from __future__ import annotations

import json
import logging
import os
import re
import time
import webbrowser
from typing import Optional

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from ..config import SpotifyConfig
from ..errors import AuthError
from ..http import make_session
from ..model import Playlist, Track
from .base import Provider

logger = logging.getLogger(__name__)

SPOTIFY_API = "https://api.spotify.com/v1"

# Compatibilidad: se exponen a nivel de módulo, pero la fuente de verdad es
# SpotifyConfig (config.py). Sobrescribibles con SPOTDL_CLIENT_ID/SECRET.
SPOTDL_CLIENT_ID = SpotifyConfig.from_env().spotdl_client_id
SPOTDL_CLIENT_SECRET = SpotifyConfig.from_env().spotdl_client_secret

PLAYLIST_URL_RE = re.compile(
    r"(?:open\.spotify\.com/playlist/|spotify:playlist:)([a-zA-Z0-9]+)"
)


# El mapeo vive en Track.from_spotify_item; se mantiene este alias porque los
# call-sites y algún test lo referencian por nombre de módulo.
_track_from_sp_item = Track.from_spotify_item


class SpotifyProvider(Provider):
    name = "spotify"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: str = "http://localhost:8888/callback",
        scope: str = "playlist-read-private playlist-modify-private playlist-modify-public",
        cache_path: str = ".spotify_cache",
        bearer_token: Optional[str] = None,
        use_client_credentials: bool = False,
        use_scraping: bool = False,
    ) -> None:
        cfg = SpotifyConfig.from_env()
        self.client_id = client_id or cfg.client_id
        self.client_secret = client_secret or cfg.client_secret
        self.redirect_uri = redirect_uri
        self.scope = scope
        self.cache_path = cache_path
        self._sp_client: Optional[spotipy.Spotify] = None
        self._token: Optional[str] = None
        self._token_expires: float = 0
        self._scraper: Optional[object] = None
        self._session = make_session()

        if use_scraping:
            self._init_scraper()
        elif use_client_credentials:
            self._cc_client_id = cfg.spotdl_client_id
            self._cc_client_secret = cfg.spotdl_client_secret
        elif bearer_token:
            self._token = bearer_token
            self._token_expires = float("inf")
        elif cfg.bearer_token:
            self._token = cfg.bearer_token
            self._token_expires = float("inf")

    def _init_scraper(self) -> None:
        try:
            from SpotipyFree import Spotify as Scraper
            self._scraper = Scraper()
        except ImportError:
            raise RuntimeError(
                "SpotipyFree no instalado. Ejecuta: pip install spotipyfree websockets"
            )

    def _ensure_token(self) -> str:
        if self._token and time.time() < self._token_expires:
            return self._token
        if hasattr(self, "_cc_client_id"):
            return self._get_client_credentials_token()
        raise AuthError(
            "No hay token disponible. Usa bearer_token, use_client_credentials=True, "
            "use_scraping=True, o completa OAuth con authenticate()"
        )

    def _get_client_credentials_token(self) -> str:
        import base64
        cc = base64.b64encode(
            f"{self._cc_client_id}:{self._cc_client_secret}".encode()
        ).decode()
        resp = self._session.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {cc}"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires = time.time() + data.get("expires_in", 3600) - 60
        return self._token

    @property
    def client(self) -> spotipy.Spotify:
        if self._token:
            raise RuntimeError("Usa los métodos directos, no el cliente spotipy")
        if self._scraper:
            raise RuntimeError("Usa los métodos scraping, no el cliente spotipy")
        if self._sp_client is None:
            refresh_token = SpotifyConfig.from_env().refresh_token
            if refresh_token and not os.path.exists(self.cache_path):
                with open(self.cache_path, "w") as f:
                    json.dump({"refresh_token": refresh_token}, f)
            self._sp_client = spotipy.Spotify(
                auth_manager=SpotifyOAuth(
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    redirect_uri=self.redirect_uri,
                    scope=self.scope,
                    cache_path=self.cache_path,
                )
            )
        return self._sp_client

    def _api_get(self, path: str, params: Optional[dict] = None) -> dict:
        token = self._ensure_token()
        resp = self._session.get(
            f"{SPOTIFY_API}{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _api_post(self, path: str, json_data: dict) -> dict:
        token = self._ensure_token()
        resp = self._session.post(
            f"{SPOTIFY_API}{path}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=json_data,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _api_get_paginated(self, path: str) -> list[dict]:
        token = self._ensure_token()
        items: list[dict] = []
        url: Optional[str] = SPOTIFY_API + path
        while url:
            resp = self._session.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            items.extend(data.get("items", []))
            url = data.get("next")
        return items

    @staticmethod
    def authenticate(
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        auto_save: bool = False,
    ) -> str:
        cfg = SpotifyConfig.from_env()
        client_id = client_id or cfg.client_id
        client_secret = client_secret or cfg.client_secret
        redirect_uri = redirect_uri or cfg.redirect_uri

        sp_oauth = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope="playlist-read-private playlist-modify-private playlist-modify-public",
            cache_path=None,
        )

        auth_url = sp_oauth.get_authorize_url()
        print(f"Abre esta URL en tu navegador para autorizar:\n{auth_url}")
        webbrowser.open(auth_url)

        response = input("Pega la URL completa a la que fuiste redirigido: ").strip()
        code = sp_oauth.parse_response_code(response)
        token_info = sp_oauth.get_access_token(code)
        refresh_token = token_info["refresh_token"]

        if auto_save:
            from dotenv import set_key
            set_key(".env", "SPOTIFY_REFRESH_TOKEN", refresh_token)
            logger.info("Refresh token de Spotify guardado en .env")

        return refresh_token

    @staticmethod
    def playlist_id_from_url(url: str) -> Optional[str]:
        m = PLAYLIST_URL_RE.search(url)
        return m.group(1) if m else None

    def get_playlists(self) -> list[Playlist]:
        if self._scraper:
            raise NotImplementedError(
                "No se pueden listar playlists del usuario sin login vía scraping. "
                "Usa get_playlist(playlist_id) o get_playlist_by_url(url) con una URL específica."
            )
        if self._token:
            data = self._api_get("/me/playlists", {"limit": 50})
            return [self._to_model_short(item) for item in data.get("items", [])]
        playlists: list[Playlist] = []
        results = self.client.current_user_playlists()
        while results:
            for item in results["items"]:
                playlists.append(self._to_model_short(item))
            if results.get("next"):
                results = self.client.next(results)
            else:
                break
        return playlists

    def get_playlist(self, playlist_id: str) -> Playlist:
        if self._scraper:
            return self._get_playlist_scraping(playlist_id)
        data = self._api_get(f"/playlists/{playlist_id}")
        tracks = self._api_get_paginated(f"/playlists/{playlist_id}/tracks")
        model_tracks = [_track_from_sp_item(item) for item in tracks if _track_from_sp_item(item)]
        return Playlist(
            id=data["id"],
            name=data["name"],
            description=data.get("description"),
            tracks=model_tracks,
            owner=data["owner"]["display_name"] if data.get("owner") else None,
            public=data.get("public", False),
            source=self.name,
            source_url=data.get("external_urls", {}).get("spotify"),
        )

    def _get_playlist_scraping(self, playlist_id: str) -> Playlist:
        scraper = self._scraper
        data = scraper.playlist(playlist_id)
        tracks_result = scraper.playlist_items(playlist_id)
        model_tracks: list[Track] = []
        for item in tracks_result.get("items", []):
            t = _track_from_sp_item(item)
            if t:
                model_tracks.append(t)
        url = None
        ext = data.get("external_urls")
        if isinstance(ext, dict):
            url = ext.get("spotify")
        return Playlist(
            id=data["id"],
            name=data.get("name", ""),
            description=data.get("description"),
            tracks=model_tracks,
            owner=data.get("owner", {}).get("display_name") if isinstance(data.get("owner"), dict) else None,
            public=data.get("public", False),
            source=self.name,
            source_url=url,
        )

    # get_playlist_by_url se hereda de Provider.

    def search_track(self, title: str, artist: str) -> Optional[Track]:
        if self._scraper:
            return self._search_track_scraping(title, artist)
        query = f"track:{title} artist:{artist}"
        data = self._api_get("/search", {"q": query, "type": "track", "limit": 1})
        items = data.get("tracks", {}).get("items", [])
        return _track_from_sp_item({"track": items[0]}) if items else None

    def _search_track_scraping(self, title: str, artist: str) -> Optional[Track]:
        result = self._scraper.search(f"{title} {artist}", type="track", limit=1)
        items = result.get("tracks", {}).get("items", [])
        return _track_from_sp_item({"track": items[0]}) if items else None

    def create_playlist(self, name: str, description: str = "", public: bool = False) -> Playlist:
        if self._scraper:
            raise NotImplementedError("create_playlist no disponible en modo scraping. Usa bearer_token.")
        user_data = self._api_get("/me")
        user_id = user_data["id"]
        data = self._api_post(
            f"/users/{user_id}/playlists",
            {"name": name, "description": description, "public": public},
        )
        return Playlist(
            id=data["id"],
            name=data["name"],
            description=data.get("description"),
            owner=data["owner"]["display_name"] if data.get("owner") else None,
            public=data.get("public", False),
            source=self.name,
            source_url=data.get("external_urls", {}).get("spotify"),
        )

    def add_tracks_to_playlist(self, playlist_id: str, uris: list[str]) -> None:
        if self._scraper:
            raise NotImplementedError("add_tracks_to_playlist no disponible en modo scraping. Usa bearer_token.")
        self._api_post(f"/playlists/{playlist_id}/tracks", {"uris": uris})

    def _to_model_short(self, sp_item: dict) -> Playlist:
        return Playlist(
            id=sp_item["id"],
            name=sp_item["name"],
            description=sp_item.get("description"),
            owner=sp_item["owner"].get("display_name") if sp_item.get("owner") else None,
            public=sp_item.get("public", False),
            source=self.name,
            source_url=sp_item.get("external_urls", {}).get("spotify"),
        )

    def _to_model(self, sp_playlist: dict) -> Playlist:
        tracks: list[Track] = []
        results = sp_playlist.get("tracks", {})
        while results:
            for item in results.get("items", []):
                t = _track_from_sp_item(item)
                if t:
                    tracks.append(t)
            if results.get("next"):
                results = self.client.next(results)
            else:
                break
        return Playlist(
            id=sp_playlist["id"],
            name=sp_playlist["name"],
            description=sp_playlist.get("description"),
            tracks=tracks,
            owner=sp_playlist["owner"].get("display_name") if sp_playlist.get("owner") else None,
            public=sp_playlist.get("public", False),
            source=self.name,
            source_url=sp_playlist.get("external_urls", {}).get("spotify"),
        )
