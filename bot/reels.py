"""Reels d'actu en motion design : plusieurs modèles animés, choisis en alternance.

Tout est dessiné image par image (30 i/s) puis encodé avec ffmpeg, au format exigé par Instagram
(MP4 H.264 1080x1920, piste audio AAC). Aucun extrait vidéo protégé n'est utilisé : seulement le
visuel officiel de l'article, du texte et des effets.
"""
import math
import random
import re
import subprocess

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .render import (BG, CAT_COLORS, INK, M, RED, STORY, YELLOW, contain, darken, draw_logo, font,
                     generated_backdrop, headline_words, on_color, story_backdrop, vertical_gradient)

W, H = STORY
FPS = 30
SAFE_BOTTOM = 1560  # sous cette ligne, l'interface d'Instagram (boutons, légende) recouvre la vidéo


# ---------------------------------------------------------------- outils d'animation

def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out_cubic(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_out_back(t, s=1.9):
    t = clamp(t) - 1
    return t * t * ((s + 1) * t + s) + 1


def ease_in_out(t):
    t = clamp(t)
    return 3 * t * t - 2 * t * t * t


def prog(t, start, dur):
    return clamp((t - start) / dur)


def paste_rgba(frame, sprite, x, y, alpha=1.0, scale=1.0):
    """Colle un calque transparent, éventuellement agrandi et estompé, centré sur (x, y)."""
    if alpha <= 0.01 or scale <= 0.01:
        return
    sp = sprite
    if abs(scale - 1) > 0.01:
        sp = sprite.resize((max(1, int(sprite.width * scale)), max(1, int(sprite.height * scale))), Image.BILINEAR)
    if alpha < 0.99:
        a = sp.getchannel("A").point(lambda v: int(v * alpha))
        sp = sp.copy()
        sp.putalpha(a)
    frame.alpha_composite(sp, (int(x - sp.width / 2), int(y - sp.height / 2)))


def glitch(frame, strength, rnd):
    """Décalage des couches rouge/bleu + bandes déplacées : effet « glitch » de transition."""
    if strength <= 0:
        return frame
    rgb = frame.convert("RGB")
    r, g, b = rgb.split()
    off = int(18 * strength)
    rgb = Image.merge("RGB", (ImageChops.offset(r, off, 0), g, ImageChops.offset(b, -off, 0)))
    for _ in range(int(6 * strength)):
        y = rnd.randint(0, H - 60)
        h = rnd.randint(10, 60)
        band = rgb.crop((0, y, W, y + h))
        rgb.paste(band, (rnd.randint(-80, 80), y))
    return rgb.convert("RGBA")


def flash(frame, a, color=(255, 255, 255)):
    if a <= 0:
        return frame
    return Image.blend(frame, Image.new("RGBA", frame.size, color + (255,)), clamp(a))


def shake(rnd, amount):
    return (rnd.uniform(-amount, amount), rnd.uniform(-amount, amount))


# ---------------------------------------------------------------- éléments graphiques

def text_sprite(text, fnt, fill=INK, band=None, pad=(14, 10), shadow=True):
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    bb = probe.textbbox((0, 0), text, font=fnt)
    ref = probe.textbbox((0, 0), "ÉÀHgjq", font=fnt)  # hauteur commune : tous les mots restent alignés
    bb = (bb[0], ref[1], bb[2], ref[3])
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    sp = Image.new("RGBA", (w + 2 * pad[0] + 8, h + 2 * pad[1] + 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(sp)
    if band:
        d.rectangle([0, 0, sp.width - 8, sp.height - 8], fill=band + (255,))
    elif shadow:
        d.text((pad[0] - bb[0] + 4, pad[1] - bb[1] + 6), text, font=fnt, fill=(0, 0, 0, 170))
    d.text((pad[0] - bb[0], pad[1] - bb[1]), text, font=fnt, fill=fill + (255,) if len(fill) == 3 else fill)
    return sp


def pill_sprite(text, color, size=40):
    f = font("Inter.ttf", size, "Black")
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    bb = probe.textbbox((0, 0), text, font=f)
    w, h = bb[2] - bb[0] + 48, size + 34
    sp = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(sp)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=12, fill=color + (255,))
    d.text((24 - bb[0], (h - (bb[3] - bb[1])) // 2 - bb[1]), text, font=f, fill=on_color(color) + (255,))
    return sp


def headline_layout(headline, work, max_lines=4, max_w=W - 2 * M - 20, sizes=range(104, 56, -4)):
    """Découpe le titre en lignes et renvoie, pour chaque mot, son calque et sa position."""
    from .render import fit_headline
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    words = headline_words(headline, work)
    f, fsize, lines = fit_headline(probe, words, max_w, max_lines, sizes)
    line_h = int(fsize * 1.2)
    space = probe.textlength(" ", font=f)
    placed = []
    for li, line in enumerate(lines):
        x = M
        for wd, hl in line:
            core = wd.replace(" ", " ")
            sp = text_sprite(core, f, fill=on_color(YELLOW) if hl else INK, band=YELLOW if hl else None, pad=(12, 8))
            w = probe.textlength(core, font=f)
            placed.append({"sprite": sp, "cx": x + w / 2, "line": li, "hl": hl})
            x += w + space
    return placed, line_h, len(lines), f


def fact_sprites(facts, color):
    f = font("Inter.ttf", 46, "Bold")
    out = []
    for fact in facts:
        probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
        words, lines, cur = fact.split(), [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if probe.textlength(t, font=f) <= W - 2 * M - 90 or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        h = 40 + 62 * len(lines)
        sp = Image.new("RGBA", (W - 2 * M, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(sp)
        d.rounded_rectangle([0, 0, sp.width - 1, h - 1], radius=18, fill=(13, 13, 18, 225))
        d.rounded_rectangle([0, 0, 14, h - 1], radius=6, fill=color + (255,))
        for i, ln in enumerate(lines):
            d.text((44, 22 + i * 62), ln, font=f, fill=INK + (255,))
        out.append(sp)
    return out


def progress_bar(frame, t, total, color):
    d = ImageDraw.Draw(frame)
    d.rectangle([0, 0, W, 10], fill=(255, 255, 255, 60))
    d.rectangle([0, 0, int(W * t / total), 10], fill=color + (255,))


def end_card(brand, t_local, base_dark):
    """Carte de fin animée : kanji qui arrive en rebond, appel à l'abonnement."""
    fr = base_dark.copy()
    k = text_sprite(brand["kanji"], font("NotoSansJP-Sokuho.ttf", 300, "Black"), shadow=False)
    paste_rgba(fr, k, W / 2, 620, scale=0.4 + 0.6 * ease_out_back(prog(t_local, 0, 0.5)))
    a1 = prog(t_local, 0.35, 0.3)
    paste_rgba(fr, text_sprite("ABONNE-TOI", font("Anton-Regular.ttf", 120), fill=YELLOW), W / 2,
               980 - 40 * (1 - ease_out_cubic(a1)), alpha=a1)
    a2 = prog(t_local, 0.55, 0.3)
    paste_rgba(fr, text_sprite("POUR NE RIEN RATER", font("Anton-Regular.ttf", 92)), W / 2,
               1120 - 40 * (1 - ease_out_cubic(a2)), alpha=a2)
    a3 = prog(t_local, 0.8, 0.3)
    paste_rgba(fr, text_sprite(brand["handle"], font("Inter.ttf", 54, "Bold")), W / 2, 1260, alpha=a3)
    return fr


# ---------------------------------------------------------------- le montage

class Scene:
    def __init__(self, item, category, headline, facts, brand, visual, seconds, seed):
        self.rnd = random.Random(seed)
        self.color = CAT_COLORS.get(category, INK)
        self.category = category
        self.brand = brand
        self.seconds = seconds
        self.facts = [re.sub(r"[^\w\s:;,.!?'’/()&+%«»\-]", "", x).strip() for x in (facts or []) if x]
        self.facts = [x for x in self.facts if x][:3]
        bg = story_backdrop(visual) if visual is not None else generated_backdrop(item["id"], self.color, STORY)
        self.bg = darken(bg, vertical_gradient(STORY, 700, 1500, 200)).convert("RGBA")
        self.bg_dark = Image.blend(self.bg, Image.new("RGBA", STORY, BG + (255,)), 0.6)
        self.visual = contain(visual, (W - 2 * M, 760)).convert("RGBA") if visual is not None else None
        if self.visual is not None:
            framed = Image.new("RGBA", (self.visual.width + 12, self.visual.height + 12), self.color + (255,))
            framed.paste(self.visual, (6, 6))
            self.visual = framed
        self.words, self.line_h, self.n_lines, _ = headline_layout(headline, item.get("work", ""))
        self.fact_sp = fact_sprites(self.facts, self.color)
        self.tag = pill_sprite(category, self.color)
        self.flash_tag = pill_sprite("FLASH INFO", RED, 46)

    def header(self, fr):
        rgb = fr.convert("RGB")
        rgb = draw_logo(rgb, self.brand, M, 120)
        return rgb.convert("RGBA")

    def draw_visual(self, fr, cx, cy, scale=1.0, alpha=1.0):
        if self.visual is not None:
            paste_rgba(fr, self.visual, cx, cy, alpha=alpha, scale=scale)

    def draw_words(self, fr, t, start, gap, top, style="pop"):
        for i, w in enumerate(self.words):
            p = prog(t, start + i * gap, 0.28)
            if p <= 0:
                continue
            y = top + w["line"] * self.line_h + self.line_h / 2
            if style == "pop":
                paste_rgba(fr, w["sprite"], w["cx"], y, alpha=min(1, p * 2), scale=1.6 - 0.6 * ease_out_back(p))
            else:  # glisse vers le haut
                paste_rgba(fr, w["sprite"], w["cx"], y + 50 * (1 - ease_out_cubic(p)), alpha=p)
        return top + self.n_lines * self.line_h

    def draw_facts(self, fr, t, start, top, gap=0.85):
        y = top
        for i, sp in enumerate(self.fact_sp):
            p = prog(t, start + i * gap, 0.45)
            if p > 0:
                x = W / 2 + (W * 0.9) * (1 - ease_out_back(p, 1.4))
                paste_rgba(fr, sp, x, y + sp.height / 2, alpha=min(1, p * 1.5))
            y += sp.height + 22
        return y

    # --- Modèle 1 : IMPACT — flash, zoom choc, mots qui claquent, infos qui rebondissent
    def impact(self, t):
        fr = self.bg.copy()
        z = 1.35 - 0.35 * ease_out_cubic(prog(t, 0, 0.5)) + 0.04 * t / self.seconds
        sx, sy = shake(self.rnd, 14 * (1 - prog(t, 0, 0.6)))
        self.draw_visual(fr, W / 2 + sx, 600 + sy, scale=z)
        paste_rgba(fr, self.flash_tag, M + self.flash_tag.width / 2, 250,
                   scale=ease_out_back(prog(t, 0.15, 0.4)), alpha=prog(t, 0.15, 0.1))
        fr = self.header(fr)
        t_facts = 5.2 if self.facts else 99
        if t < t_facts:
            paste_rgba(fr, self.tag, M + self.tag.width / 2, 1060, alpha=prog(t, 0.6, 0.2))
            self.draw_words(fr, t, 0.8, 0.16, 1110, "pop")
        else:
            paste_rgba(fr, pill_sprite("À RETENIR", YELLOW), M + 150, 1060, alpha=prog(t, t_facts, 0.2))
            self.draw_facts(fr, t, t_facts + 0.15, 1120)
        fr = flash(fr, 1 - prog(t, 0, 0.25))
        if 0 < t - t_facts < 0.2:
            fr = glitch(fr, 1 - (t - t_facts) / 0.2, self.rnd)
        return fr

    # --- Modèle 2 : KINETIC — gros mots plein écran en rythme, puis révélation du visuel
    def kinetic(self, t):
        fr = self.bg_dark.copy()
        big_words = [w for w in self.words][:6]
        beat = 0.32
        t_reveal = 0.3 + beat * len(big_words)
        if t < t_reveal:
            i = int((t - 0.3) / beat) if t >= 0.3 else -1
            if 0 <= i < len(big_words):
                p = prog(t, 0.3 + i * beat, beat)
                sp = big_words[i]["sprite"]
                sc = (2.4 if sp.width < 400 else 1.6) * (1.25 - 0.25 * ease_out_cubic(p))
                sx, sy = shake(self.rnd, 10 * (1 - p))
                paste_rgba(fr, sp, W / 2 + sx, H / 2 - 120 + sy, scale=sc)
                fr = flash(fr, 0.35 * (1 - prog(t, 0.3 + i * beat, 0.08)), self.color)
            fr = self.header(fr)
            return fr
        lt = t - t_reveal
        fr = self.bg.copy()
        self.draw_visual(fr, W / 2, 600, scale=0.6 + 0.4 * ease_out_back(prog(lt, 0, 0.45)) + 0.03 * lt / 10)
        fr = self.header(fr)
        t_facts = 3.4 if self.facts else 99
        if lt < t_facts:
            paste_rgba(fr, self.tag, M + self.tag.width / 2, 1060, alpha=prog(lt, 0.2, 0.2))
            self.draw_words(fr, lt, 0.3, 0.07, 1110, "slide")
        else:
            paste_rgba(fr, pill_sprite("À RETENIR", YELLOW), M + 150, 1060, alpha=prog(lt, t_facts, 0.2))
            self.draw_facts(fr, lt, t_facts + 0.1, 1120)
        if lt < 0.18:
            fr = glitch(fr, 1 - lt / 0.18, self.rnd)
        return fr

    # --- Modèle 3 : BREAKING — bandeau défilant, volet sur le visuel, titre machine à écrire
    def breaking(self, t):
        fr = self.bg.copy()
        if self.visual is not None:
            p = ease_in_out(prog(t, 0.2, 0.7))
            vis = self.visual.resize((int(self.visual.width * (1 + 0.05 * t / self.seconds)),
                                      int(self.visual.height * (1 + 0.05 * t / self.seconds))), Image.BILINEAR)
            mask = Image.new("L", vis.size, 0)
            half = vis.width * p / 2
            ImageDraw.Draw(mask).rectangle([vis.width / 2 - half, 0, vis.width / 2 + half, vis.height], fill=255)
            vis.putalpha(ImageChops.multiply(vis.getchannel("A"), mask))
            fr.alpha_composite(vis, (int(W / 2 - vis.width / 2), int(620 - vis.height / 2)))
        # bandeau « BREAKING » défilant
        d = ImageDraw.Draw(fr)
        d.rectangle([0, 230, W, 310], fill=RED + (255,))
        tf = font("Anton-Regular.ttf", 56)
        msg = ("   FLASH INFO   /   " + self.category + "   /   NOUVELLE ANNONCE   /") * 4
        d.text((-((t * 260) % 900), 238), msg, font=tf, fill=INK)
        fr = self.header(fr)
        t_facts = 5.6 if self.facts else 99
        if t < t_facts:
            paste_rgba(fr, self.tag, M + self.tag.width / 2, 1060, alpha=prog(t, 0.9, 0.2))
            # machine à écrire : les mots apparaissent sans animation, au rythme de la frappe
            for i, w in enumerate(self.words):
                if t >= 1.1 + i * 0.12:
                    y = 1110 + w["line"] * self.line_h + self.line_h / 2
                    paste_rgba(fr, w["sprite"], w["cx"], y)
            if int(t * 3) % 2 == 0 and t < 1.1 + len(self.words) * 0.12 + 0.6:
                ImageDraw.Draw(fr).rectangle([M, 1110 + self.n_lines * self.line_h + 10,
                                              M + 40, 1110 + self.n_lines * self.line_h + 22], fill=YELLOW + (255,))
        else:
            paste_rgba(fr, pill_sprite("À RETENIR", YELLOW), M + 150, 1060, alpha=prog(t, t_facts, 0.2))
            self.draw_facts(fr, t, t_facts + 0.1, 1120, gap=0.7)
        if t - t_facts > -0.15 and t - t_facts < 0.15:
            fr = glitch(fr, 1 - abs(t - t_facts) / 0.15, self.rnd)
        return fr


TEMPLATES = ("impact", "kinetic", "breaking")


def make_reel(item, category, headline, facts, brand, visual, out_path, music=None, seconds=12, template=None):
    seed = item["id"]
    scene = Scene(item, category, headline, facts, brand, visual, seconds, seed)
    if not template:
        template = random.Random(str(seed)).choice(TEMPLATES)
    draw = getattr(scene, template)
    total = int(seconds * FPS)
    t_end = seconds - 2.2

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music),
                "-af", f"afade=t=in:st=0:d=0.4,afade=t=out:st={seconds - 1.2}:d=1.2"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    cmd += ["-map", "0:v", "-map", "1:a", "-t", str(seconds), "-c:v", "libx264", "-profile:v", "high",
            "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "20", "-g", str(FPS), "-keyint_min", str(FPS),
            "-sc_threshold", "0", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    prev = None
    for i in range(total):
        t = i / FPS
        if t >= t_end:
            fr = end_card(brand, t - t_end, scene.bg_dark)
            if prev is not None and t - t_end < 0.2:
                fr = glitch(Image.blend(prev, fr, (t - t_end) / 0.2), 1 - (t - t_end) / 0.2, scene.rnd)
        else:
            fr = draw(t)
            prev = fr
        progress_bar(fr, t, seconds, scene.color)
        proc.stdin.write(fr.convert("RGB").tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg a échoué")
    return out_path, template
