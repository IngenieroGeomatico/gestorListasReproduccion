from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from .model import Playlist
from .providers.deezer import DeezerProvider
from .providers.spotify import SpotifyProvider
from .providers.youtube import YouTubeProvider
from .storage import Storage

logger = logging.getLogger(__name__)


def get_sources_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "sources.json"


def load_sources(path: Optional[Path] = None) -> dict:
    sources_file = path or get_sources_path()
    if not sources_file.exists():
        return {"spotify": [], "deezer": [], "youtube": []}
    with open(sources_file, encoding="utf-8") as f:
        return json.load(f)


def _fetch_all(
    keys: list,
    fetch: "Callable",
    label: str,
    max_workers: int,
) -> list[Playlist]:
    """Descarga en paralelo aislando fallos; devuelve las playlists obtenidas.

    Las escrituras en SQLite NO se hacen aquí (la conexión no es thread-safe):
    solo se paraleliza la parte de red (I/O-bound).
    """
    def _safe_fetch(key):
        try:
            return fetch(key)
        except Exception as exc:  # noqa: BLE001 - queremos continuar con el resto
            logger.warning("[%s] Error al importar %s: %s", label, key, exc)
            return None

    if max_workers > 1 and len(keys) > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            fetched = list(pool.map(_safe_fetch, keys))
    else:
        fetched = [_safe_fetch(k) for k in keys]
    return [pl for pl in fetched if pl is not None]


def _import_urls(
    urls: list[str],
    storage: Storage,
    fetch: "Callable[[str], Playlist]",
    label: str,
    max_workers: int = 1,
) -> list[Playlist]:
    """Importa cada URL de forma aislada: un fallo no aborta el resto."""
    imported = _fetch_all(urls, fetch, label, max_workers)
    for pl in imported:
        storage.save_playlist(pl)
    return imported


def import_spotify_urls(urls: list[str], storage: Storage, max_workers: int = 1) -> list[Playlist]:
    if not urls:
        return []
    sp = SpotifyProvider(use_scraping=True)
    return _import_urls(urls, storage, sp.get_playlist_by_url, "spotify", max_workers)


def import_deezer_urls(urls: list[str], storage: Storage, max_workers: int = 1) -> list[Playlist]:
    if not urls:
        return []
    dz = DeezerProvider()
    return _import_urls(urls, storage, dz.get_playlist_by_url, "deezer", max_workers)


def import_deezer_all(storage: Storage, max_workers: int = 1) -> list[Playlist]:
    dz = DeezerProvider()
    playlists = dz.get_playlists()
    imported = _fetch_all([pl.id for pl in playlists], dz.get_playlist, "deezer", max_workers)
    for pl in imported:
        storage.save_playlist(pl)
    return imported


def import_youtube_urls(urls: list[str], storage: Storage, max_workers: int = 1) -> list[Playlist]:
    if not urls:
        return []
    yt = YouTubeProvider()
    return _import_urls(urls, storage, yt.get_playlist_by_url, "youtube", max_workers)


def run(path: Optional[Path] = None, max_workers: int = 1) -> dict[str, list[Playlist]]:
    sources = load_sources(path)

    result: dict[str, list[Playlist]] = {
        "spotify": [],
        "deezer": [],
        "youtube": [],
    }

    with Storage() as storage:
        spotify_urls = sources.get("spotify", [])
        if spotify_urls:
            result["spotify"] = import_spotify_urls(spotify_urls, storage, max_workers)

        deezer_urls = sources.get("deezer", [])
        if deezer_urls:
            result["deezer"] = import_deezer_urls(deezer_urls, storage, max_workers)
        else:
            result["deezer"] = import_deezer_all(storage, max_workers)

        youtube_urls = sources.get("youtube", [])
        if youtube_urls:
            result["youtube"] = import_youtube_urls(youtube_urls, storage, max_workers)

    return result
