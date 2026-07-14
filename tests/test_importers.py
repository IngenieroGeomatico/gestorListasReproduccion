from unittest.mock import MagicMock, call

import pytest

from gestor_listas.importers.spotify import SpotifyImporter
from gestor_listas.model import Playlist, Track


class TestSpotifyImporter:
    def test_import_playlist_with_spotify_uris(self, mocker) -> None:
        mock_provider = MagicMock()
        mock_provider.create_playlist.return_value = Playlist(
            id="new_pl", name="Imported", tracks=[], source="spotify"
        )
        mock_provider.get_playlist.return_value = Playlist(
            id="new_pl", name="Imported", tracks=[], source="spotify"
        )
        mock_provider.client.playlist_add_items.return_value = None

        importer = SpotifyImporter(mock_provider)

        t1 = Track(id="t1", title="Song 1", artist="Artist 1", uri="spotify:track:t1")
        t2 = Track(id="t2", title="Song 2", artist="Artist 2", uri="spotify:track:t2")
        src = Playlist(id="src", name="Source", tracks=[t1, t2])

        result = importer.import_playlist(src)

        mock_provider.create_playlist.assert_called_once_with(
            name="Source", description="", public=False
        )
        mock_provider.client.playlist_add_items.assert_called_once_with(
            "new_pl", ["spotify:track:t1", "spotify:track:t2"]
        )

    def test_import_playlist_with_search_fallback(self, mocker) -> None:
        mock_provider = MagicMock()
        mock_provider.create_playlist.return_value = Playlist(id="new_pl", name="Imported", source="spotify")
        mock_provider.get_playlist.return_value = Playlist(id="new_pl", name="Imported", source="spotify")

        def search_side_effect(title: str, artist: str) -> Track:
            return Track(
                id=f"found_{title.lower().replace(' ', '_')}",
                title=title,
                artist=artist,
                uri=f"spotify:track:found_{title.lower().replace(' ', '_')}",
            )

        mock_provider.search_track.side_effect = search_side_effect
        mock_provider.client.playlist_add_items.return_value = None

        importer = SpotifyImporter(mock_provider)

        t1 = Track(id="t1", title="Song 1", artist="Artist 1")
        src = Playlist(id="src", name="Source", tracks=[t1])

        result = importer.import_playlist(src)

        mock_provider.create_playlist.assert_called_once()
        mock_provider.search_track.assert_called_once_with("Song 1", "Artist 1")
        mock_provider.client.playlist_add_items.assert_called_once_with(
            "new_pl", ["spotify:track:found_song_1"]
        )

    def test_import_playlist_batches_large_sets(self, mocker) -> None:
        mock_provider = MagicMock()
        mock_provider.create_playlist.return_value = Playlist(id="new_pl", name="Imported", source="spotify")
        mock_provider.get_playlist.return_value = Playlist(id="new_pl", name="Imported", source="spotify")
        mock_provider.client.playlist_add_items.return_value = None

        importer = SpotifyImporter(mock_provider)

        tracks = [
            Track(id=str(i), title=f"Song {i}", artist="Artist", uri=f"spotify:track:t{i}")
            for i in range(150)
        ]
        src = Playlist(id="src", name="Big Playlist", tracks=tracks)

        result = importer.import_playlist(src)

        assert mock_provider.client.playlist_add_items.call_count == 2
        mock_provider.client.playlist_add_items.assert_has_calls([
            call("new_pl", [f"spotify:track:t{i}" for i in range(100)]),
            call("new_pl", [f"spotify:track:t{i}" for i in range(100, 150)]),
        ])
