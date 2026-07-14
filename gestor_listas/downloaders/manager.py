from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..model import Playlist, Track
from ..storage import Storage
from .deezer import DeezerDownloader
from .youtube import YouTubeDownloader


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
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.prefer = prefer
        self._deezer = DeezerDownloader()
        self._youtube = YouTubeDownloader()
        self._storage = Storage()

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
    ) -> list[DownloadResult]:
        dest = self.output_dir
        if use_subfolder:
            safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in playlist.name).strip()
            safe = safe[:64]
            dest = self.output_dir / safe
            dest.mkdir(parents=True, exist_ok=True)

        results: list[DownloadResult] = []
        for track in playlist.tracks:
            if track_ids is not None and track.id not in track_ids:
                continue
            result = self.download_track(track, output_dir=dest)
            results.append(result)
        return results

    def download_from_storage(
        self,
        playlist_id: Optional[str] = None,
        source: Optional[str] = None,
        use_subfolder: bool = True,
        track_ids: Optional[set[str]] = None,
    ) -> list[DownloadResult]:
        if playlist_id:
            pl = self._storage.load_playlist(playlist_id)
            if not pl:
                return []
            return self.download_playlist(pl, use_subfolder=use_subfolder, track_ids=track_ids)

        playlists = (
            self._storage.load_playlists_by_source(source)
            if source
            else self._storage.load_all_playlists()
        )
        results: list[DownloadResult] = []
        for pl in playlists:
            results.extend(self.download_playlist(pl, use_subfolder=use_subfolder, track_ids=track_ids))
        return results
