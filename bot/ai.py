"""Rédaction des descriptions avec un modèle d'IA gratuit (GitHub Models), avec repli sans IA.

Dans GitHub Actions, le jeton GITHUB_TOKEN suffit (permission « models: read » dans le workflow).
Offre gratuite : environ 150 requêtes par jour pour les petits modèles, largement assez pour 30 posts.
Si l'appel échoue (quota, panne), le robot publie quand même avec une description sans IA.
"""
import html
import json
import re

import requests

from .common import USER_AGENT, env

ENDPOINT = "https://models.github.ai/inference/chat/completions"

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


def write(item, model=None, timeout=60):
    """Renvoie un dict (is_news, headline, work, category, body, key_facts, question, hashtags) ou None."""
    token = env("GITHUB_MODELS_TOKEN") or env("GITHUB_TOKEN")
    if not token:
        return None
    text = article_text(item)
    user = f"Source : {item['source']}\nTitre : {item['title']}\nCatégories : {', '.join(item['tags'])}\n\nArticle :\n{text}"
    payload = {
        "model": model or env("AI_MODEL", "openai/gpt-4o-mini"),
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        "temperature": 0.4,
        "max_tokens": 900,
        "response_format": {"type": "json_object"},
    }
    try:
        r = requests.post(ENDPOINT, json=payload, timeout=timeout,
                          headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        if r.status_code != 200:
            print(f"   IA indisponible ({r.status_code} : {r.text[:150]})", flush=True)
            return None
        data = json.loads(r.json()["choices"][0]["message"]["content"])
    except (requests.RequestException, KeyError, ValueError) as ex:
        print(f"   IA indisponible ({ex})", flush=True)
        return None
    if data.get("category") not in ("ANIME", "MANGA", "MANHUA", "WEBTOON", "ACTU"):
        data["category"] = None
    data["headline"] = (data.get("headline") or "").strip()[:90]
    data["work"] = (data.get("work") or "").strip()
    if data["work"] and data["work"].lower() not in (data["headline"] + " " + item["title"]).lower():
        data["work"] = ""
    return data
