"""Rédaction des descriptions avec l'API Gemini de Google (offre gratuite, clé dans le secret GEMINI_API_KEY).

Tarifs et offre gratuite : https://ai.google.dev/gemini-api/docs/pricing
Si l'IA ne répond pas, l'actu est retentée au passage suivant (pas de post sans description).
"""
import html
import json
import re

import requests

from .common import USER_AGENT, env

API = "https://generativelanguage.googleapis.com/v1beta"
_model_cache = {}

SYSTEM = """Tu es le rédacteur de SOKUHŌ, un compte Instagram français d'actualités anime, manga, manhua et webtoon.
À partir d'un article (souvent en français, parfois en anglais), tu rédiges en FRANÇAIS, avec tes propres mots (jamais de copier-coller de phrases entières) :
- "is_news" : true si c'est une vraie actualité (annonce d'anime, saison, film, date, trailer, casting, sortie manga, fin de série, streaming, événement, record, décès…), false si c'est une critique, une interview, un dossier culturel, un test de jeu vidéo ou un article hors sujet.
- "headline" : titre choc et clair pour l'image, 75 caractères maximum, sans emoji, qui contient le nom de l'œuvre.
- "work" : nom de l'œuvre tel qu'il apparaît dans le titre (chaîne vide s'il n'y en a pas). Jamais un pays, un éditeur ou un studio.
- "category" : une valeur parmi ANIME, MANGA, MANHUA, WEBTOON, ACTU.
- "body" : 4 à 7 phrases factuelles qui expliquent l'actu en détail : ce qui est annoncé, quand, quel studio / éditeur / plateforme (Crunchyroll, ADN, Netflix…), staff et voix si connus, de quoi parle l'œuvre en une phrase, et où en est la série. N'invente RIEN : si une info n'est pas dans l'article, ne la mentionne pas. Ton dynamique mais informatif, 2 ou 3 emojis maximum dans tout le texte.
- "key_facts" : liste de 0 à 4 faits courts (ex. "📅 Sortie : janvier 2027", "🎬 Studio : MAPPA", "📺 Diffusion : Crunchyroll"), uniquement s'ils sont dans l'article.
- "question" : une question courte pour faire réagir les abonnés en commentaire.
- "hashtags" : 3 à 5 hashtags spécifiques à l'œuvre (sans #, sans espaces).
- "mood" : ambiance musicale qui colle à l'actu, une valeur parmi epic, hype, chill, emotional, dark, fun.
Réponds uniquement avec un objet JSON valide."""


def _clean(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def article_text(item, max_chars=5000):
    """Texte de l'article : contenu du flux s'il est complet, sinon les paragraphes de la page."""
    text = _clean(item.get("content", ""))
    if len(text) < 600:
        try:
            r = requests.get(item["link"], headers={"User-Agent": USER_AGENT}, timeout=20)
            paras = [_clean(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", r.text, re.S | re.I)]
            paras = [p for p in paras if len(p) > 60 and "cookie" not in p.lower()]
            text = " ".join(paras) or text
        except requests.RequestException:
            pass
    if len(text) < 200:
        text = (text + " " + _clean(item.get("summary", ""))).strip()
    return text[:max_chars]


def pick_model(key):
    """Choisit un modèle Gemini « Flash-Lite » (ou « Flash ») disponible pour cette clé."""
    if env("AI_MODEL"):
        return env("AI_MODEL")
    if "m" in _model_cache:
        return _model_cache["m"]
    r = requests.get(f"{API}/models", params={"key": key, "pageSize": 200}, timeout=20)
    r.raise_for_status()
    names = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    stable = [n for n in names if "preview" not in n and "exp" not in n]
    for want in ("flash-lite", "flash"):
        cands = sorted([n for n in stable if want in n and "image" not in n and "tts" not in n
                        and "live" not in n and "audio" not in n], reverse=True)
        if cands:
            _model_cache["m"] = cands[0]
            return cands[0]
    raise RuntimeError("aucun modèle Gemini Flash disponible pour cette clé")


def write(item, timeout=60):
    """Renvoie un dict (is_news, headline, work, category, body, key_facts, question, hashtags, mood) ou None."""
    key = env("GEMINI_API_KEY")
    if not key:
        return None
    text = article_text(item)
    user = f"Source : {item['source']}\nTitre : {item['title']}\nCatégories : {', '.join(item['tags'])}\n\nArticle :\n{text}"
    r = None
    try:
        model = pick_model(key)
        payload = {
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1200, "responseMimeType": "application/json"},
        }
        r = requests.post(f"{API}/models/{model}:generateContent", params={"key": key}, json=payload, timeout=timeout)
        if r.status_code != 200:
            print(f"   IA indisponible ({r.status_code} : {r.text[:200]})", flush=True)
            return None
        parts = r.json()["candidates"][0]["content"]["parts"]
        content = "".join(p.get("text", "") for p in parts)
        m = re.search(r"\{.*\}", content, re.S)
        data = json.loads(m.group(0) if m else content)
    except (requests.RequestException, KeyError, IndexError, ValueError, RuntimeError) as ex:
        print(f"   IA indisponible ({type(ex).__name__}: {ex}) {r.text[:200] if r is not None else ''}", flush=True)
        return None
    if data.get("category") not in ("ANIME", "MANGA", "MANHUA", "WEBTOON", "ACTU"):
        data["category"] = None
    data["headline"] = (data.get("headline") or "").strip()[:90]
    data["work"] = (data.get("work") or "").strip()
    if data["work"] and data["work"].lower() not in (data["headline"] + " " + item["title"]).lower():
        data["work"] = ""
    return data
