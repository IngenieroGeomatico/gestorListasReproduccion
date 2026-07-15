from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Optional

from ..model import Playlist, Track
from .base import Provider


PLAYLIST_URL_RE = re.compile(
    r"(?:youtube\.com/playlist\?.*list=|youtu\.be/|youtube\.com/watch\?.*v=)([a-zA-Z0-9_-]+)"
)


class YouTubeProvider(Provider):
    name = "youtube"

    def __init__(self) -> None:
        self._yt_dlp_checked = False

    def _ensure_yt_dlp(self) -> None:
        if self._yt_dlp_checked:
            return
        try:
            subprocess.run(["yt-dlp", "--version"], capture_output=True, timeout=10)
        except FileNotFoundError:
            raise RuntimeError("yt-dlp no está instalado. Ejecuta: pip install yt-dlp")
        self._yt_dlp_checked = True

    def get_playlists(self, channel: Optional[str] = None) -> list[Playlist]:
        raise NotImplementedError(
            "La lectura por canal ya no está disponible. "
            "Usa URLs de playlist en sources.json."
        )

    def get_playlist(self, playlist_id: str) -> Playlist:
        url = f"https://www.youtube.com/playlist?list={playlist_id}"
        return self.get_playlist_by_url(url)

    def get_playlist_by_url(self, url: str) -> Playlist:
        self._ensure_yt_dlp()
        pid = self.playlist_id_from_url(url)
        if not pid:
            raise ValueError(f"No se pudo extraer el ID de la URL: {url}")

        result = subprocess.run(
            [
                "yt-dlp",
                "--flat-playlist",
                "--dump-single-json",
                "--no-download",
                "--skip-download",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or "Error desconocido"
            raise RuntimeError(f"Error al obtener playlist de YouTube: {error_msg}")

        data = json.loads(result.stdout)

        entries = data.get("entries", [])
        tracks: list[Track] = []
        for entry in entries:
            video_id = entry.get("id", "")
            title = entry.get("title", "")
            uploader = entry.get("uploader", entry.get("channel", ""))
            duration = entry.get("duration")

            if not video_id or not title:
                continue

            tracks.append(Track(
                id=video_id,
                title=title,
                artist=uploader,
                duration_ms=int(duration * 1000) if duration else None,
                uri=f"https://www.youtube.com/watch?v={video_id}",
            ))

        return Playlist(
            id=pid,
            name=data.get("title", ""),
            description=data.get("description"),
            tracks=tracks,
            owner=data.get("uploader", data.get("channel")),
            source=self.name,
            source_url=url,
        )

    def search_track(self, title: str, artist: str) -> Optional[Track]:
        self._ensure_yt_dlp()
        query = f"{artist} - {title}"
        result = subprocess.run(
            [
                "yt-dlp",
                "--flat-playlist",
                "--dump-single-json",
                "--no-download",
                "--skip-download",
                "--default-search", "ytsearch",
                f"ytsearch1:{query}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return None

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

        entries = data.get("entries", [])
        if not entries:
            return None

        entry = entries[0]
        video_id = entry.get("id", "")
        if not video_id:
            return None

        return Track(
            id=video_id,
            title=entry.get("title", title),
            artist=entry.get("uploader", entry.get("channel", artist)),
            duration_ms=int(entry["duration"] * 1000) if entry.get("duration") else None,
            uri=f"https://www.youtube.com/watch?v={video_id}",
        )

    @staticmethod
    def playlist_id_from_url(url: str) -> Optional[str]:
        m = PLAYLIST_URL_RE.search(url)
        return m.group(1) if m else None
