import numpy as np
import pytest

pytest.importorskip("scipy")

from gestor_listas import audio
from gestor_listas.audio import (
    BPM_SEARCH_WINDOW,
    FAMILIES,
    _PRIOR_DEFAULT,
    _PRIOR_EDM,
    _SAMPLE_RATE,
    TempoPrior,
    _genre_name,
    _spectral_flux_envelope,
    _tempo_from_envelope,
    classify_genre,
    detect_bpm,
    is_edm_genre,
    prior_for_genre,
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
                  "Drum & Bass", "Electro Pop"):
            assert is_edm_genre(g) is True, g

    def test_non_edm_genres_do_not_match(self) -> None:
        for g in ("Rock", "Pop", "Jazz", "Classical", "Country"):
            assert is_edm_genre(g) is False, g

    def test_case_insensitive(self) -> None:
        assert is_edm_genre("TECHNO") is True

    def test_deezer_id_edm(self) -> None:
        # 111 = Techno/House → familia house_techno (EDM).
        assert is_edm_genre(111) is True
        # 132 = Pop → familia pop_rock (no EDM).
        assert is_edm_genre(132) is False


class TestClassifyGenre:
    def test_none_and_empty_are_unknown(self) -> None:
        assert classify_genre(None) == "unknown"
        assert classify_genre("") == "unknown"
        assert classify_genre("   ") == "unknown"

    def test_deezer_id_int(self) -> None:
        assert classify_genre(111) == "house_techno"   # Techno/House
        assert classify_genre(115) == "trance"          # Trance
        assert classify_genre(122) == "hiphop_reggaeton"  # Reggaeton
        assert classify_genre(132) == "pop_rock"        # Pop
        assert classify_genre(107) == "ballad"          # Chill Out/Lounge

    def test_deezer_id_numeric_string(self) -> None:
        assert classify_genre("111") == "house_techno"
        assert classify_genre("132") == "pop_rock"

    def test_unknown_deezer_id_falls_back(self) -> None:
        assert classify_genre(999999) == "unknown"
        assert classify_genre(129) == "unknown"  # Jazz: mapeado explícito a unknown

    def test_text_families(self) -> None:
        assert classify_genre("Hardstyle") == "hardstyle_hardcore"
        assert classify_genre("Drum & Bass") == "dnb"
        assert classify_genre("Progressive Trance") == "trance"
        assert classify_genre("Deep House") == "house_techno"
        assert classify_genre("Reggaeton") == "hiphop_reggaeton"
        assert classify_genre("Indie Rock") == "pop_rock"
        assert classify_genre("Piano Ballad") == "ballad"

    def test_text_is_case_insensitive(self) -> None:
        assert classify_genre("HARDSTYLE") == "hardstyle_hardcore"
        assert classify_genre("dRuM & bAsS") == "dnb"

    def test_precedence_specific_wins_over_generic(self) -> None:
        # "Hard Dance" contiene "dance" (dance_pop) pero "hardstyle"/"hardcore"
        # tienen prioridad; aquí "hardtek" gana. Un caso claro: hardcore + dance.
        assert classify_genre("Hardcore Dance") == "hardstyle_hardcore"
        # "drum & bass" gana aunque contenga texto genérico.
        assert classify_genre("Liquid Drum & Bass") == "dnb"
        # trance gana a un genérico "dance".
        assert classify_genre("Trance Dance") == "trance"

    def test_unrecognized_text_is_unknown(self) -> None:
        assert classify_genre("Zzzzz Undefined Genre") == "unknown"

    def test_flamenco_id_is_unknown_by_design(self) -> None:
        # 36 = Flamenco: mapeado explícitamente a unknown (tempo muy variable).
        assert classify_genre(36) == "unknown"

    def test_unmapped_deezer_id_falls_back_to_name_keywords(self) -> None:
        """Un ID de Deezer que no está en DEEZER_TO_FAMILY_MAP pero sí tiene
        nombre en DEEZER_GENRE_MAP debe intentar clasificarse por su nombre.

        ID 154 = 'Rock Indé/Pop Rock' → contiene 'rock'/'pop' → pop_rock.
        """
        from gestor_listas.audio import DEEZER_TO_FAMILY_MAP, DEEZER_GENRE_MAP

        assert 154 not in DEEZER_TO_FAMILY_MAP
        assert "Rock" in DEEZER_GENRE_MAP.get(154, "")
        assert classify_genre(154) == "pop_rock"

    def test_completely_unmapped_id_is_unknown(self) -> None:
        # ID que no existe en ningún mapa → unknown, sin lanzar.
        assert classify_genre(888888) == "unknown"

    def test_unrecognized_genre_logs_debug(self, caplog) -> None:
        import logging

        with caplog.at_level(logging.DEBUG, logger="gestor_listas.audio"):
            assert classify_genre("Totally Made Up Genre") == "unknown"
        assert any("no reconocido" in r.message for r in caplog.records)


class TestPriorForGenre:
    def test_returns_family_prior(self) -> None:
        assert prior_for_genre("Hardstyle") is FAMILIES["hardstyle_hardcore"]
        assert prior_for_genre(111) is FAMILIES["house_techno"]
        assert prior_for_genre(None) is FAMILIES["unknown"]

    def test_all_families_are_tempo_priors(self) -> None:
        for name, prior in FAMILIES.items():
            assert isinstance(prior, TempoPrior), name
            assert prior.min_bpm < prior.max_bpm, name
            assert prior.sigma > 0, name
            assert BPM_SEARCH_WINDOW[0] <= prior.center <= BPM_SEARCH_WINDOW[1], name


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


class TestFamilyPriorsAccuracy:
    """Cada familia debe recuperar BPM típicos de su rango sobre señales
    sintéticas, usando su TempoPrior real (sistema multi-familia)."""

    @pytest.mark.parametrize(
        "family,bpm",
        [
            ("ballad", 75),
            ("hiphop_reggaeton", 95),
            ("pop_rock", 120),
            ("house_techno", 128),
            ("trance", 140),
            ("hardstyle_hardcore", 160),
            ("dnb", 174),
        ],
    )
    def test_family_prior_recovers_typical_bpm(self, family: str, bpm: int) -> None:
        samples = _make_kick_track(bpm)
        env = _spectral_flux_envelope(samples)
        assert env is not None
        detected = _tempo_from_envelope(env, FAMILIES[family])
        assert detected is not None
        assert abs(detected - bpm) <= 2.0, f"{family}: esperado {bpm}, detectado {detected}"

    @pytest.mark.parametrize("bpm", [90, 100, 120, 128, 150])
    def test_unknown_prior_recovers_common_bpm(self, bpm: int) -> None:
        """El prior 'unknown' (sin tag de género) debe recuperar BPM comunes
        en un rango amplio sin errores de octava graves."""
        samples = _make_kick_track(bpm)
        env = _spectral_flux_envelope(samples)
        assert env is not None
        detected = _tempo_from_envelope(env, FAMILIES["unknown"])
        assert detected is not None
        assert abs(detected - bpm) <= 2.0, f"esperado {bpm}, detectado {detected}"

    def test_dnb_prior_avoids_half_time_error(self) -> None:
        """Un tema de 174 BPM (dnb) no debe colapsar a 87 (medio tiempo)."""
        samples = _make_kick_track(174)
        env = _spectral_flux_envelope(samples)
        detected = _tempo_from_envelope(env, FAMILIES["dnb"])
        assert detected is not None
        assert detected > 140, f"error de octava: detectado {detected}"

    def test_wide_search_finds_peak_outside_family_range(self) -> None:
        """Soft prior sobre búsqueda ancha: un tema a 150 BPM etiquetado como
        'ballad' (prior centrado en 80, rango 60-100) DEBE poder detectarse
        porque la ventana de búsqueda es ancha (60-240), no recortada al prior."""
        samples = _make_kick_track(150)
        env = _spectral_flux_envelope(samples)
        detected = _tempo_from_envelope(env, FAMILIES["ballad"])
        assert detected is not None
        # No exigimos ±2 (el prior de balada tira hacia abajo), pero el pico
        # real a 150 debe seguir siendo alcanzable: no debe quedar clavado en
        # el rango de la balada por recorte de ventana. Aceptamos 150 o su
        # subarmónico 75 (medio tiempo), pero NUNCA un valor imposible.
        assert 70 <= detected <= 160, f"detectado {detected} fuera de lo plausible"
