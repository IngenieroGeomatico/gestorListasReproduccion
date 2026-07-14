from __future__ import annotations

from typing import Optional

from ..model import Playlist
from ..providers.spotify import SpotifyProvider


class SpotifyImporter:
    def __init__(self, provider: SpotifyProvider) -> None:
        self.provider = provider

    def import_playlist(
        self,
        playlist: Playlist,
        name: Optional[str] = None,
        description: Optional[str] = None,
        public: bool = False,
    ) -> Playlist:
        created = self.provider.create_playlist(
            name=name or playlist.name,
            description=description or playlist.description or "",
            public=public or playlist.public,
        )

        track_uris: list[str] = []
        for track in playlist.tracks:
            if track.uri and track.uri.startswith("spotify:track:"):
                track_uris.append(track.uri)
            else:
                found = self.provider.search_track(track.title, track.artist)
                if found and found.uri:
                    track_uris.append(found.uri)

        if track_uris:
            batch_size = 100
            for i in range(0, len(track_uris), batch_size):
                batch = track_uris[i : i + batch_size]
                self.provider.client.playlist_add_items(created.id, batch)

        return self.provider.get_playlist(created.id)
