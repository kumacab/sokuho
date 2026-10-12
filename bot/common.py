"""Outils partagés : chemins, configuration, état, normalisation de texte."""
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "data" / "state.json"
MEDIA_DIR = ROOT / "media"  # images et vidéos servies en ligne (branche « media » + GitHub Pages)
FONTS = ROOT / "assets" / "fonts"

USER_AGENT = "Mozilla/5.0 (compatible; SokuhoBot/1.0; +https://github.com)"


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def now_utc():
    return datetime.now(timezone.utc)


def load_state():
    if STATE_PATH.exists():
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"seen": {}, "queue": [], "posted": []}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # On ne garde que 30 jours d'historique pour que le fichier reste léger.
    cutoff = now_utc().timestamp() - 30 * 86400
    state["seen"] = {k: v for k, v in state["seen"].items() if v >= cutoff}
    state["posted"] = [p for p in state["posted"] if p.get("ts", 0) >= cutoff]
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


STOP = set("""le la les l un une des de du d en et a au aux pour par sur avec son sa ses
anime manga manhua webtoon manhwa film saison season teaser trailer video vidéo affiche
annonce annoncé annonces adapte adapté adaptation nouvel nouveau nouvelle infos toutes
informations premiere première promo date sortie the of""".split())


def title_key(title):
    """Mots-clés d'un titre, pour repérer la même actu publiée par deux sites."""
    t = strip_accents(title.lower())
    words = re.findall(r"[a-z0-9]+", t)
    return sorted({w for w in words if w not in STOP and len(w) > 1})


def similar(a, b):
    a, b = set(a), set(b)
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= 0.5


def hashtag(text):
    t = re.sub(r"[’'](s\b)?", "", strip_accents(text))  # « Nue's » → « Nue »
    parts = re.findall(r"[A-Za-z0-9]+", t)
    tag = "".join(p[:1].upper() + p[1:] for p in parts)
    return tag if 3 <= len(tag) <= 28 else ""  # un hashtag tronqué ne sert à rien : on l'abandonne


def env(name, default=None):
    v = os.environ.get(name)
    return v if v not in (None, "") else default
