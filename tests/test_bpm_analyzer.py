import pytest

from gestor_listas import bpm_analyzer
from gestor_listas.bpm_analyzer import (
    _bpm_tag_key,
    analyze_directory,
    get_bpm,
    parse_extensions,
    read_existing_bpm,
    write_bpm,
)


class TestParseExtensions:
    def test_empty_returns_none(self) -> None:
        assert parse_extensions("") is None

    def test_single_extension(self) -> None:
        assert parse_extensions("mp3") == {".mp3"}

    def test_multiple_with_dots_and_spaces(self) -> None:
        assert parse_extensions(" mp3 , .flac,ogg ") == {".mp3", ".flac", ".ogg"}


class TestBpmTagKey:
    def test_mp3(self) -> None:
        assert _bpm_tag_key(".mp3") == "TBPM"

    def test_flac(self) -> None:
        assert _bpm_tag_key(".flac") == "BPM"

    def test_m4a(self) -> None:
        assert _bpm_tag_key(".m4a") == "----:com.apple.iTunes:BPM"

    def test_wav_has_no_key(self) -> None:
        assert _bpm_tag_key(".wav") is None

    def test_unknown_extension(self) -> None:
        assert _bpm_tag_key(".xyz") is None


class TestMp3BpmRoundTrip:
    def test_write_then_read(self, tmp_path) -> None:
        mp3 = tmp_path / "track.mp3"
        # mutagen ID3 puede añadir tags a un fichero aunque no sea un MP3 real.
        mp3.write_bytes(b"\x00" * 128)

        assert read_existing_bpm(mp3) is None
        assert write_bpm(mp3, 128.4) is True
        # Se guarda redondeado a entero (str(round(bpm))).
        assert read_existing_bpm(mp3) == 128.0

    def test_read_missing_bpm_returns_none(self, tmp_path) -> None:
        mp3 = tmp_path / "empty.mp3"
        mp3.write_bytes(b"\x00" * 128)
        assert read_existing_bpm(mp3) is None


class TestAnalyzeDirectory:
    def test_skips_files_with_existing_bpm(self, tmp_path, mocker) -> None:
        mp3 = tmp_path / "has_bpm.mp3"
        mp3.write_bytes(b"\x00" * 128)
        write_bpm(mp3, 100)

        detect = mocker.patch("gestor_listas.bpm_analyzer.detect_bpm")

        stats = analyze_directory(tmp_path, recursive=False, force=False)
        assert stats["skipped"] == 1
        assert stats["analyzed"] == 0
        detect.assert_not_called()

    def test_analyzes_and_tags(self, tmp_path, mocker) -> None:
        mp3 = tmp_path / "new.mp3"
        mp3.write_bytes(b"\x00" * 128)

        mocker.patch("gestor_listas.bpm_analyzer.detect_bpm", return_value=140.0)

        stats = analyze_directory(tmp_path, recursive=False, force=False)
        assert stats["scanned"] == 1
        assert stats["analyzed"] == 1
        assert stats["tagged"] == 1
        assert read_existing_bpm(mp3) == 140.0

    def test_force_reanalyzes(self, tmp_path, mocker) -> None:
        mp3 = tmp_path / "existing.mp3"
        mp3.write_bytes(b"\x00" * 128)
        write_bpm(mp3, 90)

        mocker.patch("gestor_listas.bpm_analyzer.detect_bpm", return_value=95.0)

        stats = analyze_directory(tmp_path, recursive=False, force=True)
        assert stats["skipped"] == 0
        assert stats["analyzed"] == 1

    def test_ignores_non_audio_files(self, tmp_path, mocker) -> None:
        (tmp_path / "notes.txt").write_text("hello")
        detect = mocker.patch("gestor_listas.bpm_analyzer.detect_bpm")
        stats = analyze_directory(tmp_path, recursive=False)
        assert stats["scanned"] == 0
        detect.assert_not_called()


class TestGetBpm:
    def test_swallows_exceptions(self, tmp_path, mocker) -> None:
        mocker.patch("gestor_listas.bpm_analyzer.detect_bpm", side_effect=RuntimeError("boom"))
        assert get_bpm(tmp_path / "x.mp3") is None


class TestReadExistingBpmByFormat:
    """Verifica que se elige la clase de mutagen y la key correctas por
    extensión, sin depender de ficheros binarios reales."""

    def test_flac_reads_bpm_key(self, tmp_path, mocker) -> None:
        fake = mocker.patch("gestor_listas.bpm_analyzer.FLAC")
        fake.return_value = {"BPM": ["123"]}
        assert read_existing_bpm(tmp_path / "song.flac") == 123.0
        fake.assert_called_once()

    def test_ogg_reads_bpm_key(self, tmp_path, mocker) -> None:
        fake = mocker.patch("gestor_listas.bpm_analyzer.OggVorbis")
        fake.return_value = {"BPM": ["140"]}
        assert read_existing_bpm(tmp_path / "song.ogg") == 140.0

    def test_opus_reads_bpm_key(self, tmp_path, mocker) -> None:
        fake = mocker.patch("gestor_listas.bpm_analyzer.OggOpus")
        fake.return_value = {"BPM": ["135"]}
        assert read_existing_bpm(tmp_path / "song.opus") == 135.0

    def test_flac_without_bpm_returns_none(self, tmp_path, mocker) -> None:
        fake = mocker.patch("gestor_listas.bpm_analyzer.FLAC")
        fake.return_value = {}
        assert read_existing_bpm(tmp_path / "song.flac") is None

    def test_m4a_reads_itunes_key(self, tmp_path, mocker) -> None:
        fake = mocker.patch("gestor_listas.bpm_analyzer.MP4")
        fake.return_value = {"----:com.apple.iTunes:BPM": [b"128"]}
        assert read_existing_bpm(tmp_path / "song.m4a") == 128.0


class TestWriteBpmByFormat:
    def test_flac_writes_bpm_key(self, tmp_path, mocker) -> None:
        tags: dict = {}
        instance = mocker.MagicMock()
        instance.__setitem__.side_effect = tags.__setitem__
        fake = mocker.patch("gestor_listas.bpm_analyzer.FLAC", return_value=instance)

        assert write_bpm(tmp_path / "song.flac", 90.6) is True
        fake.assert_called_once()
        instance.save.assert_called_once()
        assert tags["BPM"] == ["91"]

    def test_ogg_writes_bpm_key(self, tmp_path, mocker) -> None:
        tags: dict = {}
        instance = mocker.MagicMock()
        instance.__setitem__.side_effect = tags.__setitem__
        mocker.patch("gestor_listas.bpm_analyzer.OggVorbis", return_value=instance)

        assert write_bpm(tmp_path / "song.ogg", 128.0) is True
        assert tags["BPM"] == ["128"]

    def test_opus_writes_bpm_key(self, tmp_path, mocker) -> None:
        tags: dict = {}
        instance = mocker.MagicMock()
        instance.__setitem__.side_effect = tags.__setitem__
        mocker.patch("gestor_listas.bpm_analyzer.OggOpus", return_value=instance)

        assert write_bpm(tmp_path / "song.opus", 128.0) is True
        assert tags["BPM"] == ["128"]

    def test_m4a_writes_itunes_key(self, tmp_path, mocker) -> None:
        tags: dict = {}
        instance = mocker.MagicMock()
        instance.__setitem__.side_effect = tags.__setitem__
        mocker.patch("gestor_listas.bpm_analyzer.MP4", return_value=instance)

        assert write_bpm(tmp_path / "song.m4a", 100.0) is True
        assert tags["----:com.apple.iTunes:BPM"] == [b"100"]

    def test_failure_returns_false(self, tmp_path, mocker) -> None:
        mocker.patch("gestor_listas.bpm_analyzer.FLAC", side_effect=Exception("corrupto"))
        assert write_bpm(tmp_path / "song.flac", 90) is False
