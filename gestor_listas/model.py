from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Track:
    id: str
    title: str
    artist: str
    album: Optional[str] = None
    duration_ms: Optional[int] = None
    isrc: Optional[str] = None
    uri: Optional[str] = None

    def __str__(self) -> str:
        return f"{self.artist} - {self.title}"


@dataclass
class Playlist:
    id: str
    name: str
    description: Optional[str] = None
    tracks: list[Track] = field(default_factory=list)
    owner: Optional[str] = None
    public: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    source: Optional[str] = None
    source_url: Optional[str] = None

    @property
    def track_count(self) -> int:
        return len(self.tracks)

    def add_track(self, track: Track) -> None:
        self.tracks.append(track)

    def remove_track(self, track_id: str) -> None:
        self.tracks = [t for t in self.tracks if t.id != track_id]

    def find_track(self, title: str, artist: str) -> Optional[Track]:
        for t in self.tracks:
            if t.title.lower() == title.lower() and t.artist.lower() == artist.lower():
                return t
        return None
