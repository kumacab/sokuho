"""Point d'entrée du robot SOKUHŌ.

  python -m bot prepare        lit les flux, fabrique posts, stories et récap du dimanche (dans media/)
  python -m bot publish        publie sur Instagram ce qui est en file d'attente (une fois en ligne)
  python -m bot preview        visuels d'essai à partir des flux d'exemple, sans rien publier
  python -m bot refresh-token  prolonge le jeton Instagram de 60 jours
  python -m bot check          vérifie le jeton et affiche le compte connecté
"""
import json
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from PIL import Image

from . import editorial, feeds, render
from .common import (MEDIA_DIR, ROOT, env, load_config, load_state, now_utc, save_state,
                     similar, title_key)

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


def is_duplicate(item, state, cfg):
    key = title_key(item["title"])
    cutoff = now_utc().timestamp() - cfg["dedupe_hours"] * 3600
    recent = [p for p in state["posted"] + state["queue"] if p.get("ts", 0) >= cutoff and p.get("key")]
    return any(similar(key, p["key"]) for p in recent)


def media_name(kind, ident, ext="jpg"):
    return f"{kind}/{now_utc().strftime('%Y%m%d')}-{ident}.{ext}"


def rel(path):
    return str(path.relative_to(MEDIA_DIR)).replace("\\", "/")


# ---------------------------------------------------------------- préparation

def make_entries(item, cfg, use_visual):
    """Fabrique le post (et sa story) d'une actu. Renvoie [] si l'actu doit être ignorée."""
    category = editorial.classify(item)
    headline = editorial.rewrite_title(item["title"])
    visual = None
    if use_visual:
        try:
            url = render.find_og_image(item["link"])
            visual = render.download_image(url) if url else None
        except Exception as ex:
            log(f"   visuel indisponible ({ex})")
    if visual is None and cfg.get("require_visual") and use_visual:
        log("   pas de vrai visuel → actu ignorée")
        return []
    brand, tz = cfg["brand"], cfg["timezone"]
    card = render.save_jpeg(render.render_post(item, category, headline, brand, visual, tz),
                            MEDIA_DIR / media_name("posts", item["id"]))
    vis_path = None
    if visual is not None:  # petite copie du visuel, pour la couverture du récap
        vis_path = render.save_jpeg(render.cover(visual, (1080, 1350)), MEDIA_DIR / media_name("visuals", item["id"]), 80)
    caption = editorial.build_caption(item, category, headline, brand, cfg["hashtags_base"], visual is not None)
    base = {"id": item["id"], "headline": headline, "category": category, "link": item["link"],
            "key": title_key(item["title"]), "ts": now_utc().timestamp()}
    entries = [dict(base, type="post", files=[rel(card)], caption=caption, alt=f"{category} — {headline}",
                    visual=rel(vis_path) if vis_path else None)]
    if cfg.get("stories", True):
        story = render.save_jpeg(render.render_story(item, category, headline, brand, visual, tz),
                                 MEDIA_DIR / media_name("stories", item["id"]))
        entries.append(dict(base, type="story", files=[rel(story)], key=None))
    if cfg.get("reel_per_post", False):
        cover_img = Image.open(card)
        video = render.make_reel([cover_img], MEDIA_DIR / media_name("reels", item["id"], "mp4"), 6)
        entries.append(dict(base, type="reel", files=[rel(video), rel(card)], caption=caption, key=None))
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

    queued_feed = sum(1 for q in state["queue"] if q["type"] in FEED_TYPES)
    budget = min(cfg["max_posts_per_run"], cfg["max_posts_per_day"] - feed_posts_last_24h(state)) - queued_feed
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
        entries = make_entries(item, cfg, use_visual)
        if entries:
            state["queue"].extend(entries)
            budget -= 1


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
    done = [p for p in state["posted"] if p.get("type") == "post" and p.get("ts", 0) >= cutoff
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
    prune_media(cfg)
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
        return ig.publish_reel(urls[0], entry["caption"], urls[1] if len(urls) > 1 else None)
    raise ValueError(f"type inconnu : {t}")


def cmd_publish(cfg):
    from .instagram import Instagram, InstagramError
    state = load_state()
    if not state["queue"]:
        log("Rien à publier.")
        return
    if env("DRY_RUN") == "1":
        log(f"DRY_RUN : {len(state['queue'])} élément(s) prêts, rien n'est envoyé à Instagram.")
        for q in state["queue"]:
            log(f"   [{q['type']}] {q['headline']} → {', '.join(q['files'])}")
        return
    ig = Instagram()
    remaining, failed_posts = [], set()
    for entry in state["queue"]:
        if entry["type"] == "story" and entry["id"] in failed_posts:
            remaining.append(entry)  # la story attend que son post soit passé
            continue
        try:
            media_id = publish_one(ig, entry)
            log(f"✅ [{entry['type']}] {entry['headline']} (id {media_id})")
            done = {k: entry.get(k) for k in ("id", "type", "headline", "key", "link", "visual")}
            done.update(media_id=media_id, ts=now_utc().timestamp(),
                        card=entry["files"][0] if entry["type"] == "post" else None)
            state["posted"].append(done)
        except TimeoutError as ex:
            log(f"⏳ {ex} — nouvel essai au prochain passage")
            remaining.append(entry)
            failed_posts.add(entry["id"])
        except (InstagramError, requests.RequestException) as ex:
            entry["errors"] = entry.get("errors", 0) + 1
            log(f"❌ [{entry['type']}] échec {entry['errors']}/3 : {entry['headline']} — {ex}")
            failed_posts.add(entry["id"])
            if entry["errors"] < 3:
                remaining.append(entry)
    state["queue"] = remaining
    save_state(state)


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
                "refresh-token": cmd_refresh_token, "check": cmd_check}
    if cmd not in commands:
        print(__doc__)
        sys.exit(1)
    commands[cmd](cfg)


if __name__ == "__main__":
    main()
