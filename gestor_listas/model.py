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

    @classmethod
    def from_deezer_gw(cls, data: dict) -> "Track":
        """Construye un Track desde un item de la API interna de Deezer (gw-light).

        Los campos vienen en MAYÚSCULAS (SNG_ID, SNG_TITLE, ART_NAME...) y las
        duraciones en segundos.
        """
        sng_id = data["SNG_ID"]
        duration = data.get("DURATION", 0)
        return cls(
            id=str(sng_id),
            title=data.get("SNG_TITLE", ""),
            artist=data.get("ART_NAME", ""),
            album=data.get("ALB_TITLE"),
            duration_ms=duration * 1000 if duration else 0,
            uri=f"deezer://track/{sng_id}",
        )

    @classmethod
    def from_spotify_item(cls, item: dict) -> Optional["Track"]:
        """Construye un Track desde un item de la Web API de Spotify.

        Acepta tanto el objeto track directo como el envoltorio {'track': {...}}
        que devuelven los endpoints de playlist. Devuelve None si el item no es
        un track válido (p. ej. episodios o pistas locales sin id).
        """
        t = item.get("track") or item
        if not t or not t.get("id"):
            return None
        external_ids = t.get("external_ids")
        isrc = external_ids.get("isrc") if isinstance(external_ids, dict) else None
        return cls(
            id=t["id"],
            title=t["name"],
            artist=t["artists"][0]["name"] if t.get("artists") else "Unknown",
            album=t["album"]["name"] if t.get("album") else None,
            duration_ms=t.get("duration_ms"),
            isrc=isrc,
            uri=t.get("uri"),
        )


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
