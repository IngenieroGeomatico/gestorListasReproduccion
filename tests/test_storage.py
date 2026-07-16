from datetime import datetime

import pytest

from gestor_listas.model import Playlist, Track
from gestor_listas.storage import Storage


@pytest.fixture
def storage(tmp_path) -> Storage:
    s = Storage(db_path=tmp_path / "test.db")
    yield s
    s.close()


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

    def test_context_manager_closes_connection(self, tmp_path) -> None:
        import sqlite3

        with Storage(db_path=tmp_path / "ctx.db") as s:
            assert s.playlist_count() == 0
        # Tras salir del with, la conexión debe estar cerrada.
        with pytest.raises(sqlite3.ProgrammingError):
            s._conn.execute("SELECT 1")

    def test_context_manager_returns_self(self, tmp_path) -> None:
        s = Storage(db_path=tmp_path / "ctx2.db")
        with s as entered:
            assert entered is s
        s.close()

    def test_context_manager_closes_on_exception(self, tmp_path) -> None:
        import sqlite3

        s = Storage(db_path=tmp_path / "ctx3.db")
        with pytest.raises(ValueError):
            with s:
                raise ValueError("boom")
        with pytest.raises(sqlite3.ProgrammingError):
            s._conn.execute("SELECT 1")

    def test_track_order_preserved(self, storage: Storage) -> None:
        tracks = [
            Track(id=f"t{i}", title=f"Song {i}", artist="Artist")
            for i in range(5)
        ]
        pl = Playlist(id="ordered", name="Ordered", tracks=tracks)
        storage.save_playlist(pl)
        loaded = storage.load_playlist("ordered")
        assert loaded is not None
        assert [t.id for t in loaded.tracks] == ["t0", "t1", "t2", "t3", "t4"]

    def test_update_reorders_tracks(self, storage: Storage) -> None:
        pl = Playlist(
            id="reorder",
            name="Reorder",
            tracks=[Track(id="a", title="A", artist="X"), Track(id="b", title="B", artist="X")],
        )
        storage.save_playlist(pl)
        reordered = Playlist(
            id="reorder",
            name="Reorder",
            tracks=[Track(id="b", title="B", artist="X"), Track(id="a", title="A", artist="X")],
        )
        storage.save_playlist(reordered)
        loaded = storage.load_playlist("reorder")
        assert loaded is not None
        assert [t.id for t in loaded.tracks] == ["b", "a"]
