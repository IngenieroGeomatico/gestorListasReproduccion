from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..errors import PlaylistNotFoundError
from ..model import Playlist, Track


class Provider(ABC):
    name: str = "base"

    @abstractmethod
    def get_playlists(self) -> list[Playlist]:
        """Devuelve las playlists del usuario autenticado."""
        ...

    @abstractmethod
    def get_playlist(self, playlist_id: str) -> Playlist:
        """Devuelve una playlist (con sus tracks) por su ID."""
        ...

    @staticmethod
    @abstractmethod
    def playlist_id_from_url(url: str) -> Optional[str]:
        """Extrae el ID de playlist de una URL, o None si no se reconoce."""
        ...

    def get_playlist_by_url(self, url: str) -> Playlist:
        """Devuelve una playlist a partir de su URL."""
        pid = self.playlist_id_from_url(url)
        if not pid:
            raise PlaylistNotFoundError(f"No se pudo extraer el ID de la URL: {url}")
        return self.get_playlist(pid)

    def search_track(self, title: str, artist: str) -> Optional[Track]:
        """Busca un track por título y artista. Opcional según el proveedor."""
        raise NotImplementedError(
            f"search_track no está implementado para el proveedor '{self.name}'"
        )
