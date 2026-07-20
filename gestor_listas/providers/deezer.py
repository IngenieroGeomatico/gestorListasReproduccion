from __future__ import annotations

import logging
import re
import urllib.parse
import webbrowser
from typing import Optional

import deezer
import requests

from ..config import DeezerConfig
from ..errors import AuthError, ProviderError
from ..http import make_session
from ..model import Playlist, Track
from .base import Provider

logger = logging.getLogger(__name__)

GW_URL = "https://www.deezer.com/ajax/gw-light.php"
PUBLIC_API = "https://api.deezer.com"


class DeezerProvider(Provider):
    name = "deezer"

    def __init__(
        self,
        access_token: Optional[str] = None,
        arl: Optional[str] = None,
    ) -> None:
        cfg = DeezerConfig.from_env()
        self._arl = arl or cfg.arl
        token = access_token or cfg.access_token

        if not self._arl and not token and cfg.email and cfg.password:
            self._arl = self.login(cfg.email, cfg.password)

        if self._arl:
            self._session = self._build_arl_session()
            self._api_token: Optional[str] = None
            self.client = None
        else:
            self.client = deezer.Client(access_token=token) if token else deezer.Client()
            self._session = None

    # ── ARL (web API) internals ──────────────────────────────────

    def _build_arl_session(self) -> requests.Session:
        session = make_session()
        session.cookies.set("arl", self._arl, domain=".deezer.com")
        resp = session.post(
            GW_URL,
            params={"api_version": "1.0", "api_token": "null", "input": "3", "method": "deezer.getUserData"},
            json={},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            raise AuthError(f"ARL inválido o expirado: {data['error']}")
        self._api_token = data["results"].get("checkForm", "")
        return session

    def _gw(self, method: str, args: object = None) -> dict:
        if not self._api_token and method != "deezer.getUserData":
            self._api_token = self._refresh_api_token()
        params = {
            "api_version": "1.0",
            "api_token": "null" if method == "deezer.getUserData" else self._api_token,
            "input": "3",
            "method": method,
        }
        resp = self._session.post(GW_URL, params=params, json=args or {})
        resp.raise_for_status()
        result = resp.json()
        err = result.get("error")
        if err:
            # Un token de API caducado se manifiesta como VALID_TOKEN_REQUIRED o
            # GATEWAY_ERROR: refrescamos el token y reintentamos una vez.
            err_keys = set(err) if isinstance(err, dict) else set()
            if err_keys & {"VALID_TOKEN_REQUIRED", "GATEWAY_ERROR"}:
                self._api_token = self._refresh_api_token()
                return self._gw(method, args)
            raise ProviderError(f"Deezer API error: {err}")
        if method == "deezer.getUserData":
            self._api_token = result["results"]["checkForm"]
        return result.get("results", {})

    def _refresh_api_token(self) -> str:
        resp = self._session.post(
            GW_URL,
            params={"api_version": "1.0", "api_token": "null", "input": "3", "method": "deezer.getUserData"},
            json={},
        )
        resp.raise_for_status()
        return resp.json()["results"]["checkForm"]

    def _arl_playlist(self, item: dict, load_tracks: bool = False) -> Playlist:
        tracks: list[Track] = []
        if load_tracks:
            data = self._gw("playlist.getSongs", {"PLAYLIST_ID": item["PLAYLIST_ID"], "nb": -1})
            tracks = [Track.from_deezer_gw(t) for t in data.get("data", [])]
        return Playlist(
            id=str(item["PLAYLIST_ID"]),
            name=item.get("TITLE", ""),
            description=item.get("DESCRIPTION"),
            tracks=tracks,
            owner=str(item.get("PARENT_USER_ID", "")),
            public=item.get("STATUS", 0) == 0,
            source=self.name,
        )

    def _public_search(self, title: str, artist: str) -> Optional[Track]:
        resp = requests.get(f"{PUBLIC_API}/search", params={"q": f"{artist} {title}"}, timeout=10)
        resp.raise_for_status()
        items = resp.json().get("data", [])
        if not items:
            return None
        t = items[0]
        return Track(
            id=str(t["id"]),
            title=t["title"],
            artist=t["artist"]["name"],
            album=t["album"]["title"] if t.get("album") else None,
            duration_ms=t.get("duration", 0) * 1000,
            isrc=t.get("isrc"),
            uri=f"deezer://track/{t['id']}",
        )

    # ── Public interface ─────────────────────────────────────────

    def get_playlists(self) -> list[Playlist]:
        if self.client:
            playlists: list[Playlist] = []
            for dz_playlist in self.client.get_user_playlists():
                playlists.append(self._to_model(dz_playlist, load_tracks=False))
            return playlists
        user_data = self._gw("deezer.getUserData")
        user_id = user_data["USER"]["USER_ID"]
        result = self._gw("deezer.pageProfile", {"USER_ID": user_id, "tab": "playlists", "nb": 100})
        return [self._arl_playlist(item) for item in result.get("TAB", {}).get("playlists", {}).get("data", [])]

    def get_playlist(self, playlist_id: str, load_tracks: bool = True) -> Playlist:
        if self.client:
            dz_playlist = self.client.get_playlist(int(playlist_id))
            return self._to_model(dz_playlist, load_tracks=True)
        pl_metadata = self._gw("deezer.pagePlaylist", {"PLAYLIST_ID": int(playlist_id), "lang": "en", "header": True, "tab": 0})
        tracks: list[Track] = []
        if load_tracks:
            pl_tracks = self._gw("playlist.getSongs", {"PLAYLIST_ID": int(playlist_id), "nb": -1})
            track_data = pl_tracks["data"] if isinstance(pl_tracks, dict) and "data" in pl_tracks else pl_tracks if isinstance(pl_tracks, list) else []
            tracks = [Track.from_deezer_gw(t) for t in track_data]
        data = pl_metadata.get("DATA", {})
        return Playlist(
            id=str(data.get("PLAYLIST_ID", playlist_id)),
            name=data.get("TITLE", ""),
            description=data.get("DESCRIPTION"),
            tracks=tracks,
            owner=str(data.get("PARENT_USER_ID", "")),
            public=data.get("STATUS", 0) == 0,
            source=self.name,
        )

    def search_track(self, title: str, artist: str) -> Optional[Track]:
        if self.client:
            query = f"{artist} {title}"
            results = self.client.search(query)
            if results:
                track = results[0]
                return Track(
                    id=str(track.id),
                    title=track.title,
                    artist=track.artist.name,
                    album=track.album.title if track.album else None,
                    duration_ms=track.duration * 1000 if track.duration else None,
                    uri=f"deezer://track/{track.id}",
                )
            return None
        return self._public_search(title, artist)

    # ── Model mapping (deezer-python) ────────────────────────────

    def _to_model(self, dz_playlist: deezer.Playlist, load_tracks: bool = False) -> Playlist:
        tracks: list[Track] = []
        if load_tracks:
            for dz_track in dz_playlist.tracks:
                if dz_track:
                    tracks.append(
                        Track(
                            id=str(dz_track.id),
                            title=dz_track.title,
                            artist=dz_track.artist.name,
                            album=dz_track.album.title if dz_track.album else None,
                            duration_ms=dz_track.duration * 1000 if dz_track.duration else None,
                            uri=f"deezer://track/{dz_track.id}",
                        )
                    )

        return Playlist(
            id=str(dz_playlist.id),
            name=dz_playlist.title,
            description=dz_playlist.description,
            tracks=tracks,
            owner=dz_playlist.creator.name if dz_playlist.creator else None,
            public=dz_playlist.public,
            source=self.name,
            source_url=dz_playlist.link,
        )

    @staticmethod
    def playlist_id_from_url(url: str) -> Optional[str]:
        m = re.search(r"(?:deezer\.com/playlist/|deezer:playlist:)(\d+)", url)
        return m.group(1) if m else None

    # get_playlist_by_url se hereda de Provider.

    # ── Auth helpers ─────────────────────────────────────────────

    @classmethod
    def from_arl(cls, arl: str) -> DeezerProvider:
        return cls(arl=arl)

    @classmethod
    def login(cls, email: str, password: str, auto_save: bool = False) -> str:
        session = make_session(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        resp = session.get("https://www.deezer.com/login", timeout=15)
        hash_match = re.search(r'"checkForm"\s*:\s*"([^"]+)"', resp.text)

        payload = {
            "api_version": "1.0",
            "api_token": "null",
            "input": {"email": email, "password": password},
            "method": "deezer.loginDeezer",
        }
        if hash_match:
            payload["input"]["hash"] = hash_match.group(1)

        resp = session.post(f"{GW_URL}?method=deezer.loginDeezer", json=payload, timeout=15)
        data = resp.json()
        if data.get("error"):
            raise AuthError(
                f"Error al iniciar sesión: {data['error']}. "
                "Si Deezer pide CAPTCHA, obtén el ARL manualmente:\n"
                + DeezerProvider.get_arl_instructions()
            )

        arl = session.cookies.get("arl")
        if not arl:
            raise AuthError(
                "No se pudo obtener el ARL automáticamente. "
                "Intenta obtenerlo manualmente:\n"
                + DeezerProvider.get_arl_instructions()
            )

        if auto_save:
            from dotenv import set_key
            set_key(".env", "DEEZER_ARL", arl)
            logger.info("ARL de Deezer guardado en .env")

        return arl

    @staticmethod
    def get_arl_instructions() -> str:
        return (
            "Para obtener tu ARL:\n"
            "1. Abre https://www.deezer.com en Chrome/Firefox/Edge e inicia sesión\n"
            "2. Abre DevTools (F12) → Application (Chrome) o Storage (Firefox)\n"
            "3. Ve a Cookies → https://www.deezer.com\n"
            "4. Copia el valor de la cookie 'arl'\n"
            "5. Ponlo en tu .env como DEEZER_ARL=tu_arl"
        )

    @staticmethod
    def authenticate(
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        auto_save: bool = False,
    ) -> str:
        cfg = DeezerConfig.from_env()
        app_id = app_id or cfg.app_id
        app_secret = app_secret or cfg.app_secret
        redirect_uri = redirect_uri or cfg.redirect_uri
        perms = "basic_access,manage_library"

        params = urllib.parse.urlencode({
            "app_id": app_id,
            "redirect_uri": redirect_uri,
            "perms": perms,
        })
        auth_url = f"https://connect.deezer.com/oauth/auth.php?{params}"
        print(f"Abre esta URL en tu navegador para autorizar:\n{auth_url}")
        webbrowser.open(auth_url)

        response_url = input("Pega la URL completa a la que fuiste redirigido: ").strip()
        parsed = urllib.parse.urlparse(response_url)
        query_params = urllib.parse.parse_qs(parsed.query)
        code = query_params.get("code", [None])[0]
        if not code:
            raise AuthError("No se encontró el código de autorización en la URL.")

        token_params = urllib.parse.urlencode({
            "app_id": app_id,
            "secret": app_secret,
            "code": code,
        })
        resp = requests.get(f"https://connect.deezer.com/oauth/access_token.php?{token_params}")
        resp.raise_for_status()
        token_data = urllib.parse.parse_qs(resp.text)
        access_token = token_data.get("access_token", [None])[0]
        if not access_token:
            raise AuthError(f"Error obteniendo token: {resp.text}")

        if auto_save:
            from dotenv import set_key
            set_key(".env", "DEEZER_ACCESS_TOKEN", access_token)
            logger.info("Token de Deezer guardado en .env")

        return access_token
