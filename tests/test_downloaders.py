import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from gestor_listas.downloaders.deezer import (
    CHUNK_SIZE,
    DeezerDownloader,
    _blowfish_key,
    _decrypt,
    _decrypt_chunk,
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


class TestBlowfishKey:
    def test_key_is_deterministic_and_16_bytes(self) -> None:
        key = _blowfish_key("3135556")
        assert len(key) == 16
        # Vector fijo: si cambia el algoritmo de derivación, esto salta.
        assert key.hex() == "6c6c666b39662c37652575603c643439"

    def test_different_ids_yield_different_keys(self) -> None:
        assert _blowfish_key("111") != _blowfish_key("222")


class TestDecryptChunk:
    def test_roundtrip_with_known_key(self) -> None:
        key = _blowfish_key("3135556")
        plain = b"A" * CHUNK_SIZE
        cipher = Cipher(algorithms.Blowfish(key), modes.CBC(b"\x00\x01\x02\x03\x04\x05\x06\x07"))
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(plain) + encryptor.finalize()

        assert _decrypt_chunk(ciphertext, key) == plain

    def test_only_every_third_block_encrypted(self) -> None:
        # _decrypt cifra solo el bloque 0, 3, 6... Los demás quedan en claro.
        key = _blowfish_key("3135556")
        cipher = Cipher(algorithms.Blowfish(key), modes.CBC(b"\x00\x01\x02\x03\x04\x05\x06\x07"))
        enc = cipher.encryptor()
        block0_plain = b"X" * CHUNK_SIZE
        block0_enc = enc.update(block0_plain) + enc.finalize()
        block1_plain = b"Y" * CHUNK_SIZE  # este NO se cifra (índice 1)

        data = block0_enc + block1_plain
        out = _decrypt(data, "3135556")
        assert out[:CHUNK_SIZE] == block0_plain
        assert out[CHUNK_SIZE:] == block1_plain


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


class TestDeezerStreamUrl:
    def test_get_stream_url_success(self, mocker) -> None:
        provider = MagicMock()
        provider._gw.side_effect = [
            {"TRACK_TOKEN": "tok"},  # song.getData
            {"USER": {"OPTIONS": {"license_token": "lic"}}},  # deezer.getUserData
        ]
        dl = DeezerDownloader(provider=provider)

        resp = mocker.Mock(status_code=200)
        resp.json.return_value = {
            "data": [{"media": [{"sources": [{"url": "https://media/stream"}]}]}]
        }
        mocker.patch("gestor_listas.downloaders.deezer._session.post", return_value=resp)

        assert dl._get_stream_url("123") == "https://media/stream"

    def test_get_stream_url_no_track_token(self) -> None:
        provider = MagicMock()
        provider._gw.return_value = {}  # sin TRACK_TOKEN
        dl = DeezerDownloader(provider=provider)
        assert dl._get_stream_url("123") is None

    def test_get_stream_url_http_error(self, mocker) -> None:
        provider = MagicMock()
        provider._gw.side_effect = [
            {"TRACK_TOKEN": "tok"},
            {"USER": {"OPTIONS": {"license_token": "lic"}}},
        ]
        dl = DeezerDownloader(provider=provider)
        resp = mocker.Mock(status_code=403)
        mocker.patch("gestor_listas.downloaders.deezer._session.post", return_value=resp)
        assert dl._get_stream_url("123") is None

    def test_get_stream_url_gw_exception(self) -> None:
        provider = MagicMock()
        provider._gw.side_effect = RuntimeError("gw caido")
        dl = DeezerDownloader(provider=provider)
        assert dl._get_stream_url("123") is None


class TestDeezerTagFile:
    def test_tag_file_writes_metadata(self, tmp_path, mocker) -> None:
        provider = MagicMock()
        provider._gw.side_effect = [
            {  # song.getData
                "SNG_TITLE": "Cancion",
                "ART_NAME": "Artista",
                "ALB_ID": "555",
                "TRACK_NUMBER": 3,
                "GENRE_ID": 23,
            },
            {  # album.getData
                "ALB_TITLE": "Album",
                "DIGITAL_RELEASE_DATE": "2021-05-01",
                "ALB_PICTURE": "hash",
            },
        ]
        dl = DeezerDownloader(provider=provider)

        write_tags = mocker.patch("gestor_listas.audio.write_id3_tags")
        mocker.patch("gestor_listas.audio.detect_bpm", return_value=128.0)
        mocker.patch(
            "gestor_listas.downloaders.deezer._session.get",
            return_value=mocker.Mock(content=b"coverbytes"),
        )

        mp3 = tmp_path / "song.mp3"
        mp3.write_bytes(b"x")
        dl._tag_file(mp3, "123")

        write_tags.assert_called_once()
        _, kwargs = write_tags.call_args
        assert kwargs["title"] == "Cancion"
        assert kwargs["artist"] == "Artista"
        assert kwargs["album"] == "Album"
        assert kwargs["year"] == "2021"
        assert kwargs["genre"] == "K-Pop"
        assert kwargs["bpm"] == 128.0

    def test_tag_file_gw_failure_returns_early(self, tmp_path, mocker) -> None:
        provider = MagicMock()
        provider._gw.side_effect = RuntimeError("no disponible")
        dl = DeezerDownloader(provider=provider)
        write_tags = mocker.patch("gestor_listas.audio.write_id3_tags")

        mp3 = tmp_path / "song.mp3"
        mp3.write_bytes(b"x")
        dl._tag_file(mp3, "123")  # no debe lanzar
        write_tags.assert_not_called()


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

    def test_download_playlist_parallel_preserves_order(self, tmp_path) -> None:
        from gestor_listas.model import Playlist

        manager = DownloadManager(output_dir=tmp_path, prefer="deezer", max_workers=3)
        manager._deezer = MagicMock()
        manager._youtube = MagicMock()

        def fake_download(track, dest):
            return dest / f"{track.id}.mp3"

        manager._deezer.download.side_effect = fake_download

        tracks = [Track(id=str(i), title=f"S{i}", artist="A") for i in range(5)]
        pl = Playlist(id="pl", name="Lista", tracks=tracks)
        results = manager.download_playlist(pl, use_subfolder=False)

        assert [r.track.id for r in results] == ["0", "1", "2", "3", "4"]
        assert all(r.path is not None for r in results)

    def test_max_workers_floor_is_one(self, tmp_path) -> None:
        manager = DownloadManager(output_dir=tmp_path, max_workers=0)
        assert manager.max_workers == 1
