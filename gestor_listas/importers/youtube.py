"""Creación de playlists en YouTube mediante la YouTube Data API v3.

A diferencia de la lectura (yt-dlp, sin credenciales), CREAR playlists escribe en
tu cuenta y requiere OAuth 2.0 de Google. Este importador usa la API v3 mediante
`requests` puro (sin `google-api-python-client`).

Puesta en marcha (una sola vez):
1. Crea un proyecto en https://console.cloud.google.com/
2. Habilita "YouTube Data API v3".
3. Crea credenciales OAuth (tipo "Aplicación de escritorio").
4. Pon YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET en tu .env.
5. Ejecuta YouTubeImporter.authenticate(auto_save=True) y sigue el flujo del
   navegador; se guardará YOUTUBE_REFRESH_TOKEN en .env.

Cuota: la API v3 da 10.000 unidades/día. Crear playlist ≈ 50, buscar ≈ 100,
añadir un vídeo ≈ 50. Importar listas grandes puede agotar la cuota diaria.
"""

from __future__ import annotations

import logging
import time
import webbrowser
from typing import Optional

import requests

from ..config import YouTubeConfig
from ..errors import AuthError, ProviderError
from ..http import make_session
from ..model import Playlist, Track

logger = logging.getLogger(__name__)

API_BASE = "https://www.googleapis.com/youtube/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
SCOPE = "https://www.googleapis.com/auth/youtube"


class YouTubeImporter:
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
    ) -> None:
        cfg = YouTubeConfig.from_env()
        self.client_id = client_id or cfg.client_id
        self.client_secret = client_secret or cfg.client_secret
        self._refresh_token = refresh_token or cfg.refresh_token
        self._session = make_session()
        self._access_token: Optional[str] = None
        self._token_expires: float = 0.0

        if not self.client_id or not self.client_secret:
            raise AuthError(
                "Faltan credenciales OAuth de YouTube. Configura YOUTUBE_CLIENT_ID "
                "y YOUTUBE_CLIENT_SECRET en .env (ver docstring de YouTubeImporter)."
            )
        if not self._refresh_token:
            raise AuthError(
                "Falta YOUTUBE_REFRESH_TOKEN. Ejecuta "
                "YouTubeImporter.authenticate(auto_save=True) una vez."
            )

    # ── OAuth ────────────────────────────────────────────────────

    def _ensure_access_token(self) -> str:
        if self._access_token and time.time() < self._token_expires:
            return self._access_token
        resp = self._session.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            raise AuthError(f"No se pudo refrescar el token de YouTube: {resp.text}")
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expires = time.time() + data.get("expires_in", 3600) - 60
        return self._access_token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._ensure_access_token()}"}

    def _post(self, path: str, params: dict, body: dict) -> dict:
        resp = self._session.post(
            f"{API_BASE}{path}",
            params=params,
            json=body,
            headers={**self._headers(), "Content-Type": "application/json"},
            timeout=30,
        )
        self._raise_for_api_error(resp)
        return resp.json()

    def _get(self, path: str, params: dict) -> dict:
        resp = self._session.get(
            f"{API_BASE}{path}",
            params=params,
            headers=self._headers(),
            timeout=30,
        )
        self._raise_for_api_error(resp)
        return resp.json()

    @staticmethod
    def _raise_for_api_error(resp: requests.Response) -> None:
        if resp.status_code == 200:
            return
        # Detecta agotamiento de cuota para dar un mensaje útil.
        text = resp.text
        if resp.status_code == 403 and "quota" in text.lower():
            raise ProviderError(
                "Cuota diaria de la YouTube Data API agotada (10.000 unidades/día). "
                "Inténtalo de nuevo mañana o usa otro proyecto de Google Cloud."
            )
        if resp.status_code in (401, 403):
            raise AuthError(f"YouTube API rechazó la petición ({resp.status_code}): {text}")
        raise ProviderError(f"YouTube API error ({resp.status_code}): {text}")

    # ── Operaciones de escritura ─────────────────────────────────

    def create_playlist(self, name: str, description: str = "", public: bool = False) -> Playlist:
        data = self._post(
            "/playlists",
            params={"part": "snippet,status"},
            body={
                "snippet": {"title": name, "description": description},
                "status": {"privacyStatus": "public" if public else "private"},
            },
        )
        return Playlist(
            id=data["id"],
            name=data["snippet"]["title"],
            description=data["snippet"].get("description"),
            public=data.get("status", {}).get("privacyStatus") == "public",
            source="youtube",
            source_url=f"https://www.youtube.com/playlist?list={data['id']}",
        )

    def add_video_to_playlist(self, playlist_id: str, video_id: str) -> None:
        self._post(
            "/playlistItems",
            params={"part": "snippet"},
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id},
                }
            },
        )

    def search_video_id(self, title: str, artist: str) -> Optional[str]:
        data = self._get(
            "/search",
            params={
                "part": "snippet",
                "q": f"{artist} - {title}",
                "type": "video",
                "maxResults": 1,
            },
        )
        items = data.get("items", [])
        if not items:
            return None
        return items[0]["id"]["videoId"]

    @staticmethod
    def _video_id_from_track(track: Track) -> Optional[str]:
        if track.uri and "youtube.com/watch?v=" in track.uri:
            return track.uri.split("v=", 1)[1].split("&", 1)[0]
        if track.uri and "youtu.be/" in track.uri:
            return track.uri.split("youtu.be/", 1)[1].split("?", 1)[0]
        return None

    # ── Orquestación ─────────────────────────────────────────────

    def import_playlist(
        self,
        playlist: Playlist,
        name: Optional[str] = None,
        description: Optional[str] = None,
        public: bool = False,
    ) -> Playlist:
        created = self.create_playlist(
            name=name or playlist.name,
            description=description or playlist.description or "",
            public=public or playlist.public,
        )

        added = 0
        for track in playlist.tracks:
            video_id = self._video_id_from_track(track)
            if not video_id:
                video_id = self.search_video_id(track.title, track.artist)
            if not video_id:
                logger.warning("No se encontró en YouTube: %s - %s", track.artist, track.title)
                continue
            self.add_video_to_playlist(created.id, video_id)
            added += 1

        logger.info("Importadas %d/%d pistas a la playlist de YouTube '%s'",
                    added, playlist.track_count, created.name)
        return created

    # ── Autenticación interactiva (una sola vez) ─────────────────

    @staticmethod
    def authenticate(
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        auto_save: bool = False,
    ) -> str:
        import urllib.parse

        cfg = YouTubeConfig.from_env()
        client_id = client_id or cfg.client_id
        client_secret = client_secret or cfg.client_secret
        redirect_uri = redirect_uri or cfg.redirect_uri
        if not client_id or not client_secret:
            raise AuthError(
                "Faltan YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET para autenticar."
            )

        params = urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        })
        auth_url = f"{AUTH_URL}?{params}"
        print(f"Abre esta URL en tu navegador para autorizar:\n{auth_url}")
        webbrowser.open(auth_url)

        code = input("Pega el código de autorización: ").strip()
        resp = requests.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            raise AuthError(f"Error obteniendo el token de YouTube: {resp.text}")
        refresh_token = resp.json().get("refresh_token")
        if not refresh_token:
            raise AuthError(
                "Google no devolvió refresh_token. Revoca el acceso de la app en "
                "https://myaccount.google.com/permissions y reautoriza con prompt=consent."
            )

        if auto_save:
            from dotenv import set_key
            set_key(".env", "YOUTUBE_REFRESH_TOKEN", refresh_token)
            logger.info("Refresh token de YouTube guardado en .env")

        return refresh_token
