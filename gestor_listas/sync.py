from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from .model import Playlist
from .providers.deezer import DeezerProvider
from .providers.spotify import SpotifyProvider
from .providers.youtube import YouTubeProvider
from .storage import Storage


def get_sources_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "sources.json"


def load_sources(path: Optional[Path] = None) -> dict:
    sources_file = path or get_sources_path()
    if not sources_file.exists():
        return {"spotify": [], "deezer": [], "youtube": []}
    with open(sources_file, encoding="utf-8") as f:
        return json.load(f)


def _import_urls(
    urls: list[str],
    storage: Storage,
    fetch: "Callable[[str], Playlist]",
    label: str,
) -> list[Playlist]:
    """Importa cada URL de forma aislada: un fallo no aborta el resto."""
    imported: list[Playlist] = []
    for url in urls:
        try:
            pl = fetch(url)
            storage.save_playlist(pl)
            imported.append(pl)
        except Exception as exc:  # noqa: BLE001 - queremos continuar con el resto
            print(f"  [{label}] Error al importar {url}: {exc}")
    return imported


def import_spotify_urls(urls: list[str], storage: Storage) -> list[Playlist]:
    if not urls:
        return []
    sp = SpotifyProvider(use_scraping=True)
    return _import_urls(urls, storage, sp.get_playlist_by_url, "spotify")


def import_deezer_urls(urls: list[str], storage: Storage) -> list[Playlist]:
    if not urls:
        return []
    dz = DeezerProvider()
    return _import_urls(urls, storage, dz.get_playlist_by_url, "deezer")


def import_deezer_all(storage: Storage) -> list[Playlist]:
    dz = DeezerProvider()
    playlists = dz.get_playlists()
    imported: list[Playlist] = []
    for pl in playlists:
        try:
            full = dz.get_playlist(pl.id)
            storage.save_playlist(full)
            imported.append(full)
        except Exception as exc:  # noqa: BLE001 - continuar con el resto
            print(f"  [deezer] Error al importar {pl.id}: {exc}")
    return imported


def import_youtube_urls(urls: list[str], storage: Storage) -> list[Playlist]:
    if not urls:
        return []
    yt = YouTubeProvider()
    return _import_urls(urls, storage, yt.get_playlist_by_url, "youtube")


def run(path: Optional[Path] = None) -> dict[str, list[Playlist]]:
    sources = load_sources(path)

    result: dict[str, list[Playlist]] = {
        "spotify": [],
        "deezer": [],
        "youtube": [],
    }

    with Storage() as storage:
        spotify_urls = sources.get("spotify", [])
        if spotify_urls:
            result["spotify"] = import_spotify_urls(spotify_urls, storage)

        deezer_urls = sources.get("deezer", [])
        if deezer_urls:
            result["deezer"] = import_deezer_urls(deezer_urls, storage)
        else:
            result["deezer"] = import_deezer_all(storage)

        youtube_urls = sources.get("youtube", [])
        if youtube_urls:
            result["youtube"] = import_youtube_urls(youtube_urls, storage)

    return result
