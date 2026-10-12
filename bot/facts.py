"""Description détaillée SANS IA : lecture de l'article et extraction des infos clés.

Le robot lit l'article complet et en tire :
- l'accroche (les deux premières phrases, courtes, avec la source citée) ;
- les infos clés repérées dans le texte : date ou période de sortie, studio, réalisation,
  plateforme de diffusion, éditeur français, nombre d'épisodes ou de tomes, saison.
"""
import re

from .ai import article_text
from .common import strip_accents

MONTHS = "janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre"
SEASONS = "hiver|printemps|été|ete|automne"
PLATFORMS = ["Crunchyroll", "ADN", "Anime Digital Network", "Netflix", "Prime Video", "Disney+", "Max",
             "HIDIVE", "Apple TV+", "J-One", "Game One", "YouTube"]
PUBLISHERS = ["Glénat", "Kana", "Ki-oon", "Pika", "Kurokawa", "Delcourt", "Tonkam", "Kazé", "Crunchyroll Manga",
              "Vega", "Dupuis", "Mangetsu", "Meian", "Akata", "Doki-Doki", "nobi nobi", "Noeve Grafx", "Michel Lafon",
              "Panini", "Soleil", "Casterman", "Naban", "Kotoji", "Taifu", "Ototo", "Webtoon Factory", "Verytoon",
              "Piccoma", "Hachette Heroes", "Omaké Books", "Komikku", "Fabelo", "Pika Webtoon"]
NOT_WORKS = {"japon", "france", "coree", "chine", "mexique", "usa", "etats-unis", "japan expo", "netflix",
             "crunchyroll", "adn", "prime video", "disney+", "trailer", "teaser", "affiche", "news", "actualite"}
NOT_NEWS = re.compile(r"\b(critique|review|interview|entretien|dossier|avis|test|quiz|sondage|concours|"
                      r"souvenirs|portrait|chronique|top \d+|classement des lecteurs)\b", re.I)


def is_news(item):
    return not NOT_NEWS.search(strip_accents(item["title"]))


def clean_work(work):
    return "" if strip_accents((work or "").lower()).strip() in NOT_WORKS else work


ABBR = re.compile(r"\b(Dr|Mr|Mme|M|St|Vol|No|T|Ep|Éd|Prof)\.\s")


def sentences(text):
    text = ABBR.sub(lambda m: m.group(1) + "\u2024 ", text)  # protège « Dr. Stone » du découpage en phrases
    parts = re.split(r"(?<=[.!?…])\s+(?=[A-ZÀ-ÖØ-ÞÉ«\"“])", text)
    return [p.strip().replace("\u2024", ".") for p in parts if 25 <= len(p.strip()) <= 400]


def lead(text, max_chars=380):
    out = ""
    for s in sentences(text):
        if re.search(r"(cookie|abonnez|newsletter|cliquez|publicit|l’article .* est apparu)", s, re.I):
            continue
        if len(out) + len(s) > max_chars:
            break
        out = (out + " " + s).strip()
        if len(out) > 220:
            break
    return out


def find(pattern, text, group=1, flags=re.I):
    m = re.search(pattern, text, flags)
    return re.sub(r"\s+", " ", m.group(group)).strip(" ,.;:") if m else ""


RELEASE = r"(?:diffus|sortie|sortira|arrive|arrivera|début|commence|prévu|programm|premi|lancement|disponible|en salles|au cinéma|à partir)"


def _future(dates, now_year):
    for d in dates:
        y = re.search(r"(\d{4})", d)
        if y and int(y.group(1)) >= now_year:
            return d
    return ""


def extract_facts(text, category=None, now_year=None):
    import datetime
    now_year = now_year or datetime.date.today().year
    facts = []
    date_pat = rf"(?:\d{{1,2}}(?:er)? (?:{MONTHS}) \d{{4}}|(?:{SEASONS}) \d{{4}}|(?:{MONTHS}) \d{{4}})"
    # 1) une date future dans une phrase qui parle de sortie/diffusion, 2) sinon n'importe quelle date future
    near = [m.group(0) for s in sentences(text) if re.search(RELEASE, s, re.I)
            for m in re.finditer(date_pat, s, re.I)]
    date = _future(near, now_year) or _future([m.group(0) for m in re.finditer(date_pat, text, re.I)], now_year)
    if date:
        facts.append(f"📅 Date : {date}")
    studio = find(r"(?:[Ss]tudios?|STUDIO) ([A-Z0-9][\w&'’-]*(?: [A-Z0-9][\w&'’-]*){0,2})(?=[\s,.;)]|$)", text, flags=0)
    studio = re.sub(r"\b(Synopsis|Staff|Casting|Cast|Le|La|Les)\b.*$", "", studio).strip(" .")
    if studio and len(studio) > 1:
        facts.append(f"🎬 Studio : {studio}")
    director = find(r"(?:[Rr]éalis(?:é|ée|ation) (?:par|de)|sous la direction de|[Rr]éalisateur[^:]{0,20}:)\s*"
                    r"([A-Z][\w'’-]+(?: [A-Z][\w'’-]+){1,2})", text, flags=0)
    if director:
        facts.append(f"🎥 Réalisation : {director}")
    plats = [p for p in PLATFORMS if re.search(rf"(?<![\w]){re.escape(p)}(?![\w])", text)]
    if plats:
        facts.append(f"📺 Diffusion : {', '.join(plats[:2])}")
    if category in ("MANGA", "MANHUA", "WEBTOON", None):
        pubs = [p for p in PUBLISHERS if re.search(rf"(?:chez|aux éditions|éditions|éditeur)\s+{re.escape(p)}", text, re.I)]
        if pubs:
            facts.append(f"📚 Éditeur : {pubs[0]}")
    eps = find(r"(\d{1,3}) épisodes", text)
    if eps and category != "MANGA":
        facts.append(f"🔢 Épisodes : {eps}")
    return facts[:5]


def work_from_title(title):
    """« Dragon Ball Super: Beerus partage… » → « Dragon Ball Super: Beerus »."""
    t = re.sub(r"^(l[’']anime|le manga|le film|le webtoon|le manhua|l[’']adaptation(?: anime)? de)\s+", "", title, flags=re.I)
    for sep in (" : ", " - ", " – ", ": "):
        if sep in t:
            head = t.split(sep)[0].strip()
            if 2 <= len(head) <= 45 and not re.search(r"\b(annonc|dévoil|révèle|partage|trailer)\b", head, re.I):
                return head
    return ""


def short_headline(title, max_len=72):
    t = re.sub(r"\s+", " ", title).strip()
    if len(t) <= max_len:
        return t
    for sep in (" - ", " – ", ", "):
        if sep in t and len(t.split(sep)[0]) >= 20:
            t = t.split(sep)[0]
            if len(t) <= max_len:
                return t
    return t[:max_len].rsplit(" ", 1)[0] + "…"


MOODS = [("dark", r"horreur|zombie|mort|sombre|démon|vampire|meurtre|décès|hommage"),
         ("emotional", r"fin de|dernier chapitre|adieu|romance|amour|émotion"),
         ("fun", r"comédie|com[ée]die|kawaii|idol|slice of life|chat|cuisine"),
         ("epic", r"film|saison \d|combat|bataille|guerre|shōnen|shonen|dragon|héros"),
         ("hype", r"annonc|trailer|teaser|adapt|date|premi")]


def describe(item, category=None):
    """Remplace l'IA : même format de réponse (body, key_facts, work, mood…)."""
    text = article_text(item, max_chars=12000)
    text = re.sub(r"\s+([,.])", r"\1", text)  # « Press , » → « Press, »
    body = lead(text) or lead(item.get("summary", ""))
    if body:
        body = f"{body} (via {item['source']})"
    mood = next((m for m, pat in MOODS if re.search(pat, strip_accents(item["title"] + " " + text[:1500]), re.I)),
                "hype")
    work = clean_work(item.get("work", "")) or work_from_title(item["title"])
    return {"is_news": is_news(item), "headline": short_headline(item["title"]), "work": work,
            "category": category, "body": body, "key_facts": extract_facts(text, category),
            "question": None, "hashtags": [], "mood": mood}
