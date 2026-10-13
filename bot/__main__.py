"""Point d'entrée du robot SOKUHŌ.

  python -m bot prepare        lit les flux, fabrique posts, stories et récap du dimanche (dans media/)
  python -m bot publish        publie sur Instagram ce qui est en file d'attente (une fois en ligne)
  python -m bot preview        visuels d'essai à partir des flux d'exemple, sans rien publier
  python -m bot refresh-token  prolonge le jeton Instagram de 60 jours
  python -m bot check          vérifie le jeton et affiche le compte connecté
"""
import json
import math
import re
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from PIL import Image

from . import ai, editorial, facts, feeds, reels, render
from .common import (MEDIA_DIR, ROOT, env, load_config, load_state, now_utc, save_state,
                     similar, strip_accents, title_key)

FEED_TYPES = ("post", "carousel", "reel")  # ce qui compte dans le plafond quotidien du fil


def log(*a):
    print(*a, flush=True)


def paris_now(cfg):
    return datetime.now(ZoneInfo(cfg["timezone"]))


def in_quiet_hours(cfg):
    start, end = cfg.get("quiet_hours") or [0, 0]
    h = paris_now(cfg).hour
    return start <= h < end if start < end else (h >= start or h < end)


def feed_posts_last_24h(state):
    cutoff = now_utc().timestamp() - 86400
    return sum(1 for p in state["posted"] if p.get("ts", 0) >= cutoff and p.get("type", "post") in FEED_TYPES)


def day_window(cfg):
    """Journée de publication : de la fin des heures calmes (7 h) au début suivant (1 h du matin)."""
    start_h, end_h = cfg.get("quiet_hours") or [1, 7]
    now = paris_now(cfg)
    start = now.replace(hour=end_h, minute=0, second=0, microsecond=0)
    if start > now:
        start -= timedelta(days=1)
    length = ((start_h - end_h) % 24 or 24) * 3600
    return start.timestamp(), length


def posts_today(cfg, state):
    start, _ = day_window(cfg)
    return (sum(1 for p in state["posted"] if p.get("ts", 0) >= start and p.get("type") == "post")
            + sum(1 for q in state["queue"] if q["type"] == "post"))


def target_so_far(cfg):
    """Nombre de posts qu'on devrait avoir atteint à cette heure pour finir la journée pile sur l'objectif."""
    start, length = day_window(cfg)
    frac = min(1.0, max(0.0, (now_utc().timestamp() - start) / length))
    return math.ceil(cfg["posts_per_day"] * frac)


BIG_NEWS = re.compile(r"(saison \d|season \d|film|movie|adapt|nouvel anime|nouveau projet|annonc|date de sortie|"
                      r"trailer|bande[- ]annonce|teaser|key visual|visuel|suite|retour|revient|fin du manga|dernier "
                      r"chapitre|derni[eè]re saison|record|millions|en production|reporté|report|pause)", re.I)


def is_big_news(item, headline):
    return bool(BIG_NEWS.search(strip_accents(item["title"] + " " + headline)))


def reels_today(cfg, state):
    start, _ = day_window(cfg)
    return (sum(1 for p in state["posted"] if p.get("ts", 0) >= start and p.get("type") == "reel")
            + sum(1 for q in state["queue"] if q["type"] == "reel")
            + sum(1 for r in state.get("manual_reels", []) if r["ts"] >= start))


def is_duplicate(item, state, cfg):
    key = title_key(item["title"])
    cutoff = now_utc().timestamp() - cfg["dedupe_hours"] * 3600
    recent = [p for p in state["posted"] + state["queue"] if p.get("ts", 0) >= cutoff and p.get("key")]
    if any(similar(key, p["key"]) for p in recent):
        return True
    # Même œuvre déjà traitée récemment (utile entre un site anglais et un site français)
    work = strip_accents((item.get("work") or "").lower()).strip()
    return len(work) >= 6 and any(strip_accents((p.get("work") or "").lower()).strip() == work for p in recent)


def media_name(kind, ident, ext="jpg"):
    return f"{kind}/{now_utc().strftime('%Y%m%d')}-{ident}.{ext}"


def rel(path):
    return str(path.relative_to(MEDIA_DIR)).replace("\\", "/")


# ---------------------------------------------------------------- préparation

def make_entries(item, cfg, use_visual, state, text=None):
    """Fabrique le post (ou le reel) et la story d'une actu. Renvoie [] si l'actu doit être ignorée.
    `text` : description déjà rédigée (contenus AniList), sinon IA ou bot/facts.py."""
    if text is None:
        text = ai.write(item)
    if text is not None and text.get("is_news") is False:
        log("   pas une vraie actu (critique, dossier…) → ignorée")
        return []
    if text is None and env("GEMINI_API_KEY"):
        # L'IA est prévue mais n'a pas répondu : on retente au prochain passage plutôt que publier sans description
        log("   description IA indisponible → nouvel essai au prochain passage")
        return None
    if text is None and item.get("lang", "fr") != "fr":
        log("   article en anglais sans IA disponible → ignoré")
        return []
    if text is None:
        text = facts.describe(item, editorial.classify(item))  # description détaillée sans IA
        if not text["is_news"]:
            log("   pas une vraie actu (critique, interview, dossier…) → ignorée")
            return []
        item["work"] = text["work"]
    if text and text.get("work"):
        item["work"] = text["work"]
        if is_duplicate(item, state, cfg):
            log(f"   même œuvre déjà publiée récemment ({item['work']}) → ignorée")
            return []
    category = (text or {}).get("category") or editorial.classify(item)
    rewritten = editorial.rewrite_title(item["title"])
    headline = rewritten if rewritten != item["title"].strip().rstrip(".!") else ((text or {}).get("headline") or rewritten)
    if item.get("kind"):  # contenus AniList : titre déjà rédigé
        headline = text["headline"]

    visual = None
    if use_visual:
        getters = [lambda: render.find_og_image(item["link"]), lambda: item.get("image")]
        if item.get("image_first"):
            getters.reverse()
        for get_url in getters:
            try:
                url = get_url()
                visual = render.download_image(url) if url else None
            except Exception as ex:
                log(f"   visuel indisponible ({ex})")
            if visual is not None:
                break
    if visual is None and cfg.get("require_visual") and use_visual:
        log("   pas de vrai visuel → actu ignorée")
        return []

    brand, tz = cfg["brand"], cfg["timezone"]
    card = render.save_jpeg(render.render_post(item, category, headline, brand, visual, tz),
                            MEDIA_DIR / media_name("posts", item["id"]))
    vis_path = None
    if visual is not None:  # copie du visuel, pour la couverture du récap
        vis_path = render.save_jpeg(render.cover(visual, (1080, 1350)), MEDIA_DIR / media_name("visuals", item["id"]), 80)
    caption = editorial.build_caption(item, category, headline, brand, cfg["hashtags_base"], visual is not None, text)
    base = {"id": item["id"], "headline": headline, "category": category, "link": item["link"],
            "work": item.get("work", ""),
            "key": title_key(item["title"] + " " + item.get("work", "")), "ts": now_utc().timestamp()}

    rc = cfg.get("reels", {})
    as_reel = is_big_news(item, headline) and reels_today(cfg, state) < rc.get("max_per_day", 4) \
        and not item.get("kind")  # reel uniquement pour les grosses annonces, jamais pour les compléments
    entries = []
    if as_reel:
        try:
            music = None if rc.get("mode") == "manual" or rc.get("sound") == "none" else \
                render.pick_music(rc.get("music_dir", "assets/music"),
                                  rc.get("sound") or (text or {}).get("mood"), item["id"])
            video, template = reels.make_reel(item, category, headline, (text or {}).get("key_facts"), brand, visual,
                                              MEDIA_DIR / media_name("reels", item["id"], "mp4"), music,
                                              rc.get("seconds", 12))
            log(f"   reel « {template} » monté" + (f" avec {music.name}" if music else " (sans musique : dossier vide)"))
            if rc.get("mode") == "manual":
                # Reel à publier à la main (pour ajouter l'opening depuis la bibliothèque musicale d'Instagram)
                work = item.get("work") or ""
                state.setdefault("manual_reels", []).append({
                    "id": item["id"], "ts": now_utc().timestamp(), "headline": headline, "work": work,
                    "video": rel(video), "cover": rel(card), "caption": caption,
                    "mood": (text or {}).get("mood"), "category": category, "link": item["link"],
                    "key": base["key"], "visual": rel(vis_path) if vis_path else None,
                    "sound": f"{work} opening" if work else "anime opening"})
                log("   reel ajouté à la page « Reels à publier »")
            else:
                entries.append(dict(base, type="reel", files=[rel(video), rel(card)], caption=caption,
                                    visual=rel(vis_path) if vis_path else None, card=rel(card)))
        except Exception as ex:
            log(f"   reel impossible ({ex}) → post classique")
    if not entries:
        entries.append(dict(base, type="post", files=[rel(card)], caption=caption, alt=f"{category} — {headline}",
                            visual=rel(vis_path) if vis_path else None))
    if cfg.get("stories", True) and (not item.get("kind") or cfg.get("stories_for_fillers", False)):
        story = render.save_jpeg(render.render_story(item, category, headline, brand, visual, tz),
                                 MEDIA_DIR / media_name("stories", item["id"]))
        entries.append(dict(base, type="story", files=[rel(story)], key=None))
    return entries


def prepare_news(cfg, state):
    first_run = not state["seen"]
    items = feeds.fetch_all(cfg, log)
    if not items:
        log("Aucune actu récupérée.")
        return
    items.sort(key=lambda i: i["published"])
    fresh = [i for i in items if i["id"] not in state["seen"]]
    if first_run:
        for i in fresh[:-1]:
            state["seen"][i["id"]] = now_utc().timestamp()
        fresh = fresh[-1:]
        log("Premier lancement : historique ignoré, seule l'actu la plus récente sera publiée.")

    queued = sum(1 for q in state["queue"] if q["type"] == "post")
    budget = min(cfg["max_posts_per_run"] - queued, cfg["posts_per_day"] - posts_today(cfg, state))
    use_visual = cfg.get("use_official_visuals", True) and env("USE_OFFICIAL_VISUALS", "1") != "0"
    max_age = now_utc().timestamp() - cfg["max_age_hours"] * 3600
    for item in fresh:
        if budget <= 0:
            break
        state["seen"][item["id"]] = now_utc().timestamp()
        if item["published"] < max_age:
            continue
        if is_duplicate(item, state, cfg):
            log(f"   doublon ignoré : {item['title']}")
            continue
        log(f"→ {item['title']} ({item['source']})")
        entries = make_entries(item, cfg, use_visual, state)
        if entries is None:
            state["seen"].pop(item["id"], None)
            break  # l'IA ne répond pas : inutile d'insister sur les autres actus pendant ce passage
        if entries:
            state["queue"].extend(entries)
            budget -= 1
    fill_day(cfg, state, use_visual)


def fill_day(cfg, state, use_visual):
    """Objectif « N posts par jour » : si les sites d'actu sont calmes, on complète avec les épisodes
    sortis au Japon puis les anniversaires d'œuvres (AniList), répartis régulièrement sur la journée."""
    fc = cfg.get("fillers", {})
    if not fc.get("enabled", True):
        return
    missing = min(target_so_far(cfg) - posts_today(cfg, state), fc.get("max_per_run", 2))
    if missing <= 0:
        return
    from . import anilist
    pool = []
    try:
        pool += anilist.episodes(fc.get("episode_hours", 30), fc.get("episode_min_popularity", 2000), cfg["timezone"])
    except Exception as ex:
        log(f"[AniList] épisodes indisponibles ({ex})")
    try:
        pool += anilist.anniversaries(paris_now(cfg), fc.get("anniversary_min_popularity", 40000))
    except Exception as ex:
        log(f"[AniList] anniversaires indisponibles ({ex})")
    log(f"Objectif du jour : {posts_today(cfg, state)}/{cfg['posts_per_day']} posts, "
        f"il en faut {missing} de plus maintenant ({len(pool)} compléments possibles)")
    for item, text in pool:
        if missing <= 0:
            break
        if item["id"] in state["seen"]:
            continue
        state["seen"][item["id"]] = now_utc().timestamp()
        if is_duplicate(dict(item, work=text["work"]), state, cfg):
            continue
        log(f"→ [complément] {text['headline']}")
        try:
            entries = make_entries(item, cfg, use_visual, state, text)
        except Exception as ex:
            log(f"   complément impossible ({ex})")
            continue
        if entries:
            state["queue"].extend(entries)
            missing -= 1


def recap_due(cfg, state):
    rc = cfg.get("weekly_recap", {})
    if not rc.get("enabled", True):
        return None
    now = paris_now(cfg)
    week = now.strftime("%G-W%V")
    if now.isoweekday() != rc.get("weekday", 7) or now.hour < rc.get("hour", 18) or state.get("last_recap") == week:
        return None
    return week


def prepare_recap(cfg, state, week, force=False):
    now = paris_now(cfg)
    cutoff = now_utc().timestamp() - 7 * 86400
    done = [p for p in state["posted"] if p.get("type") in ("post", "reel") and p.get("ts", 0) >= cutoff
            and p.get("card") and (MEDIA_DIR / p["card"]).exists()]
    if not done:
        log("Récap : aucune actu publiée ces 7 derniers jours.")
        return
    if len(done) < 3 and not force:
        log("Récap : moins de 3 actus publiées cette semaine, pas de récap.")
        state["last_recap"] = week
        return
    picked = done[-9:]
    start = now - timedelta(days=6)
    months = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
    label = f"{start.day} → {now.day} {months[now.month - 1]}".upper()
    visuals = [Image.open(MEDIA_DIR / p["visual"]) for p in reversed(picked) if p.get("visual")
               and (MEDIA_DIR / p["visual"]).exists()]
    cover_img = render.render_recap_cover(visuals, cfg["brand"], label, len(picked))
    cover = render.save_jpeg(cover_img, MEDIA_DIR / media_name("recap", week))
    caption = editorial.build_recap_caption(picked, cfg["brand"], label, cfg["hashtags_base"])
    base = {"id": f"recap-{week}", "headline": f"Récap {label}", "ts": now_utc().timestamp(), "key": None}
    state["queue"].append(dict(base, type="carousel", caption=caption,
                               files=[rel(cover)] + [p["card"] for p in picked]))
    if cfg.get("weekly_recap", {}).get("reel", True):
        slides = [cover_img] + [Image.open(MEDIA_DIR / p["card"]) for p in picked] + [render.render_end_card(cfg["brand"])]
        video = render.make_reel(slides, MEDIA_DIR / media_name("reels", week, "mp4"))
        state["queue"].append(dict(base, type="reel", caption=caption, files=[rel(video), rel(cover)]))
    state["last_recap"] = week
    log(f"Récap {label} : carrousel de {len(picked) + 1} images"
        + (" + reel" if cfg.get("weekly_recap", {}).get("reel", True) else ""))


def prepare_carousels(cfg, state, force=None):
    """Carrousels « utiles » à jour et heure fixes (planning, attendus, films, décompte)."""
    from . import carousels
    now = paris_now(cfg)
    week = now.strftime("%G-W%V")
    done = state.setdefault("carousels_done", {})
    for plan in cfg.get("carousels", []):
        kind = plan["kind"]
        if force and kind != force:
            continue
        if not force and (now.isoweekday() != plan["weekday"] or now.hour < plan["hour"] or done.get(kind) == week):
            continue
        done[kind] = week  # une seule tentative par semaine, même en cas d'échec
        try:
            slides, caption = carousels.BUILDERS[kind](cfg["brand"])
        except Exception as ex:
            log(f"Carrousel « {kind} » impossible ({ex})")
            continue
        if not slides or len(slides) < 3:
            log(f"Carrousel « {kind} » : pas assez de contenu cette semaine")
            continue
        files = []
        for k, sl in enumerate(slides[:10]):
            files.append(rel(render.save_jpeg(sl, MEDIA_DIR / media_name("carousels", f"{week}-{kind}-{k}"))))
        state["queue"].append({"id": f"car-{kind}-{week}", "type": "carousel", "headline": caption.split("\n")[0],
                               "key": None, "ts": now_utc().timestamp(), "caption": caption, "files": files})
        log(f"Carrousel « {kind} » : {len(files)} slides en file")


def prune_media(cfg):
    keep = cfg.get("media_keep_days", 9)
    limit = (now_utc() - timedelta(days=keep)).strftime("%Y%m%d")
    removed = 0
    for f in MEDIA_DIR.glob("*/*"):
        if f.name[:8].isdigit() and f.name[:8] < limit:
            f.unlink()
            removed += 1
    if removed:
        log(f"Ménage : {removed} ancien(s) fichier(s) supprimé(s) de media/")


def already_on_instagram(state, reels_list):
    """Premières lignes des légendes déjà publiées sur le compte (pour ne pas doubler un reel posté à la main)."""
    if not env("IG_ACCESS_TOKEN") or not reels_list:
        return set()
    try:
        from .instagram import Instagram
        ig = Instagram()
        data = ig._call("GET", f"{ig.user_id}/media", fields="caption,media_product_type", limit=40)
        return {(m.get("caption") or "").strip().splitlines()[0].strip()
                for m in data.get("data", []) if m.get("media_product_type") == "REELS" and m.get("caption")}
    except Exception as ex:
        log(f"   vérification des reels déjà publiés impossible ({ex})")
        return None


def promote_manual_reels(cfg, state):
    """Reel pas publié à la main après N heures → le robot le publie lui-même avec un jingle original."""
    rc = cfg.get("reels", {})
    hours = rc.get("manual_timeout_hours", 3)
    limit = now_utc().timestamp() - hours * 3600
    due = [r for r in state.get("manual_reels", []) if r["ts"] < limit and (MEDIA_DIR / r["video"]).exists()]
    if not due:
        return
    published = already_on_instagram(state, due)
    if published is None:
        return  # on ne sait pas : on réessaie au prochain passage plutôt que de risquer un doublon
    for r in due:
        state["manual_reels"].remove(r)
        first = r["caption"].strip().splitlines()[0].strip()
        if first in published:
            log(f"Reel déjà publié à la main : {r['headline']}")
            continue
        music = render.pick_music(rc.get("music_dir", "assets/music"), r.get("mood"), r["id"])
        src = MEDIA_DIR / r["video"]
        out = src.with_name(src.stem + "_auto.mp4")
        try:
            if music:
                reels.add_music(src, music, out, rc.get("seconds", 12))
            else:
                out = src
        except Exception as ex:
            log(f"   mixage du son impossible ({ex}) → reel publié sans musique")
            out = src
        state["queue"].append({"id": r["id"] + "-reel", "type": "reel", "headline": r["headline"],
                               "work": r.get("work", ""), "category": r.get("category"), "link": r.get("link"),
                               "key": None, "ts": now_utc().timestamp(), "caption": r["caption"],
                               "files": [rel(out), r["cover"]], "visual": r.get("visual")})
        log(f"Reel non publié à la main depuis {hours} h → publication automatique"
            + (f" avec {music.name}" if music else "") + f" : {r['headline']}")


def write_reels_page(cfg, state):
    """Page web (GitHub Pages) qui liste les reels prêts à publier à la main depuis le téléphone."""
    from . import manual_page
    reels_list = [r for r in state.get("manual_reels", []) if (MEDIA_DIR / r["video"]).exists()]
    state["manual_reels"] = reels_list
    (MEDIA_DIR / "reels").mkdir(parents=True, exist_ok=True)
    html = manual_page.build(reels_list, cfg["brand"], cfg["timezone"],
                             cfg.get("reels", {}).get("manual_timeout_hours", 3))
    page = MEDIA_DIR / "reels" / "index.html"
    if not page.exists() or page.read_text(encoding="utf-8") != html:
        page.write_text(html, encoding="utf-8")


def cmd_prepare(cfg):
    state = load_state()
    state.setdefault("last_recap", None)
    MEDIA_DIR.mkdir(exist_ok=True)
    if in_quiet_hours(cfg):
        log("Heures calmes : rien n'est préparé, les actus attendront le matin.")
    else:
        prepare_news(cfg, state)
        week = recap_due(cfg, state)
        if week:
            prepare_recap(cfg, state, week)
        prepare_carousels(cfg, state)
    prune_media(cfg)
    if env("DRY_RUN") != "1":
        promote_manual_reels(cfg, state)
    write_reels_page(cfg, state)
    save_state(state)
    log(f"File d'attente : {len(state['queue'])} élément(s).")


# ---------------------------------------------------------------- publication

def public_url(rel_path):
    base = env("PUBLIC_BASE_URL")
    if not base:
        repo = env("GITHUB_REPOSITORY")
        if not repo:
            raise SystemExit("PUBLIC_BASE_URL absent : impossible de construire l'adresse publique des médias.")
        owner, name = repo.split("/")
        base = f"https://{owner.lower()}.github.io/{name}"
    return f"{base.rstrip('/')}/{rel_path}"


def wait_online(url, tries=36):
    """GitHub Pages met en général moins d'une minute à mettre les nouveaux fichiers en ligne."""
    for _ in range(tries):
        try:
            if requests.head(url, timeout=15, allow_redirects=True).status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(5)
    return False


def publish_one(ig, entry):
    urls = [public_url(f) for f in entry["files"]]
    for u in urls:
        if not wait_online(u):
            raise TimeoutError(f"pas encore en ligne : {u}")
    t = entry["type"]
    if t == "post":
        return ig.publish_image(urls[0], entry["caption"], entry.get("alt", ""))
    if t == "story":
        return ig.publish_story(urls[0])
    if t == "carousel":
        return ig.publish_carousel(urls, entry["caption"])
    if t == "reel":
        name = f"SOKUHŌ 速報 · {entry['work']}" if entry.get("work") else "SOKUHŌ 速報 · Flash info"
        return ig.publish_reel(urls[0], entry["caption"], urls[1] if len(urls) > 1 else None, name)
    raise ValueError(f"type inconnu : {t}")


def cmd_publish(cfg):
    from .instagram import Instagram, InstagramError
    state = load_state()
    if not state["queue"]:
        log("Rien à publier.")
        return
    # Les actus restées trop longtemps en file (jeton absent, panne…) ne sont plus des « flashs » : on les retire.
    limit = now_utc().timestamp() - cfg["max_age_hours"] * 3600
    stale = [q for q in state["queue"] if q["type"] in ("post", "story") and q.get("ts", 0) < limit]
    if stale:
        state["queue"] = [q for q in state["queue"] if q not in stale]
        save_state(state)
        log(f"{len(stale)} élément(s) trop ancien(s) retiré(s) de la file.")
    if env("DRY_RUN") != "1" and not env("IG_ACCESS_TOKEN"):
        log("⚠️ Secret IG_ACCESS_TOKEN pas encore ajouté : rien n'est publié (les visuels sont quand même fabriqués).")
        return
    if env("DRY_RUN") == "1":
        log(f"DRY_RUN : {len(state['queue'])} élément(s) prêts, rien n'est envoyé à Instagram.")
        for q in state["queue"]:
            log(f"   [{q['type']}] {q['headline']} → {', '.join(q['files'])}")
        return
    if time.time() < state.get("ig_pause_until", 0):
        log("⏸️ Instagram a demandé de ralentir : pause, on reprend au prochain créneau.")
        return
    if in_quiet_hours(cfg):
        log("Heures calmes : rien n'est publié avant le matin.")
        return
    ig = Instagram(user_id=env("IG_USER_ID") or state.get("ig_user_id"))
    state["ig_user_id"] = ig.user_id  # évite un appel « me » à chaque passage
    cap = cfg.get("api_daily_limit", 45)
    used = api_used_24h(state)
    # Anti-doublon : Instagram renvoie parfois une erreur alors que la publication est bien partie.
    # On relit donc les dernières publications du compte et on retire de la file ce qui y est déjà.
    try:
        online = {first_line(m.get("caption")) for m in ig.recent_media()}
    except Exception as ex:
        log(f"Lecture des dernières publications impossible ({ex}) → on ne publie rien ce passage (sécurité anti-doublon)")
        state["ig_pause_until"] = time.time() + 1800
        save_state(state)
        return
    keep = []
    for e in state["queue"]:
        if e["type"] != "story" and first_line(e.get("caption")) in online:
            log(f"   déjà en ligne, retiré de la file : {e['headline']}")
            state["posted"].append({k: e.get(k) for k in ("id", "type", "headline", "key", "link", "visual", "work")}
                                   | {"ts": now_utc().timestamp(), "media_id": "?",
                                      "card": e["files"][0] if e["type"] == "post" else e.get("card")})
            continue
        if e["type"] == "story" and e.get("errors"):
            continue  # story déjà tentée : peut-être partie malgré l'erreur, on ne risque pas de doublon
        keep.append(e)
    state["queue"] = keep
    # Il faut garder de la place pour les posts encore attendus aujourd'hui : les stories passent après.
    reserve = max(0, cfg["posts_per_day"] - posts_today(cfg, state))
    order = {"post": 0, "carousel": 0, "reel": 1, "story": 2}
    queue = sorted(state["queue"], key=lambda e: order.get(e["type"], 3))
    remaining, failed_posts, feed_done = [], set(), 0
    max_feed = cfg.get("max_publish_per_run", 2)
    for n, entry in enumerate(queue):
        t = entry["type"]
        if t == "story" and (entry["id"] in failed_posts or any(q["id"] == entry["id"] and q["type"] != "story"
                                                                  for q in remaining)):
            remaining.append(entry)  # la story attend que son post soit passé
            continue
        if t in ("post", "carousel", "reel") and feed_done >= max_feed:
            remaining.append(entry)  # on étale : pas de rafale de posts
            continue
        if used >= cap or (t == "story" and used >= cap - reserve):
            if t == "story":
                log(f"   story abandonnée pour garder le quota aux posts : {entry['headline']}")
            else:
                remaining.append(entry)
            continue
        try:
            media_id = publish_one(ig, entry)
            used += 1
            if t != "story":
                feed_done += 1
            log(f"✅ [{t}] {entry['headline']} (id {media_id})")
            done = {k: entry.get(k) for k in ("id", "type", "headline", "key", "link", "visual", "work")}
            done.update(media_id=media_id, ts=now_utc().timestamp(),
                        card=entry["files"][0] if t == "post" else entry.get("card"))
            state["posted"].append(done)
        except TimeoutError as ex:
            log(f"⏳ {ex} — nouvel essai au prochain passage")
            remaining.append(entry)
            failed_posts.add(entry["id"])
        except (InstagramError, requests.RequestException) as ex:
            msg = str(ex).lower()
            if any(k in msg for k in ("too many actions", "2207042", "rate limit", "request limit", "limit reached")):
                # Instagram freine : on ne gaspille pas d'essais, on met tout en pause une heure.
                state["ig_pause_until"] = time.time() + 2 * 3600
                entry["errors"] = entry.get("errors", 0) + 1  # vérifié au prochain passage (anti-doublon)
                log(f"⏸️ Instagram freine ({ex}) → pause de 2 h ; au retour, le robot vérifie d'abord si c'est parti")
                remaining += [e for e in queue[n:] if e not in remaining]
                break
            entry["errors"] = entry.get("errors", 0) + 1
            log(f"❌ [{t}] échec {entry['errors']}/3 : {entry['headline']} — {ex}")
            failed_posts.add(entry["id"])
            if entry["errors"] < 3:
                remaining.append(entry)
    state["queue"] = remaining
    save_state(state)


def first_line(caption):
    return (caption or "").strip().split("\n")[0].strip()


def api_used_24h(state):
    cutoff = now_utc().timestamp() - 86400
    return sum(1 for p in state["posted"] if p.get("ts", 0) >= cutoff)


# ---------------------------------------------------------------- outils

def cmd_preview(cfg):
    out = ROOT / "preview"
    out.mkdir(exist_ok=True)
    fixtures = ROOT / "tests" / "fixtures"
    for src in cfg["sources"]:
        f = fixtures / (src["name"].lower().replace(" ", "_") + ".xml")
        if not f.exists():
            continue
        for item in feeds.parse_feed(f.read_bytes(), src)[:4]:
            cat, head = editorial.classify(item), editorial.rewrite_title(item["title"])
            render.save_jpeg(render.render_post(item, cat, head, cfg["brand"], None, cfg["timezone"]),
                             out / f"{item['id']}.jpg")
            (out / f"{item['id']}.txt").write_text(
                editorial.build_caption(item, cat, head, cfg["brand"], cfg["hashtags_base"], False), encoding="utf-8")
            log(f"{item['id']}.jpg  [{cat}]  {head}")


def cmd_recap_now(cfg):
    """Force le récap tout de suite (utile pour tester)."""
    state = load_state()
    prepare_recap(cfg, state, paris_now(cfg).strftime("%G-W%V"), force=True)
    save_state(state)


def cmd_carousel_now(cfg):
    """python -m bot carousel-now week|upcoming|movies|countdown"""
    state = load_state()
    MEDIA_DIR.mkdir(exist_ok=True)
    prepare_carousels(cfg, state, force=sys.argv[2] if len(sys.argv) > 2 else "week")
    save_state(state)


def cmd_refresh_token(cfg):
    from .instagram import refresh_token
    token, expires = refresh_token(env("IG_ACCESS_TOKEN"))
    log(f"Jeton prolongé : valable encore {expires // 86400} jours.")
    out = env("NEW_TOKEN_FILE")
    if out:
        with open(out, "w") as f:
            f.write(token)


def cmd_check(cfg):
    from .instagram import Instagram
    ig = Instagram()
    log(f"Compte connecté : @{ig.me().get('username')} (id {ig.user_id})")
    log(f"Quota de publication : {json.dumps(ig.quota())}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    cfg = load_config()
    commands = {"prepare": cmd_prepare, "publish": cmd_publish, "preview": cmd_preview, "recap-now": cmd_recap_now,
                "carousel-now": cmd_carousel_now,
                "refresh-token": cmd_refresh_token, "check": cmd_check}
    if cmd not in commands:
        print(__doc__)
        sys.exit(1)
    commands[cmd](cfg)


if __name__ == "__main__":
    main()
