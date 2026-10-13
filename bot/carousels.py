"""Carrousels « utiles » (ceux que les gens enregistrent et partagent), générés depuis l'API publique d'AniList.

Formats :
  - planning de la semaine : un slide par jour, une carte par épisode (date, titre, épisode, plateforme) ;
  - les animes attendus la saison prochaine : 3 bandeaux par slide (« SUITE » / « NOUVEAU », titre, mois) ;
  - les films d'animation annoncés : un visuel plein cadre par slide, titre et date de sortie ;
  - le décompte : les animes qui démarrent dans les 3 semaines, avec J-N.
Identité SOKUHŌ : noir, rouge, jaune ; grosses capitales Inter Black ; un mot surligné dans une pastille rouge.
"""
import math
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFilter

from . import anilist
from .render import BG, INK, POST, RED, YELLOW, cover, download_image, draw_logo, font

W, H = POST
TZ = ZoneInfo("Europe/Paris")
DAYS = ["LUNDI", "MARDI", "MERCREDI", "JEUDI", "VENDREDI", "SAMEDI", "DIMANCHE"]
MONTHS = ["JANVIER", "FÉVRIER", "MARS", "AVRIL", "MAI", "JUIN", "JUILLET", "AOÛT", "SEPTEMBRE", "OCTOBRE",
          "NOVEMBRE", "DÉCEMBRE"]
SEASON_FR = {"WINTER": "HIVER", "SPRING": "PRINTEMPS", "SUMMER": "ÉTÉ", "FALL": "AUTOMNE"}
SEASON_OF_MONTH = {1: "WINTER", 2: "WINTER", 3: "WINTER", 4: "SPRING", 5: "SPRING", 6: "SPRING",
                   7: "SUMMER", 8: "SUMMER", 9: "SUMMER", 10: "FALL", 11: "FALL", 12: "FALL"}
NEXT = {"WINTER": "SPRING", "SPRING": "SUMMER", "SUMMER": "FALL", "FALL": "WINTER"}
# Plateformes : simple pastille de texte aux couleurs maison (pas de logos de marque)
PLATFORMS = {"Crunchyroll": ("CRUNCHYROLL", (244, 117, 33)), "ADN": ("ADN", (0, 152, 219)),
             "Netflix": ("NETFLIX", (229, 9, 20)), "Disney Plus": ("DISNEY+", (17, 60, 207)),
             "Amazon Prime Video": ("PRIME VIDEO", (0, 168, 225))}
DARK_RED = (120, 12, 28)

_cache = {}


def image(url):
    if not url:
        return None
    if url not in _cache:
        try:
            _cache[url] = download_image(url).convert("RGB")
        except Exception:
            _cache[url] = None
    return _cache[url]


# ------------------------------------------------------------------ briques graphiques

def gradient(size, c1, c2, horizontal=True):
    w, h = size
    grad = Image.linear_gradient("L").rotate(90 if horizontal else 0, expand=True).resize((w, h))
    if horizontal:
        grad = grad.transpose(Image.FLIP_LEFT_RIGHT)
    return Image.composite(Image.new("RGB", size, c2), Image.new("RGB", size, c1), grad)


def veil(img, top=0.45, strength=235):
    """Assombrit le bas de l'image pour que le texte reste lisible."""
    w, h = img.size
    mask = Image.new("L", (1, h))
    for y in range(h):
        t = max(0.0, (y / h - top) / (1 - top))
        mask.putpixel((0, y), int(strength * min(1, t * 1.25)))
    mask = mask.resize((w, h))
    img.paste(Image.new("RGB", (w, h), BG), (0, 0), mask)
    return img


def fit_font(text, max_w, size, weight="Black", min_size=28):
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    while size > min_size:
        f = font("Inter.ttf", size, weight)
        b = d.textbbox((0, 0), text, font=f)
        if b[2] - b[0] <= max_w:
            return f
        size -= 2
    return font("Inter.ttf", min_size, weight)


def text_center(d, cx, y, text, f, fill=INK, shadow=True):
    b = d.textbbox((0, 0), text, font=f)
    x = cx - (b[2] - b[0]) // 2 - b[0]
    if shadow:
        d.text((x + 3, y + 4 - b[1]), text, font=f, fill=(0, 0, 0))
    d.text((x, y - b[1]), text, font=f, fill=fill)
    return b[3] - b[1]


def pill(img, text, cx, y, max_w, size=72, lines=2, align="center", x=None):
    """Pastille dégradé rouge à liseré blanc avec le titre en capitales (1 ou 2 lignes)."""
    d = ImageDraw.Draw(img)
    words, rows = text.upper().split(), []
    f = font("Inter.ttf", size, "Black")
    while True:
        rows, cur = [], ""
        for w_ in words:
            test = (cur + " " + w_).strip()
            if d.textbbox((0, 0), test, font=f)[2] <= max_w - 60 or not cur:
                cur = test
            else:
                rows.append(cur)
                cur = w_
        rows.append(cur)
        widest = max(d.textbbox((0, 0), r, font=f)[2] for r in rows)
        if (len(rows) <= lines and widest <= max_w - 60) or size <= 30:
            break
        size -= 4
        f = font("Inter.ttf", size, "Black")
    if len(rows) > lines:
        rows = rows[:lines]
        rows[-1] = rows[-1].rstrip(".,") + "…"
    asc = d.textbbox((0, 0), "ÉQ", font=f)
    lh = int((asc[3] - asc[1]) * 1.18)
    bw = max(d.textbbox((0, 0), r, font=f)[2] for r in rows) + 60
    bh = lh * len(rows) + 30
    bx = cx - bw // 2 if align == "center" else x
    box = gradient((bw, bh), RED, DARK_RED)
    m = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, bw - 1, bh - 1], radius=18, fill=255)
    d.rounded_rectangle([bx - 4, y - 4, bx + bw + 3, y + bh + 3], radius=21, fill=INK)
    img.paste(box, (bx, y), m)
    d = ImageDraw.Draw(img)
    for i, r in enumerate(rows):
        rb = d.textbbox((0, 0), r, font=f)
        rx = bx + (bw - (rb[2] - rb[0])) // 2 - rb[0]
        d.text((rx, y + 15 + i * lh - asc[1]), r, font=f, fill=INK)
    return bx, bw, bh


def arrow(img, cx, cy, r=46):
    d = ImageDraw.Draw(img)
    d.ellipse([cx - r - 5, cy - r - 5, cx + r + 5, cy + r + 5], fill=INK)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=RED)
    d.line([cx - 20, cy, cx + 18, cy], fill=INK, width=9)
    d.line([cx + 2, cy - 18, cx + 20, cy], fill=INK, width=9)
    d.line([cx + 2, cy + 18, cx + 20, cy], fill=INK, width=9)


def corner_logo(img, brand):
    draw_logo(img, brand, 40, 40, h=64)


def mosaic(images, size=POST):
    """Couverture : 2 ou 4 visuels côte à côte."""
    img = Image.new("RGB", size, BG)
    ims = [i for i in images if i is not None][:4]
    if len(ims) >= 4:
        cells = [(0, 0), (W // 2, 0), (0, H // 2), (W // 2, H // 2)]
        for im, (x, y) in zip(ims, cells):
            img.paste(cover(im, (W // 2, H // 2), .25), (x, y))
    elif ims:
        n = len(ims)
        for k, im in enumerate(ims):
            img.paste(cover(im, (W // n, H), .2), (k * W // n, 0))
    return img


def cover_slide(images, brand, title, highlight):
    """Grosse accroche en capitales, un mot surligné, flèche vers la droite."""
    img = veil(mosaic(images), top=.30, strength=245)
    corner_logo(img, brand)
    d = ImageDraw.Draw(img)
    words = title.upper().split()
    lines, cur = [], []
    for w_ in words:
        cur.append(w_)
        if len(" ".join(cur)) >= 13:
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)
    lines = lines[:4]
    y = H - 110 - len(lines) * 128
    for ln in lines:
        text = " ".join(ln)
        f = fit_font(text, W - 120, 118)
        b = d.textbbox((0, 0), text, font=f)
        x = (W - (b[2] - b[0])) // 2 - b[0]
        for w_ in ln:
            wb = d.textbbox((0, 0), w_ + " ", font=f)
            word_w = d.textbbox((0, 0), w_, font=f)[2]
            if w_.strip("!?.,") == highlight.upper():
                hb = d.textbbox((0, 0), w_, font=f)
                d.rounded_rectangle([x - 14, y - 6, x + word_w + 14, y + (hb[3] - hb[1]) + 22], radius=16,
                                    fill=RED, outline=INK, width=4)
                d.text((x, y + 8 - hb[1]), w_, font=f, fill=INK)
            else:
                d.text((x + 4, y + 13 - b[1]), w_, font=f, fill=(0, 0, 0))
                d.text((x, y + 8 - b[1]), w_, font=f, fill=INK)
            x += wb[2]
        y += 128
    arrow(img, W - 100, H // 2 - 40)
    return img


def platform_badge(d, x, y, site, size=22):
    label, color = PLATFORMS[site]
    f = font("Inter.ttf", size, "Black")
    b = d.textbbox((0, 0), label, font=f)
    d.rounded_rectangle([x, y, x + b[2] - b[0] + 20, y + size + 14], radius=7, fill=color)
    d.text((x + 10 - b[0], y + 7 - b[1]), label, font=f, fill=INK)


def platform_of(m):
    for link in m.get("externalLinks") or []:
        if link.get("type") == "STREAMING" and link.get("site") in PLATFORMS:
            return link["site"]
    return None


def season_number(m):
    t = " ".join(x for x in (m["title"].get("english"), m["title"]["romaji"]) if x)
    n = re.search(r"(?:Season|Saison)\s*(\d+)|(\d+)(?:st|nd|rd|th) Season", t, re.I)
    if n:
        return f"SAISON {n.group(1) or n.group(2)}"
    if re.search(r"Part\s*(\d+)|Cour\s*(\d+)", t, re.I):
        return "NOUVELLE PARTIE"
    if any(e["relationType"] == "PREQUEL" for e in (m.get("relations") or {}).get("edges", [])):
        return "SUITE"
    return "NOUVEAU"


def short_title(m, limit=32):
    t = anilist._title(m) or m["title"]["romaji"]
    t = re.sub(r"\s*saison \d+$", "", t, flags=re.I)
    if len(t) > limit:
        t = re.split(r"\s*[:\-–,]\s+", t)[0]
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0] + "…"
    return t


# ------------------------------------------------------------------ données AniList

Q_SCHEDULE = """query($a:Int,$b:Int,$p:Int){Page(page:$p,perPage:50){pageInfo{hasNextPage}
  airingSchedules(airingAt_greater:$a,airingAt_lesser:$b,sort:TIME){episode airingAt media{%s bannerImage}}}}"""
Q_SEASON = """query($s:MediaSeason,$y:Int,$f:[MediaFormat],$st:MediaStatus,$p:Int){Page(page:$p,perPage:50){
  media(season:$s,seasonYear:$y,format_in:$f,status:$st,sort:POPULARITY_DESC,isAdult:false,genre_not_in:["Ecchi","Hentai"]){
  %s bannerImage}}}"""
Q_MOVIES = """query{Page(perPage:30){media(format:MOVIE,status:NOT_YET_RELEASED,sort:POPULARITY_DESC,isAdult:false,
  genre_not_in:["Ecchi","Hentai"]){%s bannerImage}}}"""


def week_schedule(min_pop=8000):
    now = datetime.now(TZ)
    start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    rows, page = [], 1
    while page <= 8:
        data = anilist._query(Q_SCHEDULE % anilist.MEDIA_FIELDS,
                              {"a": int(start.timestamp()), "b": int(end.timestamp()), "p": page})["Page"]
        rows += data["airingSchedules"]
        if not data["pageInfo"]["hasNextPage"]:
            break
        page += 1
        time.sleep(0.7)
    seen, out = set(), []
    for s in sorted(rows, key=lambda s: -s["media"]["popularity"]):
        m = s["media"]
        if m["id"] in seen or m["isAdult"] or m["popularity"] < min_pop or set(m["genres"]) & {"Ecchi", "Hentai"}:
            continue
        if m["format"] not in ("TV", "TV_SHORT", "ONA"):
            continue
        seen.add(m["id"])
        out.append((datetime.fromtimestamp(s["airingAt"], TZ), s["episode"], m))
    return start, out


def next_season(now=None):
    now = now or datetime.now(TZ)
    s = NEXT[SEASON_OF_MONTH[now.month]]
    return s, now.year + (1 if s == "WINTER" else 0)


def upcoming_season(n=18):
    s, y = next_season()
    data = anilist._query(Q_SEASON % anilist.MEDIA_FIELDS, {"s": s, "y": y, "f": ["TV", "ONA"], "p": 1})
    return s, y, [m for m in data["Page"]["media"] if m["coverImage"].get("extraLarge")][:n]


def upcoming_movies(n=9):
    data = anilist._query(Q_MOVIES % anilist.MEDIA_FIELDS, {})
    out = [m for m in data["Page"]["media"] if m["coverImage"].get("extraLarge") and (m["startDate"] or {}).get("year")]
    return out[:n]


def starting_soon(days=21, n=9):
    now = datetime.now(TZ)
    s, y = SEASON_OF_MONTH[now.month], now.year
    pool = []
    for season, year in ((s, y), next_season(now)):
        data = anilist._query(Q_SEASON % anilist.MEDIA_FIELDS,
                              {"s": season, "y": year, "f": ["TV", "ONA"], "st": "NOT_YET_RELEASED", "p": 1})
        pool += data["Page"]["media"]
    out = []
    for m in sorted(pool, key=lambda m: -m["popularity"]):
        sd = m.get("startDate") or {}
        if not all(sd.get(k) for k in ("year", "month", "day")):
            continue
        start = datetime(sd["year"], sd["month"], sd["day"], tzinfo=TZ)
        left = (start.date() - now.date()).days
        if 0 < left <= days and m["coverImage"].get("extraLarge"):
            out.append((left, m))
    return sorted(out, key=lambda x: x[0])[:n]


# ------------------------------------------------------------------ slides

def day_slide(day_name, entries, brand, bg_seed_img=None):
    img = gradient(POST, (40, 6, 14), BG, horizontal=False)
    if bg_seed_img is not None:
        glow = cover(bg_seed_img, POST).filter(ImageFilter.GaussianBlur(60))
        img = Image.blend(img, glow, .28)
    corner_logo(img, brand)
    d = ImageDraw.Draw(img)
    text_center(d, W // 2, 150, day_name, font("Inter.ttf", 120, "Black"))
    n = len(entries[:9])
    cols = 1 if n <= 3 else 2 if n <= 6 else 3
    gap = 22
    rows_n = math.ceil(n / cols)
    cw = (W - 2 * 48 - (cols - 1) * gap) // cols
    ch = min(300 if cols == 3 else 400, (H - 330 - 60 - (rows_n - 1) * gap) // rows_n)
    for k, (when, ep, m) in enumerate(entries[:9]):
        x = 48 + (k % cols) * (cw + gap)
        y = 330 + (k // cols) * (ch + gap)
        thumb = image(m.get("bannerImage")) or image(m["coverImage"]["extraLarge"])
        card = cover(thumb, (cw, ch), .3) if thumb else Image.new("RGB", (cw, ch), (40, 40, 48))
        card = veil(card, top=.25, strength=230)
        mask = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, cw - 1, ch - 1], radius=18, fill=255)
        d.rounded_rectangle([x - 3, y - 3, x + cw + 2, y + ch + 2], radius=20, fill=INK)
        img.paste(card, (x, y), mask)
        d = ImageDraw.Draw(img)
        # date + épisode
        df = font("Inter.ttf", 26, "Black")
        dt = f"{when:%d/%m} · {when:%Hh%M}"
        db = d.textbbox((0, 0), dt, font=df)
        d.rounded_rectangle([x + 12, y + 12, x + 12 + db[2] - db[0] + 20, y + 12 + 40], radius=9, fill=RED)
        d.text((x + 22 - db[0], y + 18 - db[1]), dt, font=df, fill=INK)
        # titre (2 lignes max)
        tf = font("Inter.ttf", 27 if cols == 3 else 36 if cols == 2 else 46, "ExtraBold")
        words, rows, cur = (anilist._title(m) or m["title"]["romaji"]).split(), [], ""
        for w_ in words:
            test = (cur + " " + w_).strip()
            if d.textbbox((0, 0), test, font=tf)[2] <= cw - 28 or not cur:
                cur = test
            else:
                rows.append(cur)
                cur = w_
        rows.append(cur)
        if len(rows) > 2:
            rows = rows[:2]
            rows[1] = rows[1].rstrip(",.:") + "…"
        lh = int(tf.size * 1.25)
        ty = y + ch - 56 - lh * len(rows)
        for r in rows:
            d.text((x + 16, ty), r, font=tf, fill=INK)
            ty += lh
        d.text((x + 14, y + ch - 44), f"ÉP. {ep}", font=font("Inter.ttf", 24, "Black"), fill=YELLOW)
        site = platform_of(m)
        if site:
            lb = d.textbbox((0, 0), PLATFORMS[site][0], font=font("Inter.ttf", 18, "Black"))
            platform_badge(d, x + cw - (lb[2] - lb[0]) - 34, y + ch - 48, site, 18)
    return img


def band(m, label, date_text, flip, size=(W, H // 3)):
    bw, bh = size
    vis = image(m.get("bannerImage")) or image(m["coverImage"]["extraLarge"])
    img = cover(vis, size, .25) if vis else Image.new("RGB", size, (40, 40, 48))
    shade = Image.new("RGB", size, BG)
    grad = Image.linear_gradient("L").rotate(90, expand=True).resize(size)
    if not flip:
        grad = grad.transpose(Image.FLIP_LEFT_RIGHT)
    mask = grad.point(lambda v: int(min(250, v * 1.7)))
    img.paste(shade, (0, 0), mask)
    d = ImageDraw.Draw(img)
    cx = int(bw * (.72 if not flip else .28))
    text_center(d, cx, 46, label, font("Inter.ttf", 42, "Black"))
    _, _, ph = pill(img, short_title(m, 30), cx, 108, int(bw * .5), size=56, lines=2)
    d = ImageDraw.Draw(img)
    text_center(d, cx, 108 + ph + 22, date_text, font("Inter.ttf", 34, "SemiBold"), shadow=True)
    return img


def poster_slide(m, top_line, bottom_line, brand):
    vis = image(m["coverImage"]["extraLarge"]) or image(m.get("bannerImage"))
    img = cover(vis, POST, .2) if vis else Image.new("RGB", POST, BG)
    img = veil(img, top=.5, strength=240)
    corner_logo(img, brand)
    _, _, ph = pill(img, short_title(m, 40), W // 2, H - 330, W - 100, size=70, lines=2)
    d = ImageDraw.Draw(img)
    if top_line:
        text_center(d, W // 2, H - 400, top_line, font("Inter.ttf", 40, "Black"), fill=YELLOW)
    text_center(d, W // 2, H - 330 + ph + 26, bottom_line, font("Inter.ttf", 40, "Black"))
    return img


def countdown_slide(left, m, brand):
    vis = image(m["coverImage"]["extraLarge"]) or image(m.get("bannerImage"))
    img = cover(vis, POST, .2) if vis else Image.new("RGB", POST, BG)
    img = veil(img, top=.42, strength=245)
    corner_logo(img, brand)
    _, _, ph = pill(img, short_title(m, 36), W // 2, H - 470, W - 140, size=66, lines=2)
    d = ImageDraw.Draw(img)
    text_center(d, W // 2, H - 470 + ph + 24, f"J-{left}", font("Inter.ttf", 190, "Black"))
    text_center(d, W // 2, H - 90, season_number(m).title(), font("Inter.ttf", 42, "Medium"), shadow=True)
    return img


# ------------------------------------------------------------------ carrousels complets (slides + légende)

def month_label(m):
    sd = m.get("startDate") or {}
    if sd.get("month") and sd.get("year"):
        return (f"{sd['day']} " if sd.get("day") else "") + f"{MONTHS[sd['month'] - 1]} {sd['year']}"
    if sd.get("year"):
        return f"PRÉVU EN {sd['year']}"
    return None


def build_week(brand):
    start, rows = week_schedule()
    by_day = {k: [] for k in range(7)}
    for when, ep, m in rows:
        by_day[when.weekday()].append((when, ep, m))
    for k in by_day:
        by_day[k] = sorted(by_day[k], key=lambda r: -r[2]["popularity"])[:9]
        by_day[k].sort(key=lambda r: r[0])
    tops = [image(m["coverImage"]["extraLarge"]) for _, _, m in sorted(rows, key=lambda r: -r[2]["popularity"])[:4]]
    end = start + timedelta(days=6)
    slides = [cover_slide(tops, brand, "LE PLANNING ANIME DE LA SEMAINE", "PLANNING")]
    for k in range(7):
        if by_day[k]:
            seed = image(by_day[k][0][2]["coverImage"]["extraLarge"])
            slides.append(day_slide(f"{DAYS[k]} {(start + timedelta(days=k)).day}", by_day[k], brand, seed))
    total = sum(len(v) for v in by_day.values())
    lines = [f"🗓️ LE PLANNING DE LA SEMAINE EST LÀ ! ({start.day}/{start.month:02d} → {end.day}/{end.month:02d})", "",
             f"{total} épisodes des séries les plus suivies, jour par jour, avec l'heure de sortie au Japon "
             "(heure de Paris) et la plateforme.", "",
             "📌 Enregistre le post pour l'avoir sous la main toute la semaine",
             "💬 Tu regardes lequel en premier ?", "",
             "Plateformes : catalogue variable selon les pays · Données : AniList · Visuels © leurs ayants droit", "",
             "#planninganime #animefr #crunchyroll #simulcast #anime"]
    return slides, "\n".join(lines)


def build_upcoming(brand):
    s, y, ms = upcoming_season()
    label = f"{SEASON_FR[s]} {y}"
    prep = "AU" if s == "SPRING" else "EN"
    slides = [cover_slide([image(m["coverImage"]["extraLarge"]) for m in ms[:4]], brand,
                          f"LES ANIMES ATTENDUS {prep} {label}", SEASON_FR[s])]
    for k in range(0, min(len(ms), 18), 3):
        img = Image.new("RGB", POST, BG)
        for j, m in enumerate(ms[k:k + 3]):
            img.paste(band(m, season_number(m), month_label(m) or label, flip=j % 2 == 1), (0, j * (H // 3)))
        corner_logo(img, brand)
        slides.append(img)
    names = ", ".join(short_title(m, 30) for m in ms[:6])
    lines = [f"🔥 ON VA PAS S'ENNUYER CET {label} !" if s != "SPRING" else f"🔥 ON VA PAS S'ENNUYER CE {label} !", "",
             f"Les animes les plus attendus de la saison prochaine : {names}… et d'autres à découvrir dans le carrousel.",
             "", "📌 Enregistre pour ne rien oublier", "💬 Lequel tu attends le plus ?", "",
             "Données : AniList · Visuels © leurs ayants droit", "",
             f"#anime{SEASON_FR[s].lower().replace('é', 'e')}{y} #animefr #animes #manga #otaku"]
    return slides, "\n".join(lines)


def build_movies(brand):
    ms = upcoming_movies()
    slides = [cover_slide([image(m["coverImage"]["extraLarge"]) for m in ms[:2]], brand,
                          "LES PROCHAINS FILMS D'ANIMATION ANNONCÉS !", "FILMS")]
    for m in ms[:9]:
        slides.append(poster_slide(m, None, ((month_label(m) or "DATE À VENIR") + " AU JAPON") if (m.get("startDate") or {}).get("month")
                                  else (month_label(m) or "DATE À VENIR"), brand))
    lines = ["🎬 LES PROCHAINS FILMS D'ANIMATION À NE PAS RATER !", "",
             "Les films d'animation japonais les plus attendus, avec leur date de sortie au Japon. "
             "Les sorties françaises sont annoncées plus tard : on vous tient au courant.", "",
             "📌 Enregistre le post", "💬 Tu vas voir lequel au cinéma ?", "",
             "Données : AniList · Visuels © leurs ayants droit", "",
             "#filmanime #animefr #anime #cinema #manga"]
    return slides, "\n".join(lines)


def build_countdown(brand):
    items = starting_soon()
    if len(items) < 4:
        return None, None
    slides = [cover_slide([image(m["coverImage"]["extraLarge"]) for _, m in items[:2]], brand,
                          "LE DÉCOMPTE DES ANIMES QUI ARRIVENT", "DÉCOMPTE")]
    slides += [countdown_slide(left, m, brand) for left, m in items[:9]]
    lines = ["⏳ LE DÉCOMPTE EST LANCÉ !", "",
             "Les animes qui démarrent dans les prochaines semaines, du plus proche au plus lointain.", "",
             "📌 Enregistre pour suivre le décompte", "💬 Lequel tu attends le plus ?", "",
             "Données : AniList · Visuels © leurs ayants droit", "",
             "#anime #animefr #nouvelanime #manga #otaku"]
    return slides, "\n".join(lines)


BUILDERS = {"week": build_week, "upcoming": build_upcoming, "movies": build_movies, "countdown": build_countdown}


# ------------------------------------------------------------------ post d'actu (même famille visuelle)

def news_card(headline, work, category, source, brand, visual, when_text):
    """Visuel en grand (portrait : plein cadre ; paysage : entier en haut), œuvre en pastille, titre en capitales."""
    img = Image.new("RGB", POST, BG)
    if visual is not None:
        ratio = visual.width / visual.height
        bg = cover(visual, POST).filter(ImageFilter.GaussianBlur(45))
        img = Image.blend(bg, img, .55)
        if ratio < .95:
            img = cover(visual, POST, .18)
        else:  # paysage : image entière (ou très légèrement recadrée si c'est une bannière très large)
            h = int(W / ratio)
            vis = visual.resize((W, h), Image.LANCZOS) if ratio <= 1.9 else cover(visual, (W, 600), .3)
            top = 130 + max(0, (720 - vis.height) // 2)
            img.paste(vis, (0, top))
    img = veil(img, top=.42, strength=245)
    corner_logo(img, brand)
    d = ImageDraw.Draw(img)
    tf = font("Inter.ttf", 26, "Black")
    tb = d.textbbox((0, 0), when_text, font=tf)
    d.rounded_rectangle([W - 60 - (tb[2] - tb[0]) - 28, 46, W - 60, 46 + 52], radius=12, fill=(13, 13, 18))
    d.text((W - 60 - (tb[2] - tb[0]) - 14 - tb[0], 46 + 13 - tb[1]), when_text, font=tf, fill=INK)
    # titre en capitales, 3 lignes max, calé en bas
    words, size = headline.upper().split(), 74
    while True:
        f = font("Inter.ttf", size, "Black")
        rows, cur = [], ""
        for w_ in words:
            test = (cur + " " + w_).strip()
            if d.textbbox((0, 0), test, font=f)[2] <= W - 120 or not cur:
                cur = test
            else:
                rows.append(cur)
                cur = w_
        rows.append(cur)
        if len(rows) <= 3 or size <= 46:
            break
        size -= 4
    rows = rows[:3]
    lh = int(size * 1.12)
    y = H - 120 - lh * len(rows)
    if work:
        _, _, ph = pill(img, work, W // 2, y - 150, W - 200, size=54, lines=1)
        d = ImageDraw.Draw(img)
    for r in rows:
        text_center(d, W // 2, y, r, f)
        y += lh
    sf = font("Inter.ttf", 24, "SemiBold")
    credit = f"Source : {source}" + ("  ·  Visuel © ayants droit" if visual is not None else "")
    text_center(d, W // 2, H - 66, credit, sf, fill=(190, 190, 200), shadow=False)
    return img
