"""Visuels SOKUHŌ : post 4:5, story 9:16, couverture de récap et reel vidéo."""
import io
import math
import random
import re
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .common import FONTS, USER_AGENT

POST = (1080, 1350)
STORY = (1080, 1920)
BG = (13, 13, 18)
INK = (245, 243, 238)
MUTED = (175, 175, 186)
RED = (230, 57, 70)
YELLOW = (255, 209, 10)
CAT_COLORS = {
    "ANIME": (230, 57, 70),
    "MANGA": (255, 209, 10),
    "MANHUA": (0, 196, 170),
    "WEBTOON": (124, 92, 255),
    "ACTU": (240, 240, 240),
}
M = 56  # marge latérale


def font(name, size, weight=None):
    f = ImageFont.truetype(str(FONTS / name), size)
    if weight:
        f.set_variation_by_name(weight)
    return f


def on_color(c):
    return BG if sum(c) > 420 else INK


# ---------- Récupération du visuel officiel de l'article ----------

def find_og_image(article_url, timeout=20):
    r = requests.get(article_url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    r.raise_for_status()
    for prop in ("og:image", "twitter:image"):
        m = re.search(r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]+content=["\']([^"\']+)' % prop, r.text, re.I) \
            or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']%s["\']' % prop, r.text, re.I)
        if m:
            return m.group(1)
    return None


def download_image(url, timeout=30):
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content))
    img.load()
    if min(img.size) < 300:  # trop petit : logo ou icône, on n'en veut pas
        return None
    return img.convert("RGB")


# ---------- Fond maison (seulement si require_visual est désactivé) ----------

def generated_backdrop(seed, color, size):
    rnd = random.Random(seed)
    w, h = size
    img = Image.new("RGB", size, BG)
    d = ImageDraw.Draw(img)
    cx, cy = rnd.randint(int(w * .55), int(w * .85)), rnd.randint(int(h * .2), int(h * .4))
    for _ in range(160):
        a = rnd.uniform(0, 2 * math.pi)
        r0, r1 = rnd.uniform(80, 220), rnd.uniform(900, 2000)
        shade = tuple(int(c * rnd.uniform(.25, .7) + BG[k] * .3) for k, c in enumerate(color))
        d.line([(cx + r0 * math.cos(a), cy + r0 * math.sin(a)), (cx + r1 * math.cos(a), cy + r1 * math.sin(a))],
               fill=shade, width=rnd.choice([1, 2, 2, 3, 5]))
    glow = Image.new("RGB", size, BG)
    ImageDraw.Draw(glow).ellipse([cx - 180, cy - 180, cx + 180, cy + 180], fill=color)
    return Image.blend(img, glow.filter(ImageFilter.GaussianBlur(130)), .35)


def cover(img, size, focus_y=.3):
    w, h = size
    s = max(w / img.width, h / img.height)
    img = img.resize((math.ceil(img.width * s), math.ceil(img.height * s)), Image.LANCZOS)
    left = (img.width - w) // 2
    top = int((img.height - h) * focus_y)  # les visages sont souvent dans le haut des affiches
    return img.crop((left, top, left + w, top + h))


def story_backdrop(visual, size=STORY):
    """Fond 9:16 : le visuel flouté et assombri, l'image nette posée au centre."""
    bg = cover(visual, size).filter(ImageFilter.GaussianBlur(40))
    return Image.blend(bg, Image.new("RGB", size, BG), .45)


def vertical_gradient(size, start, end, max_alpha):
    w, h = size
    g = Image.new("L", (1, h), 0)
    for y in range(h):
        t = min(1, max(0, (y - start) / max(1, end - start)))
        g.putpixel((0, y), int(max_alpha * (t ** 1.15)))
    return g.resize((w, h))


def darken(img, mask):
    img.paste(Image.new("RGB", img.size, BG), (0, 0), mask)
    return img


# ---------- Titre ----------

def headline_words(headline, work):
    """Mots du titre en majuscules, en marquant ceux qui forment le nom de l'œuvre."""
    up = headline.upper().replace("’", "'")
    work_up = work.upper().strip().replace("’", "'")
    span = None
    if work_up and work_up in up:
        i = up.index(work_up)
        span = (i, i + len(work_up))
    words = []
    for m in re.finditer(r"\S+", up):
        hl = span is not None and m.start() >= span[0] and m.end() <= span[1] + 1
        if words and m.group() in (":", "!", "?", "·", ";") and not hl:
            words[-1] = (words[-1][0] + "\u00a0" + m.group(), words[-1][1])  # pas de « : » orphelin en début de ligne
        else:
            words.append((m.group(), hl))
    return words


def wrap_words(draw, words, fnt, max_w):
    lines, cur = [], []
    for wd in words:
        test = cur + [wd]
        if draw.textlength(" ".join(w for w, _ in test), font=fnt) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = [wd]
    if cur:
        lines.append(cur)
    return lines


def fit_headline(draw, words, max_w, max_lines, sizes):
    for size in sizes:
        f = font("Anton-Regular.ttf", size)
        lines = wrap_words(draw, words, f, max_w)
        if len(lines) <= max_lines:
            return f, size, lines
    return f, size, lines


def draw_headline(img, lines, f, size, x0, y0, band_color):
    """Titre massif ; le nom de l'œuvre est posé sur un bandeau de couleur."""
    line_h = int(size * 1.18)
    space = ImageDraw.Draw(img).textlength(" ", font=f)
    cap = ImageDraw.Draw(img).textbbox((0, 0), "H", font=f)
    cap_top, cap_bot = cap[1], cap[3]
    # Ombre portée douce pour détacher le texte de l'image
    shadow = Image.new("L", img.size, 0)
    sd = ImageDraw.Draw(shadow)
    y = y0
    for line in lines:
        x = x0
        for wd, hl in line:
            if not hl:
                sd.text((x, y + 4), wd, font=f, fill=200)
            x += sd.textlength(wd, font=f) + space
        y += line_h
    img.paste(Image.new("RGB", img.size, (0, 0, 0)), (0, 0), shadow.filter(ImageFilter.GaussianBlur(10)))

    d = ImageDraw.Draw(img)
    y = y0
    for line in lines:
        x = x0
        runs, run = [], None
        for wd, hl in line:
            w = d.textlength(wd, font=f)
            if hl:
                run = [run[0], x + w] if run else [x, x + w]
            elif run:
                runs.append(run)
                run = None
            x += w + space
        if run:
            runs.append(run)
        for a, b in runs:
            d.rectangle([a - 14, y + cap_top - 12, b + 14, y + cap_bot + 12], fill=band_color)
        x = x0
        for wd, hl in line:
            d.text((x, y), wd, font=f, fill=on_color(band_color) if hl else INK)
            x += d.textlength(wd, font=f) + space
        y += line_h
    return y


# ---------- Éléments de marque ----------

def draw_logo(img, brand, x, y, h=70):
    d = ImageDraw.Draw(img)
    kfont = font("NotoSansJP-Sokuho.ttf", int(h * .66), "Black")
    nfont = font("Anton-Regular.ttf", int(h * .72))
    kb = d.textbbox((0, 0), brand["kanji"], font=kfont)
    box = [x, y, x + (kb[2] - kb[0]) + 28, y + h]
    d.rounded_rectangle(box, radius=10, fill=RED)
    d.text((x + 14 - kb[0], y + (h - (kb[3] - kb[1])) // 2 - kb[1]), brand["kanji"], font=kfont, fill=INK)
    nb = d.textbbox((0, 0), brand["name"], font=nfont)
    pill = [box[2] + 8, y, box[2] + 8 + (nb[2] - nb[0]) + 32, y + h]
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(over).rounded_rectangle(pill, radius=10, fill=(13, 13, 18, 210))
    img.paste(Image.alpha_composite(img.convert("RGBA"), over).convert("RGB"))
    d = ImageDraw.Draw(img)
    d.text((pill[0] + 16 - nb[0], y + (h - (nb[3] - nb[1])) // 2 - nb[1]), brand["name"], font=nfont, fill=INK)
    return img


def draw_tag(d, text, x, y, color, size=34):
    f = font("Inter.ttf", size, "Black")
    b = d.textbbox((0, 0), text, font=f)
    h = size + 28
    d.rounded_rectangle([x, y, x + (b[2] - b[0]) + 40, y + h], radius=8, fill=color)
    d.text((x + 20 - b[0], y + (h - (b[3] - b[1])) // 2 - b[1]), text, font=f, fill=on_color(color))
    return x + (b[2] - b[0]) + 40, h


def _veil_mask(size, h):
    w, H = size
    m = Image.new("L", (1, H), 0)
    for y in range(min(h, H)):
        m.putpixel((0, y), int(150 * (1 - y / h)))
    return m.resize((w, H))


# ---------- Cartes ----------

def render_card(item, category, headline, brand, visual=None, tz="Europe/Paris", story=False):
    size = STORY if story else POST
    W, H = size
    color = CAT_COLORS.get(category, INK)
    if visual is not None:
        if story:
            img = story_backdrop(visual)
        else:
            img = cover(visual, size)
    else:
        img = generated_backdrop(item["id"], color, size)

    safe_bottom = 300 if story else 0       # zone réservée à l'interface des stories
    footer_h = 84
    footer_y = H - safe_bottom - footer_h

    d = ImageDraw.Draw(img)
    words = headline_words(headline, item.get("work", ""))
    f, fsize, lines = fit_headline(d, words, W - 2 * M - 24, 4, range(104 if story else 118, 58, -4))
    block_h = len(lines) * int(fsize * 1.18)
    head_y = footer_y - 36 - block_h
    tag_y = head_y - 24 - 62
    if story and visual is not None:
        # Image nette encadrée entre le logo et le texte
        inner = cover(visual, (W - 2 * M, max(420, tag_y - 50 - 310)), focus_y=.25)
        img.paste(inner, (M, 310))
        ImageDraw.Draw(img).rectangle([M, 310, W - M, 310 + inner.height], outline=color, width=6)

    grad_start = tag_y - (40 if story else 380)
    img = darken(img, vertical_gradient(size, grad_start, footer_y - 40, 242))
    img = darken(img, _veil_mask(size, 260 if not story else 420))
    img = draw_logo(img, brand, M, 48 if not story else 200)
    d = ImageDraw.Draw(img)

    when = datetime.fromtimestamp(item["published"], ZoneInfo(tz))
    stamp = when.strftime("%d/%m · %Hh%M")
    sfont = font("Inter.ttf", 30, "SemiBold")
    sb = d.textbbox((0, 0), stamp, font=sfont)
    sy = (48 if not story else 200) + (70 - (sb[3] - sb[1])) // 2 - sb[1]
    d.text((W - M - (sb[2] - sb[0]), sy), stamp, font=sfont, fill=INK)

    tx, _ = draw_tag(d, category, M, tag_y, color)
    if story:
        draw_tag(d, "NOUVEAU POST", tx + 14, tag_y, INK)

    draw_headline(img, lines, f, fsize, M, head_y, YELLOW)

    d = ImageDraw.Draw(img)
    d.line([(M, footer_y + 8), (W - M, footer_y + 8)], fill=(255, 255, 255), width=1)
    ffont = font("Inter.ttf", 26, "Medium")
    left = f"Source : {item['source']}" + ("  ·  Visuel © ayants droit" if visual is not None else "")
    d.text((M, footer_y + 32), left, font=ffont, fill=MUTED)
    hf = font("Inter.ttf", 28, "Bold")
    hb = d.textbbox((0, 0), brand["handle"], font=hf)
    d.text((W - M - (hb[2] - hb[0]), footer_y + 30), brand["handle"], font=hf, fill=INK)
    return img


def render_post(item, category, headline, brand, visual=None, tz="Europe/Paris"):
    return render_card(item, category, headline, brand, visual, tz, story=False)


def render_story(item, category, headline, brand, visual=None, tz="Europe/Paris"):
    return render_card(item, category, headline, brand, visual, tz, story=True)


# ---------- Récap de la semaine ----------

def render_recap_cover(visuals, brand, period_label, count):
    """Couverture de carrousel : mosaïque en biais des visuels de la semaine + gros titre."""
    W, H = POST
    img = Image.new("RGB", POST, BG)
    vis = visuals[:4] or [generated_backdrop("recap", RED, POST)]
    n = len(vis)
    strip_w = W / n
    skew = 120
    for i, v in enumerate(vis):
        tile = cover(v, (int(strip_w + 2 * skew), H), focus_y=.25)
        mask = Image.new("L", POST, 0)
        x0 = i * strip_w
        poly = [(x0 + skew * .5, 0), (x0 + strip_w + skew * .5, 0), (x0 + strip_w - skew * .5, H), (x0 - skew * .5, H)]
        if i == 0:
            poly[0], poly[3] = (0, 0), (0, H)
        if i == n - 1:
            poly[1], poly[2] = (W, 0), (W, H)
        ImageDraw.Draw(mask).polygon(poly, fill=255)
        img.paste(tile, (int(x0 - skew), 0), mask.crop((int(x0 - skew), 0, int(x0 - skew) + tile.width, H)))
        if 0 < i:
            ImageDraw.Draw(img).line([poly[0], poly[3]], fill=BG, width=10)
    img = darken(img, vertical_gradient(POST, 420, 1050, 245))
    img = darken(img, _veil_mask(POST, 260))
    img = draw_logo(img, brand, M, 48)
    d = ImageDraw.Draw(img)
    words = [("LES", False), ("NEWS", True), ("ANIME", False), ("&", False), ("MANGA", False),
             ("DE", False), ("LA", False), ("SEMAINE", True)]
    f, fsize, lines = fit_headline(d, words, W - 2 * M, 3, range(124, 70, -4))
    head_y = 1230 - len(lines) * int(fsize * 1.18)
    draw_tag(d, f"RÉCAP · {period_label}", M, head_y - 90, RED)
    draw_headline(img, lines, f, fsize, M, head_y, YELLOW)
    d = ImageDraw.Draw(img)
    sf = font("Inter.ttf", 32, "Bold")
    d.text((M, 1262), f"{count} actus à retenir  →  swipe", font=sf, fill=INK)
    hf = font("Inter.ttf", 28, "Bold")
    hb = d.textbbox((0, 0), brand["handle"], font=hf)
    d.text((W - M - (hb[2] - hb[0]), 1266), brand["handle"], font=hf, fill=MUTED)
    return img


def render_end_card(brand, size=POST):
    W, H = size
    img = generated_backdrop("outro", RED, size)
    img = darken(img, vertical_gradient(size, 0, H, 120))
    d = ImageDraw.Draw(img)
    k = font("NotoSansJP-Sokuho.ttf", 300, "Black")
    kb = d.textbbox((0, 0), brand["kanji"], font=k)
    d.text(((W - (kb[2] - kb[0])) // 2 - kb[0], H * .3 - kb[1]), brand["kanji"], font=k, fill=INK)
    f = font("Anton-Regular.ttf", 96)
    for i, line in enumerate(["ABONNE-TOI", "POUR NE RIEN RATER"]):
        b = d.textbbox((0, 0), line, font=f)
        d.text(((W - (b[2] - b[0])) // 2 - b[0], H * .58 + i * 118), line, font=f, fill=YELLOW if i == 0 else INK)
    hf = font("Inter.ttf", 44, "Bold")
    hb = d.textbbox((0, 0), brand["handle"], font=hf)
    d.text(((W - (hb[2] - hb[0])) // 2, H * .58 + 280), brand["handle"], font=hf, fill=INK)
    return img


# ---------- Reel vidéo (sans musique : piste audio muette exigée par le format) ----------

def make_reel(slides, out_path, seconds_per_slide=2.6, fps=30):
    """Diaporama vertical 1080x1920 : chaque carte posée sur son fond flouté, léger zoom progressif."""
    W, H = STORY
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames_per = int(seconds_per_slide * fps)
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
           "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
           "-shortest", "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
           "-preset", "veryfast", "-crf", "21", "-g", str(fps), "-keyint_min", str(fps), "-sc_threshold", "0",
           "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for card in slides:
        bg = Image.blend(cover(card, STORY).filter(ImageFilter.GaussianBlur(45)), Image.new("RGB", STORY, BG), .5)
        for i in range(frames_per):
            z = 1 + .05 * (i / frames_per)
            cw, ch = int(W * z), int(W * z * card.height / card.width)
            c = card.resize((cw, ch), Image.BILINEAR)
            frame = bg.copy()
            frame.paste(c, ((W - cw) // 2, (H - ch) // 2))
            proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg a échoué")
    return out_path


def save_jpeg(img, path, quality=88):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(path, "JPEG", quality=quality, optimize=True, progressive=False)
    return path
