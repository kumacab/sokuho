"""Test de bout en bout sans réseau : flux d'exemple → posts + stories → publication simulée → récap."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bot.common as common  # noqa: E402

tmp = Path(tempfile.mkdtemp())
common.STATE_PATH = tmp / "state.json"
import bot.__main__ as m  # noqa: E402
from bot import feeds, render  # noqa: E402
from test_render_with_visual import fake_visual  # noqa: E402

m.MEDIA_DIR = tmp / "media"
m.load_state, m.save_state = common.load_state, common.save_state
m.in_quiet_hours = lambda cfg: False
render.find_og_image = lambda url: "https://example.org/visuel.jpg"
render.download_image = lambda url: fake_visual(len(url) % 4)
os.environ.pop("DRY_RUN", None)

cfg = common.load_config()
cfg["max_age_hours"] = 10 ** 6  # les actus d'exemple datent de quelques jours
cfg["max_posts_per_run"] = 10
fx = ROOT / "tests" / "fixtures"


def fake_fetch(cfg, log=print):
    out = []
    for s in cfg["sources"]:
        out += feeds.parse_feed((fx / (s["name"].lower().replace(" ", "_") + ".xml")).read_bytes(), s)
    return out


m.feeds.fetch_all = fake_fetch

# 1er passage : historique ignoré, une seule actu → 1 post + 1 story
m.cmd_prepare(cfg)
st = common.load_state()
assert [q["type"] for q in st["queue"]] == ["post", "story"], st["queue"]

# On « oublie » l'historique pour fabriquer toutes les actus d'exemple
st["seen"] = {"x": common.now_utc().timestamp()}
common.save_state(st)
m.cmd_prepare(cfg)
st = common.load_state()
types = [q["type"] for q in st["queue"]]
assert types.count("post") >= 4 and types.count("story") == types.count("post"), types
assert all((m.MEDIA_DIR / f).exists() for q in st["queue"] for f in q["files"])
assert not any("Brigandine" in q["headline"] for q in st["queue"]), "le jeu vidéo aurait dû être filtré"


class FakeIG:
    n = 0

    def _id(self):
        FakeIG.n += 1
        return str(FakeIG.n)

    def publish_image(self, *a):
        return self._id()

    publish_story = publish_carousel = publish_reel = publish_image


m.wait_online = lambda url, tries=1: True
os.environ["PUBLIC_BASE_URL"] = "https://exemple.github.io/sokuho"
published = [m.publish_one(FakeIG(), q) for q in st["queue"]]
for q, mid in zip(st["queue"], published):
    st["posted"].append({"id": q["id"], "type": q["type"], "headline": q["headline"], "key": q.get("key"),
                         "visual": q.get("visual"), "card": q["files"][0] if q["type"] == "post" else None,
                         "media_id": mid, "ts": common.now_utc().timestamp()})
st["queue"] = []
common.save_state(st)

# Doublon : la même annonce reprise par un autre site doit être ignorée
assert m.is_duplicate({"title": "Nouvel anime Dr. Stone Terraforming annoncé", "id": "x"}, st, cfg)
assert not m.is_duplicate({"title": "Le manga One Piece en pause", "id": "y"}, st, cfg)

# Récap de la semaine : carrousel (couverture + cartes) + reel
m.cmd_recap_now(cfg)
st = common.load_state()
kinds = [q["type"] for q in st["queue"]]
assert kinds == ["carousel", "reel"], kinds
car = st["queue"][0]
assert 4 <= len(car["files"]) <= 10 and "1️⃣" in car["caption"]
assert (m.MEDIA_DIR / st["queue"][1]["files"][0]).stat().st_size > 10000
print(f"OK — {types.count('post')} posts, {types.count('story')} stories, récap de {len(car['files'])} images + reel")
print("Médias produits dans", m.MEDIA_DIR)
