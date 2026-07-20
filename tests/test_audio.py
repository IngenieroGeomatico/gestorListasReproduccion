import numpy as np
import pytest

pytest.importorskip("scipy")

from gestor_listas import audio
from gestor_listas.audio import (
    _PRIOR_DEFAULT,
    _PRIOR_EDM,
    _SAMPLE_RATE,
    _genre_name,
    _spectral_flux_envelope,
    _tempo_from_envelope,
    detect_bpm,
    is_edm_genre,
    read_genre_tag,
)


def _make_kick_track(bpm: float, seconds: float = 30.0, seed: int = 0) -> np.ndarray:
    """Genera audio sintético mono con un bombo periódico al BPM indicado.

    Cada golpe es un tono grave (~60 Hz) con envolvente exponencial decreciente,
    imitando el transitorio de un kick. Se añade algo de ruido para realismo.
    """
    rng = np.random.default_rng(seed)
    n = int(_SAMPLE_RATE * seconds)
    t = np.arange(n) / _SAMPLE_RATE
    signal = np.zeros(n, dtype=np.float64)

    beat_period = 60.0 / bpm
    kick_len = int(_SAMPLE_RATE * 0.12)
    kt = np.arange(kick_len) / _SAMPLE_RATE
    kick = np.sin(2 * np.pi * 60.0 * kt) * np.exp(-kt * 30.0)

    beat_time = 0.0
    while beat_time < seconds:
        start = int(beat_time * _SAMPLE_RATE)
        end = min(start + kick_len, n)
        signal[start:end] += kick[: end - start]
        beat_time += beat_period

    signal += 0.02 * rng.standard_normal(n)
    return (signal / np.max(np.abs(signal)) * 20000.0)


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


class TestIsEdmGenre:
    def test_none_is_not_edm(self) -> None:
        assert is_edm_genre(None) is False
        assert is_edm_genre("") is False

    def test_edm_genres_match(self) -> None:
        for g in ("Techno/House", "Hard Trance", "Hardstyle", "Dubstep",
                  "Dance", "Drum & Bass", "Remember", "Electro Pop"):
            assert is_edm_genre(g) is True, g

    def test_non_edm_genres_do_not_match(self) -> None:
        for g in ("Rock", "Pop", "Jazz", "Classical", "Reggae", "Country"):
            assert is_edm_genre(g) is False, g

    def test_case_insensitive(self) -> None:
        assert is_edm_genre("TECHNO") is True


class TestReadGenreTag:
    def test_missing_file_returns_none(self, tmp_path) -> None:
        assert read_genre_tag(tmp_path / "no_existe.mp3") is None

    def test_reads_genre_key(self, tmp_path, mocker) -> None:
        mocker.patch(
            "gestor_listas.audio.MutagenFile",
            return_value={"genre": ["Hardstyle"]},
        )
        assert read_genre_tag(tmp_path / "song.mp3") == "Hardstyle"

    def test_no_tags_returns_none(self, tmp_path, mocker) -> None:
        mocker.patch("gestor_listas.audio.MutagenFile", return_value=None)
        assert read_genre_tag(tmp_path / "song.mp3") is None

    def test_no_genre_key_returns_none(self, tmp_path, mocker) -> None:
        mocker.patch("gestor_listas.audio.MutagenFile", return_value={"artist": ["X"]})
        assert read_genre_tag(tmp_path / "song.mp3") is None


class TestDetectBpm:
    def test_missing_file_returns_none(self, tmp_path) -> None:
        assert detect_bpm(tmp_path / "no_existe.mp3") is None

    def test_ffmpeg_missing_raises(self, tmp_path, mocker) -> None:
        from gestor_listas.errors import DownloadError

        audio_file = tmp_path / "song.mp3"
        audio_file.write_bytes(b"x")
        mocker.patch(
            "gestor_listas.audio.resolve_ffmpeg",
            side_effect=DownloadError("No se encontró ffmpeg."),
        )
        with pytest.raises(DownloadError, match="ffmpeg"):
            detect_bpm(audio_file)

    def test_ffmpeg_failure_returns_none(self, tmp_path, mocker) -> None:
        audio_file = tmp_path / "song.mp3"
        audio_file.write_bytes(b"x")
        mocker.patch("gestor_listas.audio.resolve_ffmpeg", return_value="ffmpeg")
        mocker.patch(
            "gestor_listas.audio.subprocess.run",
            return_value=mocker.Mock(returncode=1, stdout="", stderr="err"),
        )
        assert detect_bpm(audio_file) is None


class TestTempoDetectionAccuracy:
    """Valida la precisión del algoritmo sobre señales sintéticas con BPM
    conocido, ejercitando el núcleo (flujo espectral + autocorrelación + prior)
    sin depender de ffmpeg."""

    @pytest.mark.parametrize("bpm", [90, 100, 120, 128])
    def test_default_prior_recovers_bpm(self, bpm: int) -> None:
        samples = _make_kick_track(bpm)
        env = _spectral_flux_envelope(samples)
        assert env is not None
        detected = _tempo_from_envelope(env, _PRIOR_DEFAULT)
        assert detected is not None
        assert abs(detected - bpm) <= 2.0, f"esperado {bpm}, detectado {detected}"

    @pytest.mark.parametrize("bpm", [140, 150, 160, 175])
    def test_edm_prior_recovers_high_bpm(self, bpm: int) -> None:
        samples = _make_kick_track(bpm)
        env = _spectral_flux_envelope(samples)
        assert env is not None
        detected = _tempo_from_envelope(env, _PRIOR_EDM)
        assert detected is not None
        assert abs(detected - bpm) <= 2.0, f"esperado {bpm}, detectado {detected}"

    def test_edm_prior_avoids_half_tempo_octave_error(self) -> None:
        """Un tema a 150 BPM no debe detectarse como 75 (medio tempo) con el
        prior de EDM: es el fallo que motivó el rediseño."""
        samples = _make_kick_track(150)
        env = _spectral_flux_envelope(samples)
        detected = _tempo_from_envelope(env, _PRIOR_EDM)
        assert detected is not None
        assert detected > 120, f"error de octava: detectado {detected}"

    def test_detect_bpm_end_to_end_with_genre(self, tmp_path, mocker) -> None:
        """detect_bpm completo: mockea ffmpeg para devolver PCM sintético a
        150 BPM y comprueba que con género EDM lo detecta correctamente."""
        samples = _make_kick_track(150).astype(np.int16)
        raw = samples.tobytes()

        audio_file = tmp_path / "hardstyle.mp3"
        audio_file.write_bytes(b"x")

        mocker.patch("gestor_listas.audio.resolve_ffmpeg", return_value="ffmpeg")
        mocker.patch(
            "gestor_listas.audio.subprocess.run",
            return_value=mocker.Mock(returncode=0, stdout="", stderr=""),
        )
        mocker.patch("gestor_listas.audio.Path.read_bytes", return_value=raw)

        detected = detect_bpm(audio_file, genre="Hardstyle")
        assert detected is not None
        assert abs(detected - 150) <= 2.0, f"detectado {detected}"
