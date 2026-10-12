"""Publication via l'API Instagram officielle (connexion Instagram, graph.instagram.com).

Documentation Meta :
  https://developers.facebook.com/docs/instagram-platform/content-publishing
  https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media
"""
import time

import requests

from .common import env

API = "https://graph.instagram.com"


class InstagramError(RuntimeError):
    pass


class Instagram:
    def __init__(self, token=None, user_id=None, version=None):
        self.token = token or env("IG_ACCESS_TOKEN")
        if not self.token:
            raise InstagramError("Secret IG_ACCESS_TOKEN manquant.")
        self.version = version or env("IG_API_VERSION", "v25.0")
        self.user_id = user_id or env("IG_USER_ID") or self.me()["user_id"]

    def _call(self, method, path, **params):
        params["access_token"] = self.token
        r = requests.request(method, f"{API}/{self.version}/{path}", params=params, timeout=90)
        data = r.json() if r.content else {}
        if r.status_code >= 400 or "error" in data:
            err = data.get("error", {})
            raise InstagramError(f"{method} {path} → {r.status_code} {err.get('message', r.text)[:300]}")
        return data

    def me(self):
        return self._call("GET", "me", fields="user_id,username")

    def quota(self):
        data = self._call("GET", f"{self.user_id}/content_publishing_limit", fields="quota_usage,config")
        return (data.get("data") or [{}])[0]

    # --- étapes communes : conteneur → attente → publication ---

    def _container(self, **params):
        return self._call("POST", f"{self.user_id}/media", **params)["id"]

    def _wait(self, container, video=False):
        # Meta conseille de vérifier l'état au plus une fois par minute, pendant 5 minutes maximum.
        delays = [5, 15, 40, 60, 60, 60, 60] if video else [3, 10, 60, 60, 60, 60]
        for delay in delays:
            time.sleep(delay)
            status = self._call("GET", container, fields="status_code").get("status_code")
            if status == "FINISHED":
                return
            if status in ("ERROR", "EXPIRED"):
                raise InstagramError(f"Conteneur {container} en état {status}")
        raise InstagramError(f"Conteneur {container} toujours pas prêt après 5 minutes")

    def _publish(self, container):
        return self._call("POST", f"{self.user_id}/media_publish", creation_id=container)["id"]

    # --- types de publication ---

    def publish_image(self, image_url, caption, alt_text=""):
        params = {"image_url": image_url, "caption": caption}
        if alt_text:
            params["alt_text"] = alt_text[:1000]
        c = self._container(**params)
        self._wait(c)
        return self._publish(c)

    def publish_story(self, image_url):
        c = self._container(image_url=image_url, media_type="STORIES")
        self._wait(c)
        return self._publish(c)

    def publish_carousel(self, image_urls, caption):
        children = [self._container(image_url=u, is_carousel_item="true") for u in image_urls[:10]]
        for c in children:
            self._wait(c)
        c = self._container(media_type="CAROUSEL", children=",".join(children), caption=caption)
        self._wait(c)
        return self._publish(c)

    def publish_reel(self, video_url, caption, cover_url=None, audio_name=None):
        params = {"media_type": "REELS", "video_url": video_url, "caption": caption, "share_to_feed": "true"}
        if audio_name:
            params["audio_name"] = audio_name[:80]  # nom du son original affiché sous le reel
        if cover_url:
            params["cover_url"] = cover_url
        c = self._container(**params)
        self._wait(c, video=True)
        return self._publish(c)


def refresh_token(token):
    """Prolonge le jeton longue durée de 60 jours (il doit avoir au moins 24 h et ne pas être expiré)."""
    r = requests.get(f"{API}/refresh_access_token",
                     params={"grant_type": "ig_refresh_token", "access_token": token}, timeout=30)
    data = r.json()
    if "access_token" not in data:
        raise InstagramError(f"Rafraîchissement refusé : {data}")
    return data["access_token"], int(data.get("expires_in", 0))
