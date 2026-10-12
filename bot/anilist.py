"""Contenus de complément tirés de l'API publique et gratuite d'AniList (https://docs.anilist.co).

Sert à tenir l'objectif de posts par jour quand les sites d'actu sont calmes :
  1. « Épisode sorti » : les nouveaux épisodes des séries suivies, juste après leur diffusion au Japon ;
  2. « Anniversaire » : les œuvres connues sorties un jour comme aujourd'hui.
Chaque élément arrive avec sa description déjà rédigée (même format que bot/facts.py).
"""
import hashlib
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

API = "https://graphql.anilist.co"
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre"]
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
GENRES_FR = {"Action": "Action", "Adventure": "Aventure", "Comedy": "Comédie", "Drama": "Drame",
             "Fantasy": "Fantasy", "Horror": "Horreur", "Mystery": "Mystère", "Psychological": "Psychologique",
             "Romance": "Romance", "Sci-Fi": "Science-fiction", "Slice of Life": "Tranche de vie",
             "Sports": "Sport", "Supernatural": "Surnaturel", "Thriller": "Thriller", "Mecha": "Mecha",
             "Music": "Musique", "Mahou Shoujo": "Magical girl"}
MOOD = {"Horror": "dark", "Thriller": "dark", "Psychological": "dark", "Comedy": "fun", "Slice of Life": "chill",
        "Romance": "emotional", "Drama": "emotional", "Action": "hype", "Sports": "hype", "Adventure": "epic",
        "Fantasy": "epic"}
NO_GENRES = ["Ecchi", "Hentai"]

MEDIA_FIELDS = """id type format countryOfOrigin popularity isAdult episodes chapters genres siteUrl
  title{romaji english} coverImage{extraLarge} startDate{year month day}
  studios(isMain:true){nodes{name}} externalLinks{site type}"""


def _query(query, variables, tries=3):
    for n in range(tries):
        r = requests.post(API, json={"query": query, "variables": variables}, timeout=30)
        if r.status_code == 429:  # limite de débit : on patiente
            time.sleep(int(r.headers.get("Retry-After", 30)))
            continue
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            raise RuntimeError(data["errors"][0].get("message"))
        return data["data"]
    raise RuntimeError("AniList : trop de requêtes")


def _id(*parts):
    return hashlib.sha1("-".join(map(str, parts)).encode()).hexdigest()[:12]


def _title(m):
    """Titre le plus court entre l'anglais et le romaji ; « Season 2 » devient « saison 2 »."""
    names = [t.strip() for t in (m["title"].get("english"), m["title"]["romaji"]) if t]
    names = [re.split(r"\s*:\s+", t)[0] if len(t) > 45 else t for t in names]  # titres de light novel à rallonge
    t = names[0] if len(names[0]) <= 45 else min(names, key=len)  # l'anglais d'abord, plus parlant en France
    t = re.sub(r"\s*(?:Season|Saison)\s*(\d+)", r" saison \1", t)
    t = re.sub(r"\s*(\d+)(?:st|nd|rd|th) Season", r" saison \1", t)
    return re.sub(r"\s{2,}", " ", t).strip().rstrip(".")


def de(work):
    """« de Overgeared » → « d’Overgeared »."""
    return f"d’{work}" if re.match(r"[AEIOUYÉÈÊaeiouyéèê]", work) else f"de {work}"


def _category(m):
    if m["type"] == "ANIME":
        return "ANIME"
    return {"CN": "MANHUA", "KR": "WEBTOON"}.get(m["countryOfOrigin"], "MANGA")


def _ok(m, min_pop):
    return (not m["isAdult"] and m["popularity"] >= min_pop and not set(m["genres"]) & set(NO_GENRES)
            and m["coverImage"].get("extraLarge"))


def _common_facts(m):
    facts = []
    studio = ", ".join(s["name"] for s in m["studios"]["nodes"][:2])
    if studio:
        facts.append(f"🎬 Studio : {studio}")
    genres = [GENRES_FR.get(g, g) for g in m["genres"][:3]]
    if genres:
        facts.append(f"🏷️ Genres : {', '.join(genres)}")
    return facts, studio


def _streaming(m):
    sites = []
    for link in m.get("externalLinks") or []:
        if link["type"] == "STREAMING" and link["site"] in ("Crunchyroll", "ADN", "Netflix", "Disney Plus",
                                                            "Amazon Prime Video", "HIDIVE") \
                and link["site"] not in sites:
            sites.append(link["site"].replace("Disney Plus", "Disney+"))
    return sites[:2]


def _mood(m):
    return next((MOOD[g] for g in m["genres"] if g in MOOD), "hype")


def _item(m, ident, title, published, kind):
    return {"id": ident, "title": title, "link": m["siteUrl"], "source": "AniList", "summary": "",
            "tags": [], "published": published, "lang": "fr", "image": m["coverImage"]["extraLarge"],
            "image_first": True, "kind": kind}


def episodes(hours=30, min_pop=2000, tz="Europe/Paris"):
    """Épisodes diffusés au Japon dans les dernières heures, des plus populaires aux moins suivis."""
    q = """query($a:Int,$b:Int,$p:Int){Page(page:$p,perPage:50){pageInfo{hasNextPage}
      airingSchedules(airingAt_greater:$a,airingAt_lesser:$b,sort:TIME){episode airingAt media{%s}}}}""" % MEDIA_FIELDS
    now = int(time.time())
    rows, page = [], 1
    while page <= 4:
        data = _query(q, {"a": now - hours * 3600, "b": now, "p": page})["Page"]
        rows += data["airingSchedules"]
        if not data["pageInfo"]["hasNextPage"]:
            break
        page += 1
    out = []
    for s in sorted(rows, key=lambda s: -s["media"]["popularity"]):
        m, ep = s["media"], s["episode"]
        if not _ok(m, min_pop) or m["format"] not in ("TV", "TV_SHORT", "ONA"):
            continue
        work = _title(m)
        when = datetime.fromtimestamp(s["airingAt"], ZoneInfo(tz))
        total = m.get("episodes")
        last = total and ep == total
        facts, studio = _common_facts(m)
        facts.insert(0, f"📺 Épisode {ep}" + (f" sur {total}" if total else ""))
        sites = _streaming(m)
        if sites:
            facts.append(f"▶️ Streaming : {' / '.join(sites)} (catalogue variable selon les pays)")
        headline = f"{work} : {'le dernier épisode' if last else f'l’épisode {ep}'} est sorti"
        body = (f"{'Le dernier épisode' if last else f'L’épisode {ep}'} {de(work)} a été diffusé au Japon "
                f"{DAYS[when.weekday()]} {when.day} {MONTHS[when.month - 1]} à {when:%Hh%M} (heure de Paris).")
        if studio:
            body += f" La série est produite par {studio}."
        if total and not last:
            body += f" Elle compte {total} épisodes au total : encore {total - ep} à venir."
        if last:
            body += " C’est la fin de la diffusion de cette saison."
        body += " (via AniList)"
        question = (f"Ton verdict sur la fin {de(work)} ? 👇" if last
                    else f"Tu suis {work} ? Ton avis sur l’épisode {ep} 👇")
        item = _item(m, _id("ep", m["id"], ep), headline, s["airingAt"], "episode")
        text = {"is_news": True, "headline": headline, "work": work, "category": _category(m), "body": body,
                "key_facts": facts, "mood": _mood(m), "question": question, "hashtags": []}
        out.append((item, text))
    return out


def anniversaries(day=None, min_pop=40000, min_years=2, n=20, tz="Europe/Paris"):
    """Œuvres populaires sorties un jour comme aujourd'hui (anime ou manga)."""
    day = day or datetime.now(ZoneInfo(tz))
    q = """query($d:String,$no:[String]){Page(perPage:%d){
      media(startDate_like:$d,sort:POPULARITY_DESC,isAdult:false,genre_not_in:$no){%s}}}""" % (n, MEDIA_FIELDS)
    rows = _query(q, {"d": f"%{day:%m%d}", "no": NO_GENRES})["Page"]["media"]
    out = []
    for m in rows:
        years = day.year - (m["startDate"].get("year") or day.year)
        if not _ok(m, min_pop) or years < min_years:
            continue
        work = _title(m)
        cat = _category(m)
        anime = m["type"] == "ANIME"
        facts, studio = _common_facts(m)
        if anime and m.get("episodes"):
            facts.insert(0, f"📺 {m['episodes']} épisodes")
        if not anime and m.get("chapters"):
            facts.insert(0, f"📖 {m['chapters']} chapitres")
        facts.insert(0, f"🎂 Sortie le {m['startDate']['day']} {MONTHS[m['startDate']['month'] - 1]} "
                        f"{m['startDate']['year']}")
        nature = {"ANIME": "l’anime", "MANGA": "le manga", "MANHUA": "le manhua", "WEBTOON": "le webtoon"}[cat]
        headline = f"{work} fête ses {years} ans"
        start = f"{m['startDate']['day']} {MONTHS[m['startDate']['month'] - 1]} {m['startDate']['year']}"
        body = (f"Il y a {years} ans jour pour jour, le {start}, {nature} {work} "
                + ("était diffusé pour la première fois au Japon." if anime
                   else "commençait sa publication."))
        if anime and studio:
            body += f" L’animation est signée {studio}."
        body += " (via AniList)"
        item = _item(m, _id("anniv", m["id"], day.year), headline, int(time.time()), "anniversary")
        text = {"is_news": True, "headline": headline, "work": work, "category": cat, "body": body,
                "key_facts": facts, "mood": "emotional" if years >= 10 else _mood(m),
                "question": f"Tu l’as découvert quand, {work} ? 👇", "hashtags": []}
        out.append((item, text))
    return out
