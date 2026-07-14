from datetime import datetime

import pytest

from gestor_listas.model import Playlist, Track
from gestor_listas.storage import Storage


@pytest.fixture
def storage(tmp_path) -> Storage:
    return Storage(db_path=tmp_path / "test.db")


class TestStorage:
    def test_save_and_load_playlist(self, storage: Storage, sample_playlist: Playlist) -> None:
        storage.save_playlist(sample_playlist)
        loaded = storage.load_playlist("pl1")
        assert loaded is not None
        assert loaded.id == "pl1"
        assert loaded.name == "Classic Rock"
        assert loaded.track_count == 2
        assert loaded.tracks[0].title == "Bohemian Rhapsody"
        assert loaded.tracks[1].artist == "Led Zeppelin"
        assert loaded.source == "manual"

    def test_load_nonexistent(self, storage: Storage) -> None:
        assert storage.load_playlist("nonexistent") is None

    def test_load_all_playlists(self, storage: Storage, sample_playlist: Playlist) -> None:
        pl2 = Playlist(id="pl2", name="Jazz", tracks=[], source="deezer")
        storage.save_playlist(sample_playlist)
        storage.save_playlist(pl2)
        all_pl = storage.load_all_playlists()
        assert len(all_pl) == 2
        assert all_pl[0].name == "Classic Rock"
        assert all_pl[1].name == "Jazz"

    def test_load_by_source(self, storage: Storage, sample_playlist: Playlist) -> None:
        pl2 = Playlist(id="pl2", name="Jazz", tracks=[], source="deezer")
        storage.save_playlist(sample_playlist)
        storage.save_playlist(pl2)
        spotify = storage.load_playlists_by_source("manual")
        assert len(spotify) == 1
        assert spotify[0].id == "pl1"

    def test_delete_playlist(self, storage: Storage, sample_playlist: Playlist) -> None:
        storage.save_playlist(sample_playlist)
        assert storage.playlist_count() == 1
        storage.delete_playlist("pl1")
        assert storage.load_playlist("pl1") is None
        assert storage.playlist_count() == 0
        assert storage.track_count() == 0

    def test_update_existing_playlist(self, storage: Storage, sample_playlist: Playlist) -> None:
        storage.save_playlist(sample_playlist)
        updated = Playlist(
            id="pl1",
            name="Classic Rock Updated",
            description=sample_playlist.description,
            tracks=[sample_playlist.tracks[0]],
            owner=sample_playlist.owner,
            source=sample_playlist.source,
        )
        storage.save_playlist(updated)
        loaded = storage.load_playlist("pl1")
        assert loaded is not None
        assert loaded.name == "Classic Rock Updated"
        assert loaded.track_count == 1

    def test_playlist_without_tracks(self, storage: Storage) -> None:
        pl = Playlist(id="empty", name="Empty List", source="spotify")
        storage.save_playlist(pl)
        loaded = storage.load_playlist("empty")
        assert loaded is not None
        assert loaded.track_count == 0

    def test_track_count_filtered(self, storage: Storage, sample_playlist: Playlist) -> None:
        storage.save_playlist(sample_playlist)
        assert storage.track_count("pl1") == 2
        assert storage.track_count("nonexistent") == 0

    def test_multiple_playlists_independent_tracks(self, storage: Storage, sample_playlist: Playlist, sample_track_1: Track) -> None:
        pl2 = Playlist(id="pl2", name="Single", tracks=[sample_track_1])
        storage.save_playlist(sample_playlist)
        storage.save_playlist(pl2)
        assert storage.track_count("pl1") == 2
        assert storage.track_count("pl2") == 1
        assert storage.track_count() == 3

    def test_default_db_path(self) -> None:
        s = Storage(db_path=":memory:")
        assert s.playlist_count() == 0
        s.close()
