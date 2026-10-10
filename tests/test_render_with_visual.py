"""Rend post, story, couverture de récap et reel avec de faux visuels dessinés ici (aucune image protégée)."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bot import editorial, render  # noqa: E402
from bot.common import load_config  # noqa: E402

OUT = ROOT / "preview"
cfg = load_config()


def fake_visual(seed):
    hues = [((40, 90, 160), (250, 220, 170)), ((120, 30, 60), (255, 200, 90)),
            ((20, 110, 90), (240, 240, 255)), ((70, 40, 140), (255, 150, 200))][seed % 4]
    img = Image.new("RGB", (884, 1200))
    d = ImageDraw.Draw(img)
    for y in range(1200):
        k = y / 1200
        d.line([(0, y), (884, y)], fill=tuple(int(hues[0][i] * (1 - k) + 20 * k) for i in range(3)))
    d.ellipse([200 + seed * 40, 180, 640 + seed * 40, 620], fill=hues[1])
    d.polygon([(0, 1200), (300, 700), (600, 1200)], fill=tuple(c // 2 for c in hues[0]))
    return img


if __name__ == "__main__":
    items = [
        ("L'anime Dr. Stone Terraforming, annoncé en Vidéo", "Dr. Stone Terraforming", ["ANIME"]),
        ("Le webtoon L’Impératrice Remariée adapté en anime + Teaser Vidéo", "L'Impératrice Remariée", ["ANIME"]),
        ("Le manga Kimi wa Yotsuba no Clover se termine au prochain chapitre", "Kimi wa Yotsuba no Clover", ["MANGA"]),
        ("Le manhua Tales of Demons and Gods arrive en France", "Tales of Demons and Gods", ["MANHUA"]),
    ]
    cards = []
    for n, (title, work, tags) in enumerate(items):
        it = {"id": f"demo{n}", "title": title, "work": work, "tags": tags, "source": "Adala News",
              "published": 1791648348 - n * 7200, "link": "https://example.org"}
        head, cat, vis = editorial.rewrite_title(title), editorial.classify(it), fake_visual(n)
        card = render.render_post(it, cat, head, cfg["brand"], vis, cfg["timezone"])
        cards.append(card)
        render.save_jpeg(card, OUT / f"post_{n}.jpg")
        render.save_jpeg(render.render_story(it, cat, head, cfg["brand"], vis, cfg["timezone"]), OUT / f"story_{n}.jpg")
        print(cat, "|", head)
    cov = render.render_recap_cover([fake_visual(i) for i in range(4)], cfg["brand"], "5 → 11 OCT.", 9)
    render.save_jpeg(cov, OUT / "recap_cover.jpg")
    render.save_jpeg(render.render_end_card(cfg["brand"]), OUT / "end_card.jpg")
    if "--reel" in sys.argv:
        render.make_reel([cov] + cards + [render.render_end_card(cfg["brand"])], OUT / "reel.mp4", 1.0)
        print("reel ok")
