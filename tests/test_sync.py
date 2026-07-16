import json
from unittest.mock import MagicMock

import pytest

from gestor_listas import sync
from gestor_listas.model import Playlist
from gestor_listas.storage import Storage


class TestGetSourcesPath:
    def test_points_to_data_sources_json(self) -> None:
        path = sync.get_sources_path()
        assert path.name == "sources.json"
        assert path.parent.name == "data"


class TestLoadSources:
    def test_missing_file_returns_defaults(self, tmp_path) -> None:
        missing = tmp_path / "no_such.json"
        result = sync.load_sources(missing)
        assert result == {"spotify": [], "deezer": [], "youtube": []}

    def test_reads_utf8_content(self, tmp_path) -> None:
        path = tmp_path / "sources.json"
        data = {"spotify": ["https://open.spotify.com/playlist/café"], "deezer": [], "youtube": []}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        result = sync.load_sources(path)
        assert result["spotify"] == ["https://open.spotify.com/playlist/café"]


class TestImportUrls:
    def test_isolates_failures_per_url(self, tmp_path) -> None:
        storage = Storage(db_path=tmp_path / "s.db")

        def fetch(url: str) -> Playlist:
            if url == "bad":
                raise RuntimeError("fallo de red")
            return Playlist(id=url, name=url, source="test")

        try:
            result = sync._import_urls(["a", "bad", "b"], storage, fetch, "test")
            # 'bad' falla pero 'a' y 'b' se importan igualmente.
            assert [p.id for p in result] == ["a", "b"]
            assert storage.playlist_count() == 2
        finally:
            storage.close()

    def test_all_urls_succeed(self, tmp_path) -> None:
        storage = Storage(db_path=tmp_path / "s2.db")

        def fetch(url: str) -> Playlist:
            return Playlist(id=url, name=url, source="test")

        try:
            result = sync._import_urls(["x", "y"], storage, fetch, "test")
            assert len(result) == 2
        finally:
            storage.close()

    def test_empty_url_list_short_circuits(self, tmp_path) -> None:
        storage = Storage(db_path=tmp_path / "s3.db")
        try:
            assert sync.import_spotify_urls([], storage) == []
            assert sync.import_deezer_urls([], storage) == []
            assert sync.import_youtube_urls([], storage) == []
        finally:
            storage.close()


class TestImportDeezerAll:
    def test_isolates_failures(self, mocker, tmp_path) -> None:
        storage = Storage(db_path=tmp_path / "dz.db")

        pl_ok = Playlist(id="1", name="ok", source="deezer")
        pl_bad = Playlist(id="2", name="bad", source="deezer")

        fake_provider = MagicMock()
        fake_provider.get_playlists.return_value = [pl_ok, pl_bad]

        def get_playlist(pid: str) -> Playlist:
            if pid == "2":
                raise RuntimeError("no disponible")
            return Playlist(id=pid, name="full", source="deezer")

        fake_provider.get_playlist.side_effect = get_playlist
        mocker.patch("gestor_listas.sync.DeezerProvider", return_value=fake_provider)

        try:
            result = sync.import_deezer_all(storage)
            assert [p.id for p in result] == ["1"]
            assert storage.playlist_count() == 1
        finally:
            storage.close()


class TestRun:
    def test_run_uses_deezer_all_when_empty(self, mocker, tmp_path) -> None:
        sources = {"spotify": [], "deezer": [], "youtube": []}
        mocker.patch("gestor_listas.sync.load_sources", return_value=sources)

        fake_storage = MagicMock()
        fake_storage.__enter__.return_value = fake_storage
        fake_storage.__exit__.return_value = None
        mocker.patch("gestor_listas.sync.Storage", return_value=fake_storage)

        import_all = mocker.patch(
            "gestor_listas.sync.import_deezer_all", return_value=[Playlist(id="d", name="d")]
        )
        import_dz_urls = mocker.patch("gestor_listas.sync.import_deezer_urls")

        result = sync.run()

        import_all.assert_called_once_with(fake_storage)
        import_dz_urls.assert_not_called()
        assert result["deezer"] == [Playlist(id="d", name="d")]
        fake_storage.__exit__.assert_called_once()

    def test_run_uses_deezer_urls_when_present(self, mocker) -> None:
        sources = {"spotify": [], "deezer": ["url1"], "youtube": []}
        mocker.patch("gestor_listas.sync.load_sources", return_value=sources)

        fake_storage = MagicMock()
        fake_storage.__enter__.return_value = fake_storage
        fake_storage.__exit__.return_value = None
        mocker.patch("gestor_listas.sync.Storage", return_value=fake_storage)

        import_all = mocker.patch("gestor_listas.sync.import_deezer_all")
        import_dz_urls = mocker.patch(
            "gestor_listas.sync.import_deezer_urls", return_value=[Playlist(id="d", name="d")]
        )

        sync.run()

        import_dz_urls.assert_called_once_with(["url1"], fake_storage)
        import_all.assert_not_called()

    def test_run_dispatches_all_sources(self, mocker) -> None:
        sources = {"spotify": ["s"], "deezer": ["d"], "youtube": ["y"]}
        mocker.patch("gestor_listas.sync.load_sources", return_value=sources)

        fake_storage = MagicMock()
        fake_storage.__enter__.return_value = fake_storage
        fake_storage.__exit__.return_value = None
        mocker.patch("gestor_listas.sync.Storage", return_value=fake_storage)

        sp = mocker.patch("gestor_listas.sync.import_spotify_urls", return_value=[])
        dz = mocker.patch("gestor_listas.sync.import_deezer_urls", return_value=[])
        yt = mocker.patch("gestor_listas.sync.import_youtube_urls", return_value=[])

        result = sync.run()

        sp.assert_called_once_with(["s"], fake_storage)
        dz.assert_called_once_with(["d"], fake_storage)
        yt.assert_called_once_with(["y"], fake_storage)
        assert set(result) == {"spotify", "deezer", "youtube"}
