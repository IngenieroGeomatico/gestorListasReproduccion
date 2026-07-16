import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gestor_listas.downloaders.deezer import (
    CHUNK_SIZE,
    DeezerDownloader,
    _decrypt,
    _decrypt_stream_to_file,
)
from gestor_listas.downloaders.manager import DownloadManager, DownloadResult
from gestor_listas.downloaders.youtube import YouTubeDownloader
from gestor_listas.model import Track


class _FakeResp:
    """Simula requests.Response.iter_content troceando en piezas arbitrarias."""

    def __init__(self, data: bytes, step: int = 777) -> None:
        self._data = data
        self._step = step

    def iter_content(self, chunk_size):  # noqa: ARG002 - firma compatible
        for i in range(0, len(self._data), self._step):
            yield self._data[i:i + self._step]


class TestStreamingDecrypt:
    @pytest.mark.parametrize(
        "size",
        [0, 100, CHUNK_SIZE, CHUNK_SIZE * 3, CHUNK_SIZE * 3 + 500, CHUNK_SIZE * 10 + 7],
    )
    def test_stream_matches_bulk(self, tmp_path, size: int) -> None:
        track_id = "3135556"
        data = os.urandom(size)
        expected = _decrypt(data, track_id)

        out = tmp_path / "out.bin"
        _decrypt_stream_to_file(_FakeResp(data), track_id, out)
        assert out.read_bytes() == expected


class TestResolveDeezerId:
    def test_numeric_id_used_directly(self) -> None:
        dl = DeezerDownloader(provider=MagicMock())
        track = Track(id="123456", title="T", artist="A")
        assert dl._resolve_deezer_id(track) == "123456"

    def test_isrc_track_falls_back_to_search(self) -> None:
        provider = MagicMock()
        provider.search_track.return_value = Track(id="999", title="T", artist="A")
        dl = DeezerDownloader(provider=provider)
        # id no numérico pero con ISRC: antes devolvía None, ahora busca.
        track = Track(id="spotify_abc", title="Song", artist="Artist", isrc="ABC123")
        assert dl._resolve_deezer_id(track) == "999"
        provider.search_track.assert_called_once_with("Song", "Artist")

    def test_search_returns_none(self) -> None:
        provider = MagicMock()
        provider.search_track.return_value = None
        dl = DeezerDownloader(provider=provider)
        track = Track(id="abc", title="Song", artist="Artist")
        assert dl._resolve_deezer_id(track) is None


class TestYouTubeParseOutputPath:
    def test_uses_printed_path(self, tmp_path) -> None:
        fp = tmp_path / "Artist - Song.opus"
        fp.write_bytes(b"x")
        stdout = f"log line\n{fp}\n"
        result = YouTubeDownloader._parse_output_path(stdout, tmp_path, "Artist - Song")
        assert result == fp

    def test_fallback_scans_directory(self, tmp_path) -> None:
        fp = tmp_path / "Artist - Song.mp3"
        fp.write_bytes(b"x")
        result = YouTubeDownloader._parse_output_path("basura\n", tmp_path, "Artist - Song")
        assert result == fp

    def test_returns_none_when_nothing_found(self, tmp_path) -> None:
        result = YouTubeDownloader._parse_output_path("", tmp_path, "No Existe")
        assert result is None


class TestYouTubeBuildCmd:
    def test_best_uses_opus_native(self) -> None:
        dl = YouTubeDownloader(output_format="best")
        cmd = dl._build_cmd("http://x", "out.%(ext)s")
        assert "opus" in cmd
        assert "--print" in cmd and "after_move:filepath" in cmd

    def test_mp3_recodes(self) -> None:
        dl = YouTubeDownloader(output_format="mp3")
        cmd = dl._build_cmd("http://x", "out.%(ext)s")
        assert "mp3" in cmd


class TestDownloadManager:
    def test_prefer_deezer_order(self, tmp_path) -> None:
        manager = DownloadManager(output_dir=tmp_path, prefer="deezer")
        manager._deezer = MagicMock()
        manager._youtube = MagicMock()
        manager._deezer.download.return_value = tmp_path / "song.mp3"

        track = Track(id="1", title="T", artist="A")
        result = manager.download_track(track)

        assert result.source == "deezer"
        manager._deezer.download.assert_called_once()
        manager._youtube.download.assert_not_called()

    def test_fallback_to_youtube_when_deezer_fails(self, tmp_path) -> None:
        manager = DownloadManager(output_dir=tmp_path, prefer="deezer")
        manager._deezer = MagicMock()
        manager._youtube = MagicMock()
        manager._deezer.download.side_effect = RuntimeError("deezer caido")
        manager._youtube.download.return_value = tmp_path / "song.opus"

        track = Track(id="1", title="T", artist="A")
        result = manager.download_track(track)

        assert result.source == "youtube"
        manager._youtube.download.assert_called_once()

    def test_prefer_youtube_order(self, tmp_path) -> None:
        manager = DownloadManager(output_dir=tmp_path, prefer="youtube")
        manager._deezer = MagicMock()
        manager._youtube = MagicMock()
        manager._youtube.download.return_value = tmp_path / "song.opus"

        track = Track(id="1", title="T", artist="A")
        result = manager.download_track(track)

        assert result.source == "youtube"
        manager._deezer.download.assert_not_called()

    def test_all_sources_fail(self, tmp_path) -> None:
        manager = DownloadManager(output_dir=tmp_path, prefer="deezer")
        manager._deezer = MagicMock()
        manager._youtube = MagicMock()
        manager._deezer.download.return_value = None
        manager._youtube.download.return_value = None

        track = Track(id="1", title="T", artist="A")
        result = manager.download_track(track)

        assert result.path is None
        assert result.error is not None
