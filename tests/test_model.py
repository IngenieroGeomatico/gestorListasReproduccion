from gestor_listas.model import Playlist, Track


class TestTrack:
    def test_str(self) -> None:
        t = Track(id="1", title="Song", artist="Artist")
        assert str(t) == "Artist - Song"

    def test_defaults(self) -> None:
        t = Track(id="1", title="Song", artist="Artist")
        assert t.album is None
        assert t.duration_ms is None
        assert t.isrc is None
        assert t.uri is None


class TestPlaylist:
    def test_track_count(self, sample_playlist: Playlist) -> None:
        assert sample_playlist.track_count == 2

    def test_empty_track_count(self) -> None:
        pl = Playlist(id="e", name="Empty")
        assert pl.track_count == 0

    def test_add_track(self, sample_playlist: Playlist, sample_track_1: Track) -> None:
        count_before = sample_playlist.track_count
        sample_playlist.add_track(sample_track_1)
        assert sample_playlist.track_count == count_before + 1

    def test_remove_track(self, sample_playlist: Playlist) -> None:
        sample_playlist.remove_track("tr1")
        assert sample_playlist.track_count == 1
        assert all(t.id != "tr1" for t in sample_playlist.tracks)

    def test_remove_nonexistent(self, sample_playlist: Playlist) -> None:
        sample_playlist.remove_track("nonexistent")
        assert sample_playlist.track_count == 2

    def test_find_track(self, sample_playlist: Playlist) -> None:
        found = sample_playlist.find_track("Bohemian Rhapsody", "Queen")
        assert found is not None
        assert found.id == "tr1"

    def test_find_track_case_insensitive(self, sample_playlist: Playlist) -> None:
        found = sample_playlist.find_track("bohemian rhapsody", "queen")
        assert found is not None

    def test_find_track_not_found(self, sample_playlist: Playlist) -> None:
        found = sample_playlist.find_track("Nonexistent", "Nobody")
        assert found is None
