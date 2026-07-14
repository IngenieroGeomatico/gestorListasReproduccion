from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .model import Playlist
from .providers.deezer import DeezerProvider
from .providers.spotify import SpotifyProvider
from .storage import Storage


def get_sources_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "sources.json"


def load_sources(path: Optional[Path] = None) -> dict:
    sources_file = path or get_sources_path()
    if not sources_file.exists():
        return {"spotify": [], "deezer": []}
    with open(sources_file) as f:
        return json.load(f)


def import_spotify_urls(urls: list[str], storage: Storage) -> list[Playlist]:
    if not urls:
        return []
    sp = SpotifyProvider(use_scraping=True)
    imported: list[Playlist] = []
    for url in urls:
        pl = sp.get_playlist_by_url(url)
        storage.save_playlist(pl)
        imported.append(pl)
    return imported


def import_deezer_urls(urls: list[str], storage: Storage) -> list[Playlist]:
    if not urls:
        return []
    dz = DeezerProvider()
    imported: list[Playlist] = []
    for url in urls:
        pl = dz.get_playlist_by_url(url)
        storage.save_playlist(pl)
        imported.append(pl)
    return imported


def import_deezer_all(storage: Storage) -> list[Playlist]:
    dz = DeezerProvider()
    playlists = dz.get_playlists()
    for pl in playlists:
        full = dz.get_playlist(pl.id)
        storage.save_playlist(full)
    return playlists


def run(path: Optional[Path] = None) -> dict[str, list[Playlist]]:
    sources = load_sources(path)
    storage = Storage()

    result: dict[str, list[Playlist]] = {
        "spotify": [],
        "deezer": [],
    }

    spotify_urls = sources.get("spotify", [])
    if spotify_urls:
        result["spotify"] = import_spotify_urls(spotify_urls, storage)

    deezer_urls = sources.get("deezer", [])
    if deezer_urls:
        result["deezer"] = import_deezer_urls(deezer_urls, storage)
    else:
        result["deezer"] = import_deezer_all(storage)

    storage.close()
    return result
