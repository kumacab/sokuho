"""Lecture des flux RSS et transformation en « actus » normalisées."""
import hashlib
import html
import re
from calendar import timegm
from datetime import datetime, timezone

import feedparser
import requests

from .common import USER_AGENT, strip_accents

GENERIC_TAGS = {"anime", "manga", "manhua", "webtoon", "manhwa", "japanime", "actus",
                "interviews et portraits manga", "interview et portraits japanime",
                "japan expo 2026", "jeu video", "drama", "cinema"}


PUBLISHERS = {"doki-doki", "ki-oon", "glenat", "kana", "pika", "kurokawa", "delcourt", "vega", "nobi nobi",
              "kaze", "crunchyroll", "ankama", "mangetsu", "meian", "akata", "soleil", "casterman", "panini",
              "noeve", "noeve grafx", "michel lafon", "hachette", "naban", "kotoji", "taifu", "ototo", "omaké books"}


def _norm(s):
    return strip_accents(s.lower()).replace("’", "'").replace("`", "'")


def _work_name(title, tags):
    """Nom de l'œuvre : le tag qui apparaît dans le titre, sinon le premier tag non générique."""
    cands = []
    for t in tags:
        n = _norm(t)
        if n in GENERIC_TAGS or n in PUBLISHERS or n.startswith("editions"):
            continue
        cands += [t, re.split(r" - | \(", t)[0].strip()]
    nt = _norm(title)
    in_title = [t for t in cands if t and _norm(t) in nt]
    return max(in_title, key=len) if in_title else ""


def parse_feed(raw_bytes, source):
    parsed = feedparser.parse(raw_bytes)
    items = []
    for e in parsed.entries:
        link = e.get("link", "")
        title = html.unescape(e.get("title", "")).strip()
        if not link or not title:
            continue
        tags = [html.unescape(t.get("term", "")).strip() for t in e.get("tags", []) if t.get("term")]
        ts = e.get("published_parsed") or e.get("updated_parsed")
        published = datetime.fromtimestamp(timegm(ts), timezone.utc) if ts else datetime.now(timezone.utc)
        summary = re.sub(r"<[^>]+>", " ", html.unescape(e.get("summary", "")))
        items.append({
            "id": hashlib.sha1(link.encode()).hexdigest()[:12],
            "title": title,
            "link": link,
            "published": published.timestamp(),
            "tags": tags,
            "work": _work_name(title, tags),
            "summary": re.sub(r"\s+", " ", summary).strip(),
            "source": source["name"],
        })
    return [i for i in items if keep(i, source)]


def keep(item, source):
    cats = [_norm(t) for t in item["tags"]]
    title = _norm(item["title"])
    inc = [_norm(x) for x in source.get("include_categories", [])]
    exc = [_norm(x) for x in source.get("exclude_categories", [])]
    if inc and not any(any(i in c for i in inc) for c in cats) and not any(i in title for i in inc):
        return False
    if any(any(x in c for x in exc) for c in cats[:1]):
        return False
    if any(_norm(x) in title for x in source.get("exclude_title", [])):
        return False
    return True


def fetch_source(source, timeout=20):
    r = requests.get(source["url"], headers={"User-Agent": USER_AGENT}, timeout=timeout)
    r.raise_for_status()
    return parse_feed(r.content, source)


def fetch_all(config, log=print):
    items = []
    for s in config["sources"]:
        try:
            got = fetch_source(s)
            log(f"[flux] {s['name']} : {len(got)} actus retenues")
            items.extend(got)
        except Exception as ex:  # une source en panne ne bloque pas les autres
            log(f"[flux] {s['name']} : ÉCHEC ({ex})")
    return items
