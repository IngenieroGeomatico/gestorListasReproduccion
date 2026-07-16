import numpy as np
import pytest

pytest.importorskip("scipy")

from gestor_listas import audio
from gestor_listas.audio import _genre_name, detect_bpm


class TestGenreName:
    def test_known_genre(self) -> None:
        assert _genre_name(23) == "K-Pop"
        assert _genre_name(132) == "Pop"

    def test_unknown_genre(self) -> None:
        assert _genre_name(999999) is None

    def test_none_input(self) -> None:
        assert _genre_name(None) is None

    def test_string_id_is_parsed(self) -> None:
        assert _genre_name("23") == "K-Pop"

    def test_invalid_string(self) -> None:
        assert _genre_name("no-soy-un-numero") is None


class TestDetectBpm:
    def test_missing_file_returns_none(self, tmp_path) -> None:
        assert detect_bpm(tmp_path / "no_existe.mp3") is None

    def test_ffmpeg_missing_raises(self, tmp_path, mocker) -> None:
        from gestor_listas.errors import DownloadError

        audio_file = tmp_path / "song.mp3"
        audio_file.write_bytes(b"x")
        mocker.patch("gestor_listas.audio.subprocess.run", side_effect=FileNotFoundError)
        with pytest.raises(DownloadError, match="ffmpeg"):
            detect_bpm(audio_file)

    def test_ffmpeg_failure_returns_none(self, tmp_path, mocker) -> None:
        audio_file = tmp_path / "song.mp3"
        audio_file.write_bytes(b"x")
        mocker.patch(
            "gestor_listas.audio.subprocess.run",
            return_value=mocker.Mock(returncode=1, stdout="", stderr="err"),
        )
        assert detect_bpm(audio_file) is None


class TestVectorizedEnergy:
    """Verifica que el cálculo vectorizado de energía RMS por frame equivale
    a la implementación por bucle original."""

    def test_vectorized_matches_loop(self) -> None:
        rng = np.random.default_rng(42)
        samples = rng.standard_normal(22050 * 3).astype(np.float64)
        hop_length = 512
        frame_length = 2048
        num_frames = (len(samples) - frame_length) // hop_length

        energy_loop = np.zeros(num_frames)
        for i in range(num_frames):
            start = i * hop_length
            frame = samples[start:start + frame_length]
            energy_loop[i] = np.sqrt(np.mean(frame ** 2))

        frame_starts = np.arange(num_frames) * hop_length
        frames = samples[frame_starts[:, None] + np.arange(frame_length)]
        energy_vec = np.sqrt(np.mean(frames ** 2, axis=1))

        assert np.allclose(energy_loop, energy_vec)
