from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.signal import butter, sosfilt, stft

from mutagen import File as MutagenFile
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TRCK, TCON, TBPM, APIC, error as MutagenError

from .config import resolve_ffmpeg

# Mapping de género obtenido de Deezer genre.getData (0-200, más IDs dispersos)
DEEZER_GENRE_MAP: dict[int, str] = {
    2: "Musique africaine",
    3: "Afro Pop",
    4: "Biguine",
    5: "Coupé-Décalé",
    6: "Sega mauritien",
    7: "Seggae mauritien",
    8: "Swag mauritien",
    9: "Touareg",
    10: "Zouglou",
    11: "Zouk",
    12: "Musique arabe",
    13: "Chaabi",
    14: "Charki",
    15: "Raï",
    16: "Musique asiatique",
    18: "Pop Chinoise",
    20: "Pop indonésienne",
    22: "J-Pop",
    23: "K-Pop",
    24: "Pop malaisienne",
    25: "Musique indonésienne",
    27: "Country thaï",
    28: "Pop thaï",
    29: "Retro thaï",
    36: "Flamenco",
    39: "Isklemä",
    45: "Schlager & Volksmusik",
    49: "Folk turc",
    52: "Chanson française",
    58: "Banda/Grupero",
    60: "Folklore latino-américain",
    65: "Musique traditionnelle mexicaine",
    67: "Salsa",
    71: "Cumbia",
    73: "Tango",
    75: "Musique brésilienne",
    76: "Axé/Forró",
    78: "MPB",
    79: "Samba/Pagode",
    80: "Sertanejo",
    81: "Musique indienne",
    84: "Country",
    85: "Alternative",
    86: "Pop Indé",
    87: "Rock indé",
    88: "Indé thaï",
    89: "Indé Finlandaise",
    90: "Indé Estonie",
    91: "Alternatif latin",
    94: "Alternatif brésilien",
    95: "Jeunesse",
    96: "Comptines/Chansons",
    97: "Histoires",
    98: "Classique",
    99: "Baroque",
    100: "Période classique",
    101: "Médieval",
    102: "Moderne",
    103: "Opéra",
    104: "Renaissance",
    105: "Romantique",
    106: "Electro",
    107: "Chill Out/Trip-Hop/Lounge",
    108: "Dubstep",
    109: "Electro Hip-Hop",
    110: "Electro Pop/Electro Rock",
    111: "Techno/House",
    112: "House sud-africaine",
    113: "Dance",
    114: "Dancefloor",
    115: "Trance",
    116: "Rap/Hip Hop",
    121: "Rap en allemand",
    122: "Reggaeton",
    123: "Rap russe",
    124: "Rap finlandais",
    125: "Kwaito",
    128: "Rap français",
    129: "Jazz",
    130: "Jazz instrumental",
    131: "Jazz vocal",
    132: "Pop",
    133: "Pop indé/Folk",
    134: "Pop internationale",
    135: "Pop russe",
    136: "Pop finlandaise",
    137: "Pop turque",
    138: "Pop latine",
    141: "Variété Internationale",
    142: "Pop-Rock hongrois",
    143: "Pop française",
    144: "Reggae",
    145: "Dancehall/Ragga",
    146: "Dub",
    147: "Ska",
    149: "Reggae finlandais",
    150: "Reggae mauritien",
    152: "Rock",
    153: "Blues",
    154: "Rock Indé/Pop Rock",
    155: "Hard Rock",
    156: "Rock & Roll/Rockabilly",
    157: "Metal finlandais",
    158: "Rock russe",
    159: "Rock turc",
    160: "Rock latin",
    161: "Rock brésilien",
    162: "Rock finlandais",
    164: "Rock français",
    165: "R&B",
    166: "R&B contemporain",
    167: "Soul contemporaine",
    168: "Disco",
    169: "Soul & Funk",
    170: "R&B vieille école",
    171: "Soul vieille école",
    173: "Films/Jeux vidéo",
    174: "Musiques de films",
    175: "Comédies musicales",
    176: "Bandes originales",
    177: "BO TV",
    178: "Bollywood",
    179: "Musiques de jeux vidéo",
    180: "Blues acoustique",
    181: "Chicago blues",
    182: "Blues classique",
    183: "Country blues",
    184: "Delta blues",
    185: "Blues électrique",
    186: "Musique religieuse",
    187: "Gospel",
    188: "Liturgique",
    189: "Pop chrétienne",
    190: "Rap chrétien",
    191: "Rock chrétien",
    192: "Country alternative",
    193: "Bluegrass",
    194: "Honky Tonk",
    195: "Country traditionnelle",
    196: "Cowboy urbain",
    197: "Latino",
    198: "Tango mexicain traditionnel",
    199: "Caribe",
    200: "Dirty South",
    500: "Vallenato",
}


def _genre_name(genre_id: object) -> Optional[str]:
    if genre_id is None:
        return None
    try:
        gid = int(genre_id)
    except (ValueError, TypeError):
        return None
    return DEEZER_GENRE_MAP.get(gid)


def write_id3_tags(
    mp3_path: str | Path,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    year: Optional[str] = None,
    track_number: Optional[int] = None,
    genre: Optional[str] = None,
    cover_data: Optional[bytes] = None,
    bpm: Optional[float] = None,
) -> None:
    path = Path(mp3_path)
    try:
        tags = ID3(str(path))
    except MutagenError:
        tags = ID3()

    if title:
        tags["TIT2"] = TIT2(encoding=3, text=title)
    if artist:
        tags["TPE1"] = TPE1(encoding=3, text=artist)
    if album:
        tags["TALB"] = TALB(encoding=3, text=album)
    if year:
        tags["TDRC"] = TDRC(encoding=3, text=year)
    if track_number is not None:
        tags["TRCK"] = TRCK(encoding=3, text=str(track_number))
    if genre:
        tags["TCON"] = TCON(encoding=3, text=genre)
    if bpm is not None:
        tags["TBPM"] = TBPM(encoding=3, text=str(round(bpm)))
    if cover_data:
        tags["APIC"] = APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover_data)

    tags.save(str(path))


# ── Detección de BPM ─────────────────────────────────────────────

_SAMPLE_RATE = 22050
_HOP_LENGTH = 512
_FRAME_LENGTH = 2048
# Frecuencia de frames de la envolvente de onset: 22050/512 ≈ 43.07 Hz.
_ENVELOPE_RATE = _SAMPLE_RATE / _HOP_LENGTH

# Palabras clave (en el nombre de género) que indican música electrónica de
# baile con pulso rápido y marcado (hardstyle, techno, trance, remember...).
# La comparación es en minúsculas y por subcadena, así que "Techno/House"
# o "Hard Trance" también encajan.
_EDM_GENRE_KEYWORDS = (
    "techno", "house", "trance", "hardstyle", "hardcore", "hard dance",
    "dubstep", "drum & bass", "drum and bass", "dnb", "electro", "edm",
    "dancefloor", "dance", "rave", "gabber", "psytrance", "bigroom",
    "big room", "remember", "makina", "jumpstyle", "hands up", "hardtek",
)

# Parámetros del "tempo prior" log-normal según el tipo de música.
# - center: BPM perceptual más probable (centro de la campana).
# - sigma: anchura en octavas (log2). Un sigma amplio apenas sesga;
#   uno estrecho fuerza el rango objetivo.
# - min_bpm/max_bpm: ventana de búsqueda de la autocorrelación.
_PRIOR_EDM = {"center": 155.0, "sigma": 0.45, "min_bpm": 120, "max_bpm": 185}
_PRIOR_DEFAULT = {"center": 125.0, "sigma": 0.55, "min_bpm": 70, "max_bpm": 190}


def read_genre_tag(filepath: str | Path) -> Optional[str]:
    """Lee el género desde los metadatos del fichero de audio, transversal a
    formato (MP3/ID3, FLAC/Ogg/Opus Vorbis, MP4/M4A). Devuelve None si no hay.

    Usa mutagen en modo genérico (easy) para no depender del contenedor: la
    clave 'genre' está expuesta de forma uniforme para los formatos comunes.
    """
    try:
        tags = MutagenFile(str(filepath), easy=True)
    except Exception:
        return None
    if not tags:
        return None
    value = tags.get("genre")
    if not value:
        return None
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if not value:
        return None
    return str(value).strip() or None


def is_edm_genre(genre: Optional[str]) -> bool:
    """True si el género sugiere electrónica de baile de pulso rápido."""
    if not genre:
        return False
    g = genre.lower()
    return any(keyword in g for keyword in _EDM_GENRE_KEYWORDS)


def _spectral_flux_envelope(samples: np.ndarray) -> Optional[np.ndarray]:
    """Envolvente de onset por flujo espectral (suma de incrementos positivos
    de magnitud entre frames consecutivos del espectrograma).

    El flujo espectral detecta transitorios (golpes de bombo) mucho mejor que
    la energía RMS, que se diluye con bajos/sintes sostenidos típicos de EDM.
    """
    _, _, zxx = stft(
        samples,
        fs=_SAMPLE_RATE,
        nperseg=_FRAME_LENGTH,
        noverlap=_FRAME_LENGTH - _HOP_LENGTH,
        boundary=None,
        padded=False,
    )
    if zxx.shape[1] < 4:
        return None
    spec = np.abs(zxx)
    # Incrementos positivos de magnitud por banda, sumados sobre el espectro.
    diff = np.diff(spec, axis=1, prepend=spec[:, :1])
    onset_env = np.sum(np.maximum(0.0, diff), axis=0)
    return onset_env


def _tempo_from_envelope(onset_env: np.ndarray, prior: dict) -> Optional[float]:
    """Estima el tempo de una envolvente de onset con autocorrelación sesgada
    ponderada por un tempo prior log-normal (resuelve errores de octava)."""
    min_bpm, max_bpm = prior["min_bpm"], prior["max_bpm"]
    min_lag = int(_ENVELOPE_RATE * 60.0 / max_bpm)
    max_lag = int(_ENVELOPE_RATE * 60.0 / min_bpm)
    if min_lag < 1 or max_lag <= min_lag:
        return None

    env = onset_env - np.mean(onset_env)
    # Bandpass sobre la envolvente ceñido al rango de búsqueda de tempo.
    nyq = _ENVELOPE_RATE / 2.0
    low = (min_bpm / 60.0) / nyq
    high = (max_bpm / 60.0) / nyq
    if not (0 < low < high < 1):
        return None
    sos = butter(2, [low, high], btype="band", output="sos")
    env = sosfilt(sos, env)

    if len(env) < max_lag + 2:
        return None

    # Autocorrelación sesgada (no normalizada): penaliza lags largos = tempos
    # lentos, lo cual es deseable (Oracle). Nos quedamos con la mitad positiva.
    autocorr = np.correlate(env, env, mode="full")
    mid = len(autocorr) // 2
    ac = autocorr[mid + min_lag: mid + max_lag + 1]
    if len(ac) < 2:
        return None

    lags = np.arange(min_lag, min_lag + len(ac))
    bpms = 60.0 * _ENVELOPE_RATE / lags

    # Tempo prior log-normal: campana en log2(bpm) centrada en 'center'.
    log_ratio = np.log2(bpms / prior["center"])
    prior_weights = np.exp(-0.5 * (log_ratio / prior["sigma"]) ** 2)

    weighted = np.maximum(0.0, ac) * prior_weights
    if not np.any(weighted > 0):
        return None

    best_idx = int(np.argmax(weighted))

    # Interpolación parabólica alrededor del pico para precisión sub-lag: la
    # autocorrelación está muestreada en lags enteros y a ~43 Hz de frame rate
    # cada lag equivale a varios BPM, lo que introduce un sesgo de cuantización.
    lag = float(min_lag + best_idx)
    if 0 < best_idx < len(ac) - 1:
        y0, y1, y2 = ac[best_idx - 1], ac[best_idx], ac[best_idx + 1]
        denom = y0 - 2.0 * y1 + y2
        if denom != 0:
            offset = 0.5 * (y0 - y2) / denom
            if -1.0 < offset < 1.0:
                lag += offset

    return float(60.0 * _ENVELOPE_RATE / lag)


def detect_bpm(
    audio_path: str | Path,
    max_duration: float = 60.0,
    genre: Optional[str] = None,
) -> Optional[float]:
    """Detecta el BPM de un fichero de audio.

    El género (si se pasa, o si se lee de los metadatos del propio fichero)
    ajusta el "tempo prior": los géneros de electrónica de baile usan un prior
    centrado en ~150 BPM (rango 120-185), el resto uno balanceado ~125 BPM
    (rango 70-190). Así se resuelven correctamente los errores de octava tanto
    en hardstyle/techno como en pop/rock/baladas.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        return None

    ffmpeg_exe = resolve_ffmpeg()

    with tempfile.NamedTemporaryFile(suffix=".raw", delete=True) as tmp:
        tmp_path = tmp.name

        cmd = [
            ffmpeg_exe, "-y",
            "-i", str(audio_path),
            "-t", str(max_duration),
            "-acodec", "pcm_s16le",
            "-ar", str(_SAMPLE_RATE),
            "-ac", "1",
            "-f", "s16le",
            tmp_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return None

        raw = Path(tmp_path).read_bytes()
        if len(raw) < 4096:
            return None

        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64)

    # Elegir el prior por género: parámetro explícito o tag del fichero.
    genre = genre if genre is not None else read_genre_tag(audio_path)
    prior = _PRIOR_EDM if is_edm_genre(genre) else _PRIOR_DEFAULT

    onset_env = _spectral_flux_envelope(samples)
    if onset_env is None or len(onset_env) < 16:
        return None

    bpm = _tempo_from_envelope(onset_env, prior)
    if bpm is None:
        return None
    return round(bpm, 1)
