"""Catégorie, titre réécrit et légende Instagram d'une actu."""
import re

from .common import hashtag, strip_accents

CATEGORIES = {
    "ANIME": {"emoji": "🎬", "tags": ["anime", "animefr", "japanime"]},
    "MANGA": {"emoji": "📚", "tags": ["manga", "mangafr", "mangaka"]},
    "MANHUA": {"emoji": "🐉", "tags": ["manhua", "manhuafr", "donghua"]},
    "WEBTOON": {"emoji": "📱", "tags": ["webtoon", "manhwa", "webtoonfr"]},
    "ACTU": {"emoji": "📰", "tags": ["otaku", "japon"]},
}


def classify(item):
    text = strip_accents((item["title"] + " " + " ".join(item["tags"])).lower())
    if item.get("source") == "Crunchyroll News" and not re.search(r"\b(manga|tome|webtoon|manhua)\b", text):
        return "ANIME"  # Crunchyroll parle surtout d'anime
    if "manhua" in text or "donghua" in text:
        return "MANHUA"
    if "adapte en anime" in text or "anime" in text or "japanime" in text:
        return "ANIME"
    if "webtoon" in text or "manhwa" in text:
        return "WEBTOON"
    if "manga" in text or "mangaka" in text:
        return "MANGA"
    return "ACTU"


# (motif sur le titre source, gabarit du titre affiché). {w} = nom de l'œuvre capturé.
RULES = [
    (r"^l[’']anime (?P<w>.+?),? en teaser vid[ée]o$", "{w} dévoile un teaser vidéo"),
    (r"^l[’']anime (?P<w>.+?),? en (trailer|bande[- ]annonce)$", "{w} : nouveau trailer"),
    (r"^l[’']anime (?P<w>.+?),? en affiche teaser$", "{w} : première affiche teaser"),
    (r"^l[’']anime (?P<w>.+?),? en annonce vid[ée]o$", "{w} : vidéo d'annonce"),
    (r"^l[’']anime (?P<w>.+?),? annonc[ée] en vid[ée]o$", "Nouvel anime annoncé : {w}"),
    (r"^l[’']anime (?P<w>.+?),? annonc[ée]$", "Nouvel anime annoncé : {w}"),
    (r"^l[’']anime (?P<w>.+?),? dat[ée]$", "{w} a enfin une date"),
    (r"^le (manga|webtoon|light novel|roman) (?P<w>.+?) adapt[ée] en anime(?P<x>.*)$", "{w} adapté en anime{x}"),
    (r"^toutes les inf(os|ormations) sur l[’']anime (?P<w>.+)$", "{w} : toutes les nouvelles infos"),
    (r"^premi[èe]re affiche de l[’']anime (?P<w>.+)$", "{w} : première affiche"),
]


def rewrite_title(title):
    t = re.sub(r"^\[[^\]]+\]\s*", "", title.strip()).rstrip(".!")
    for pat, tpl in RULES:
        m = re.match(pat, t, flags=re.IGNORECASE)
        if m:
            d = {k: (v or "") for k, v in m.groupdict().items()}
            x = d.get("x", "").strip(" +·-")
            d["x"] = f" · {x.lower()}" if x else ""
            return tpl.format(**d).strip()
    return t


QUESTIONS = {
    "ANIME": ["Tu vas le regarder ? 👀", "Hype ou pas hype ? 🔥", "Tu attendais cette annonce ?",
              "Ton avis sur le studio ? 🎬", "Note ta hype sur 10 👇"],
    "MANGA": ["Tu lis ce manga ? 📖", "Ton avis sur la série ? 👇", "Tu vas le prendre en VF ?",
              "Note ce manga sur 10 👇"],
    "MANHUA": ["Tu connaissais ce manhua ? 🐉", "Ton avis ? 👇", "Tu le lis déjà ?"],
    "WEBTOON": ["Tu lis ce webtoon ? 📱", "Bonne idée cette adaptation ? 👇", "Ton avis ? 👇"],
    "ACTU": ["Ton avis ? 👇", "Ça te surprend ? 👀"],
}


def _tags(item, category, base_tags, limit=12):
    tags = []
    for t in [hashtag(item.get("work", ""))] + CATEGORIES[category]["tags"] + base_tags:
        t = t.lstrip("#")
        if t and t.lower() not in [x.lower() for x in tags]:
            tags.append(t)
    return tags[:limit]


def build_caption(item, category, headline, brand, base_tags, used_visual, ai=None):
    """Légende détaillée. Avec l'IA : explication complète de l'actu ; sans : résumé du flux."""
    cat = CATEGORIES[category]
    qs = QUESTIONS[category]
    question = (ai or {}).get("question") or (
        qs[int(item["id"], 16) % len(qs)] if all(c in "0123456789abcdef" for c in item["id"]) else qs[0])
    lines = [f"{cat['emoji']} {headline.upper()}", ""]
    if ai and ai.get("body"):
        lines += [ai["body"].strip(), ""]
        facts = [f.strip() for f in ai.get("key_facts") or [] if f and f.strip()]
        if facts:
            lines += facts + [""]
    else:
        summary = re.sub(r"\s*(L’article|L'article).*$", "", item.get("summary", "")).strip()
        summary = re.sub(r"(\.\.\.|…|&#8230;)$", "", summary).strip()
        if summary:
            if len(summary) > 400:
                summary = summary[:400].rsplit(" ", 1)[0] + "…"
            lines += [summary, ""]
    lines += [f"💬 {question}", ""]
    work = (ai or {}).get("work") or ""
    if work:
        lines.append(f"📌 Œuvre : {work}")
    lines.append(f"📰 Source : {item['source']}")
    if used_visual:
        lines.append("🖼️ Visuel officiel © ses ayants droit")
    fan = re.sub(r"\bde (Les|les) ", "des ", re.sub(r"\bde (Le|le) ", "du ", f"un pote fan de {work}")) \
        if work else "un pote qui doit savoir ça"
    lines += ["", f"📤 Partage à {fan} et enregistre le post",
              f"🔔 Abonne-toi à {brand['handle']} pour avoir les annonces en premier", ""]
    tags = []
    for t in [hashtag(work)] + list((ai or {}).get("hashtags") or []) + cat["tags"] + base_tags:
        t = re.sub(r"[^\w]", "", str(t).lstrip("#"))
        if t and len(t) >= 3 and t.lower() not in [x.lower() for x in tags]:
            tags.append(t)
    # Instagram limite à 5 hashtags par post/reel et recommande peu de hashtags, mais ciblés
    lines.append(" ".join("#" + t for t in tags[:5]))
    return "\n".join(lines)[:2150]


def build_recap_caption(entries, brand, period_label, base_tags):
    nums = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    lines = [f"🗞️ Les news anime & manga de la semaine ({period_label})", ""]
    for n, e in enumerate(entries):
        lines.append(f"{nums[n]} {e['headline']}")
    lines += ["", "Laquelle t'a le plus hypé ? Dis-le en commentaire 👇", "",
              "🖼️ Visuels officiels © leurs ayants droit", "",
              f"🔔 Abonne-toi à {brand['handle']} pour ne rien rater", "",
              " ".join("#" + t for t in (["recapanime", "newsanime"] + base_tags)[:5])]
    return "\n".join(lines)[:2150]
