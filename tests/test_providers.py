from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from gestor_listas.model import Playlist, Track
from gestor_listas.providers.deezer import DeezerProvider
from gestor_listas.providers.spotify import SpotifyProvider, _track_from_sp_item


class FakeDeezerTrack:
    def __init__(self, id: int, title: str, artist_name: str, album_title: str, duration: int):
        self.id = id
        self.title = title
        self.artist = MagicMock(name=artist_name)
        self.album = MagicMock(title=album_title)
        self.duration = duration


class FakeDeezerPlaylist:
    def __init__(self, id: int, title: str, description: str, creator_name: str, public: bool, link: str, tracks: list):
        self.id = id
        self.title = title
        self.description = description
        self.creator = MagicMock(name=creator_name)
        self.public = public
        self.link = link
        self.tracks = tracks


class TestSpotifyProvider:
    def test_search_track_found(self) -> None:
        provider = SpotifyProvider(use_client_credentials=True)
        provider._token = "fake_token"
        provider._token_expires = float("inf")
        provider._api_get = MagicMock(return_value={
            "tracks": {
                "items": [
                    {
                        "id": "sp1",
                        "name": "Test Song",
                        "artists": [{"name": "Test Artist"}],
                        "album": {"name": "Test Album"},
                        "duration_ms": 200000,
                        "external_ids": {"isrc": "TEST123"},
                        "uri": "spotify:track:sp1",
                    }
                ]
            }
        })

        result = provider.search_track("Test Song", "Test Artist")

        assert result is not None
        assert result.id == "sp1"
        assert result.title == "Test Song"
        assert result.artist == "Test Artist"
        assert result.album == "Test Album"
        assert result.duration_ms == 200000
        assert result.isrc == "TEST123"
        assert result.uri == "spotify:track:sp1"

    def test_search_track_not_found(self) -> None:
        provider = SpotifyProvider(use_client_credentials=True)
        provider._token = "fake_token"
        provider._token_expires = float("inf")
        provider._api_get = MagicMock(return_value={"tracks": {"items": []}})

        result = provider.search_track("Nonexistent", "Nobody")
        assert result is None

    def test_get_playlists(self) -> None:
        provider = SpotifyProvider(use_client_credentials=True)
        provider._token = "fake_token"
        provider._token_expires = float("inf")
        provider._api_get = MagicMock(return_value={
            "items": [
                {
                    "id": "pl1",
                    "name": "Rock",
                    "description": "Rock hits",
                    "owner": {"display_name": "me"},
                    "public": True,
                    "external_urls": {"spotify": "https://spotify.com/pl1"},
                }
            ],
            "next": None,
        })

        playlists = provider.get_playlists()
        assert len(playlists) == 1
        assert playlists[0].name == "Rock"
        assert playlists[0].source == "spotify"

    def test_get_playlist(self) -> None:
        provider = SpotifyProvider(use_client_credentials=True)
        provider._token = "fake_token"
        provider._token_expires = float("inf")

        provider._api_get = MagicMock(return_value={
            "id": "pl1",
            "name": "Rock Classics",
            "description": "The best rock songs",
            "owner": {"display_name": "Spotify"},
            "public": True,
            "external_urls": {"spotify": "https://open.spotify.com/playlist/pl1"},
        })
        provider._api_get_paginated = MagicMock(return_value=[
            {
                "track": {
                    "id": "tr1",
                    "name": "Bohemian Rhapsody",
                    "artists": [{"name": "Queen"}],
                    "album": {"name": "A Night at the Opera"},
                    "duration_ms": 354000,
                    "external_ids": {"isrc": "GBUM71029604"},
                    "uri": "spotify:track:tr1",
                }
            }
        ])

        result = provider.get_playlist("pl1")
        assert result.id == "pl1"
        assert result.name == "Rock Classics"
        assert result.track_count == 1
        assert result.tracks[0].artist == "Queen"

    def test_create_playlist(self) -> None:
        provider = SpotifyProvider(use_client_credentials=True)
        provider._token = "fake_token"
        provider._token_expires = float("inf")

        provider._api_get = MagicMock(return_value={"id": "user1"})
        provider._api_post = MagicMock(return_value={
            "id": "new_pl",
            "name": "New Playlist",
            "description": "desc",
            "owner": {"display_name": "me"},
            "public": False,
            "external_urls": {"spotify": "https://spotify.com/new_pl"},
        })

        result = provider.create_playlist("New Playlist", "desc")
        assert result.id == "new_pl"
        assert result.name == "New Playlist"
        assert result.track_count == 0

    def test_add_tracks_to_playlist(self) -> None:
        provider = SpotifyProvider(use_client_credentials=True)
        provider._token = "fake_token"
        provider._token_expires = float("inf")
        provider._api_post = MagicMock()

        provider.add_tracks_to_playlist("pl1", ["spotify:track:tr1"])
        provider._api_post.assert_called_once_with(
            "/playlists/pl1/tracks",
            {"uris": ["spotify:track:tr1"]},
        )

    def test_playlist_id_from_url_standard(self) -> None:
        url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        assert SpotifyProvider.playlist_id_from_url(url) == "37i9dQZF1DXcBWIGoYBM5M"

    def test_playlist_id_from_url_uri(self) -> None:
        url = "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M"
        assert SpotifyProvider.playlist_id_from_url(url) == "37i9dQZF1DXcBWIGoYBM5M"

    def test_playlist_id_from_url_with_params(self) -> None:
        url = "https://open.spotify.com/playlist/7jiU8AY3wG8kAHiWrSqEQL?si=5f333b2b75b548c7"

        assert SpotifyProvider.playlist_id_from_url(url) == "7jiU8AY3wG8kAHiWrSqEQL"
    def test_playlist_id_from_url_invalid(self) -> None:
        assert SpotifyProvider.playlist_id_from_url("https://example.com") is None

    def test_get_playlist_by_url(self) -> None:
        provider = SpotifyProvider(use_client_credentials=True)
        provider._token = "fake_token"
        provider._token_expires = float("inf")
        provider.get_playlist = MagicMock(return_value=Playlist(
            id="abc123", name="Test", source="spotify"
        ))

        result = provider.get_playlist_by_url("https://open.spotify.com/playlist/abc123")
        assert result.id == "abc123"
        assert result.name == "Test"

    def test_get_playlist_by_url_invalid(self) -> None:
        provider = SpotifyProvider(use_client_credentials=True)
        with pytest.raises(ValueError, match="No se pudo extraer el ID"):
            provider.get_playlist_by_url("not-a-url")

    def test_scraping_search_track(self) -> None:
        provider = SpotifyProvider(use_scraping=True)
        provider._search_track_scraping = MagicMock(return_value=Track(
            id="sp1", title="Test", artist="Artist"
        ))
        result = provider.search_track("Test", "Artist")
        assert result is not None
        assert result.id == "sp1"

    def test_scraping_get_playlist(self) -> None:
        provider = SpotifyProvider(use_scraping=True)
        provider._get_playlist_scraping = MagicMock(return_value=Playlist(
            id="pl1", name="Scraped", tracks=[Track(id="tr1", title="Song", artist="Singer")],
            source="spotify",
        ))
        result = provider.get_playlist("pl1")
        assert result.id == "pl1"
        assert result.name == "Scraped"
        assert result.track_count == 1

    def test_scraping_create_playlist_raises(self) -> None:
        provider = SpotifyProvider(use_scraping=True)
        with pytest.raises(NotImplementedError):
            provider.create_playlist("test")

    def test_scraping_add_tracks_raises(self) -> None:
        provider = SpotifyProvider(use_scraping=True)
        with pytest.raises(NotImplementedError):
            provider.add_tracks_to_playlist("pl1", ["uri"])

    def test_scraping_get_playlists_raises(self) -> None:
        provider = SpotifyProvider(use_scraping=True)
        with pytest.raises(NotImplementedError):
            provider.get_playlists()

    def test_track_from_sp_item_with_track_key(self) -> None:
        item = {
            "track": {
                "id": "tr1",
                "name": "Test Song",
                "artists": [{"name": "Artist"}],
                "album": {"name": "Album"},
                "duration_ms": 200000,
                "external_ids": {"isrc": "TEST123"},
                "uri": "spotify:track:tr1",
            }
        }
        t = _track_from_sp_item(item)
        assert t is not None
        assert t.id == "tr1"
        assert t.artist == "Artist"

    def test_track_from_sp_item_direct(self) -> None:
        item = {
            "id": "tr1",
            "name": "Test Song",
            "artists": [{"name": "Artist"}],
        }
        t = _track_from_sp_item(item)
        assert t is not None
        assert t.id == "tr1"

    def test_track_from_sp_item_none(self) -> None:
        assert _track_from_sp_item({}) is None
        assert _track_from_sp_item({"track": {}}) is None


class TestDeezerProvider:
    def test_search_track_found(self, mocker) -> None:
        fake_track = MagicMock()
        fake_track.id = 123
        fake_track.title = "Deezer Song"
        fake_track.artist.name = "Deezer Artist"
        fake_track.album.title = "Deezer Album"
        fake_track.duration = 210

        mock_client = MagicMock()
        mock_client.search.return_value = [fake_track]

        provider = DeezerProvider(access_token="token")
        provider.client = mock_client

        result = provider.search_track("Deezer Song", "Deezer Artist")
        assert result is not None
        assert result.id == "123"
        assert result.title == "Deezer Song"
        assert result.artist == "Deezer Artist"
        assert result.album == "Deezer Album"
        assert result.duration_ms == 210000

    def test_search_track_not_found(self, mocker) -> None:
        mock_client = MagicMock()
        mock_client.search.return_value = []

        provider = DeezerProvider(access_token="token")
        provider.client = mock_client

        result = provider.search_track("Nonexistent", "Nobody")
        assert result is None

    def test_get_playlist(self, mocker) -> None:
        fake_track = MagicMock()
        fake_track.id = 456
        fake_track.title = "Deezer Track"
        fake_track.artist.name = "Deezer Artist"
        fake_track.album.title = "Deezer Album"
        fake_track.duration = 180

        fake_playlist = MagicMock()
        fake_playlist.id = 999
        fake_playlist.title = "My Deezer Playlist"
        fake_playlist.description = "desc"
        fake_playlist.creator.name = "me"
        fake_playlist.public = True
        fake_playlist.link = "https://deezer.com/playlist/999"
        fake_playlist.tracks = [fake_track]

        mock_client = MagicMock()
        mock_client.get_playlist.return_value = fake_playlist

        provider = DeezerProvider(access_token="token")
        provider.client = mock_client

        result = provider.get_playlist("999")
        assert result.id == "999"
        assert result.name == "My Deezer Playlist"
        assert result.track_count == 1
        assert result.tracks[0].artist == "Deezer Artist"
