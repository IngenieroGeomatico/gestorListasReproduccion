from __future__ import annotations

from abc import ABC, abstractmethod

from ..model import Playlist


class Provider(ABC):
    name: str = "base"

    @abstractmethod
    def get_playlists(self) -> list[Playlist]:
        ...

    @abstractmethod
    def get_playlist(self, playlist_id: str) -> Playlist:
        ...
