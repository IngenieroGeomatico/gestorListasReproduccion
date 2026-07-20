from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..model import Playlist, Track
from ..storage import Storage
from ..util import safe_filename
from .deezer import DeezerDownloader
from .youtube import YouTubeDownloader

logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    track: Track
    path: Optional[Path] = None
    source: Optional[str] = None
    error: Optional[str] = None


class DownloadManager:
    def __init__(
        self,
        output_dir: str | Path = "downloads",
        prefer: str = "deezer",
        audio_format: str = "best",
        max_workers: int = 1,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.prefer = prefer
        self.max_workers = max(1, max_workers)
        self._deezer = DeezerDownloader()
        self._youtube = YouTubeDownloader(output_format=audio_format)

    def download_track(self, track: Track, output_dir: Optional[Path] = None) -> DownloadResult:
        dest = output_dir or self.output_dir
        sources = []
        if self.prefer == "deezer":
            sources = [("deezer", self._deezer), ("youtube", self._youtube)]
        else:
            sources = [("youtube", self._youtube), ("deezer", self._deezer)]

        for name, downloader in sources:
            try:
                path = downloader.download(track, dest)
                if path:
                    return DownloadResult(track=track, path=path, source=name)
            except Exception:
                continue

        return DownloadResult(
            track=track,
            error="No se pudo descargar de ninguna fuente",
        )

    def download_playlist(
        self,
        playlist: Playlist,
        use_subfolder: bool = True,
        track_ids: Optional[set[str]] = None,
        limit: int = 0,
    ) -> list[DownloadResult]:
        dest = self.output_dir
        if use_subfolder:
            safe = safe_filename(playlist.name, max_length=64, fallback="playlist")
            dest = self.output_dir / safe
            dest.mkdir(parents=True, exist_ok=True)

        tracks = playlist.tracks
        if track_ids is not None:
            tracks = [t for t in tracks if t.id in track_ids]
        if limit > 0:
            tracks = tracks[:limit]

        total = len(tracks)

        def _download_one(item: tuple[int, Track]) -> DownloadResult:
            i, track = item
            logger.info("[%d/%d] %s - %s", i, total, track.artist, track.title)
            result = self.download_track(track, output_dir=dest)
            if result.path:
                logger.info("OK: %s", result.path.name)
            else:
                logger.warning("Error: %s", result.error or "desconocido")
            return result

        enumerated = list(enumerate(tracks, 1))
        if self.max_workers > 1:
            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                # Preserva el orden de las pistas en los resultados.
                return list(pool.map(_download_one, enumerated))
        return [_download_one(item) for item in enumerated]

    def download_from_storage(
        self,
        playlist_id: Optional[str] = None,
        source: Optional[str] = None,
        use_subfolder: bool = True,
        track_ids: Optional[set[str]] = None,
        limit: int = 0,
    ) -> list[DownloadResult]:
        with Storage() as storage:
            if playlist_id:
                pl = storage.load_playlist(playlist_id)
                if not pl:
                    return []
                return self.download_playlist(pl, use_subfolder=use_subfolder, track_ids=track_ids, limit=limit)

            playlists = (
                storage.load_playlists_by_source(source)
                if source
                else storage.load_all_playlists()
            )

        results: list[DownloadResult] = []
        for pl in playlists:
            results.extend(self.download_playlist(pl, use_subfolder=use_subfolder, track_ids=track_ids, limit=limit))
        return results
