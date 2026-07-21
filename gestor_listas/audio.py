from __future__ import annotations

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import numpy as np
from scipy.signal import butter, sosfilt, stft

from mutagen import File as MutagenFile
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TRCK, TCON, TBPM, APIC, error as MutagenError

from .config import resolve_ffmpeg

logger = logging.getLogger(__name__)

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

# ── Tempo prior por familia de género ────────────────────────────
#
# El género NO se detecta desde el audio: se lee del tag del fichero o se
# obtiene del ID de género de Deezer, y sirve únicamente para elegir el
# "tempo prior" que resuelve los errores de octava en la autocorrelación.
#
# Filosofía clave (soft prior sobre búsqueda ancha): la ventana de búsqueda
# de la autocorrelación es SIEMPRE ancha (60-240 BPM); el prior solo PONDERA
# los picos, no recorta la búsqueda. Así un tema mal etiquetado (o con un
# prior demasiado estrecho) nunca queda fuera del rango analizado: si su pico
# real es fuerte, se detecta aunque el prior no lo favorezca.


@dataclass(frozen=True)
class TempoPrior:
    """Prior log-normal (en log2 del BPM) para ponderar la autocorrelación.

    - center: BPM perceptual más probable de la familia (centro de la campana).
    - sigma: anchura en octavas (log2). Un sigma amplio apenas sesga; uno
      estrecho fuerza el tempo hacia el rango típico de la familia.
    - min_bpm/max_bpm: rango típico de la familia. INFORMATIVO: no recorta la
      búsqueda (que usa BPM_SEARCH_WINDOW); documenta el rango esperado y
      permite futuras heurísticas.
    """

    center: float
    sigma: float
    min_bpm: float
    max_bpm: float


# Ventana FIJA y ancha de búsqueda de la autocorrelación, común a todas las
# familias. El prior solo pondera dentro de esta ventana (soft weighting).
BPM_SEARCH_WINDOW = (60.0, 240.0)


# Familias de tempo para la clasificación de producción. Los centros están
# fundamentados en las distribuciones reales de tempo de cada género.
FAMILIES: dict[str, TempoPrior] = {
    # Electrónica rápida y de pulso muy marcado.
    "hardstyle_hardcore": TempoPrior(center=160.0, sigma=0.35, min_bpm=145.0, max_bpm=210.0),
    "dnb":                TempoPrior(center=174.0, sigma=0.30, min_bpm=85.0, max_bpm=190.0),
    "trance":             TempoPrior(center=140.0, sigma=0.35, min_bpm=130.0, max_bpm=155.0),
    # Electrónica de baile "de club".
    "house_techno":       TempoPrior(center=128.0, sigma=0.40, min_bpm=115.0, max_bpm=145.0),
    "dance_pop":          TempoPrior(center=125.0, sigma=0.45, min_bpm=110.0, max_bpm=140.0),
    # Géneros de pulso lento/medio.
    "hiphop_reggaeton":   TempoPrior(center=95.0, sigma=0.50, min_bpm=75.0, max_bpm=115.0),
    "pop_rock":           TempoPrior(center=120.0, sigma=0.55, min_bpm=90.0, max_bpm=150.0),
    "ballad":             TempoPrior(center=80.0, sigma=0.60, min_bpm=60.0, max_bpm=100.0),
    # Fallback ancho cuando no hay género (o es desconocido). Centrado en el
    # tempo más común de la música occidental (~125) con sigma amplio.
    "unknown":            TempoPrior(center=125.0, sigma=0.60, min_bpm=60.0, max_bpm=220.0),
}


# Mapeo directo ID de Deezer → familia. Es el camino PRIMARIO e independiente
# del idioma (los nombres de Deezer están en francés). Los IDs no listados
# caen en "unknown" vía FAMILIES.get(..., "unknown").
DEEZER_TO_FAMILY_MAP: dict[int, str] = {
    # house_techno: 106 Electro, 108 Dubstep, 109 Electro Hip-Hop,
    # 110 Electro Pop/Rock, 111 Techno/House, 112 House SA, 113 Dance, 114 Dancefloor
    106: "house_techno", 108: "house_techno", 109: "house_techno",
    110: "house_techno", 111: "house_techno", 112: "house_techno",
    113: "house_techno", 114: "house_techno",
    # trance
    115: "trance",
    # hiphop_reggaeton: raps (116,121,123,124,128), 122 Reggaeton, 125 Kwaito,
    # 144 Reggae, 145 Dancehall/Ragga, 146 Dub, 147 Ska (pulso medio-lento)
    116: "hiphop_reggaeton", 121: "hiphop_reggaeton", 122: "hiphop_reggaeton",
    123: "hiphop_reggaeton", 124: "hiphop_reggaeton", 125: "hiphop_reggaeton",
    128: "hiphop_reggaeton", 144: "hiphop_reggaeton", 145: "hiphop_reggaeton",
    146: "hiphop_reggaeton", 147: "hiphop_reggaeton",
    # dance_pop: 22 J-Pop, 23 K-Pop, 165 R&B, 168 Disco, 169 Soul & Funk
    22: "dance_pop", 23: "dance_pop", 165: "dance_pop",
    168: "dance_pop", 169: "dance_pop",
    # pop_rock: 132 Pop, 52 Chanson FR, 84 Country, 152 Rock, 153 Blues, 155 Hard Rock
    52: "pop_rock", 84: "pop_rock", 132: "pop_rock",
    152: "pop_rock", 153: "pop_rock", 155: "pop_rock",
    # ballad: 107 Chill Out/Trip-Hop/Lounge
    107: "ballad",
    # Ambiguos o de tempo muy variable → prior ancho, DECISIÓN EXPLÍCITA (no es
    # "desconocido": sabemos que existen y elegimos 'unknown' porque su tempo es
    # demasiado variable para un prior estrecho). El mapeo explícito evita además
    # el log de "no reconocido" de la cadena de fallback.
    # 98 Classique, 103 Opéra, 129 Jazz, 36 Flamenco, 67 Salsa, 71 Cumbia, 73 Tango
    36: "unknown", 67: "unknown", 71: "unknown", 73: "unknown",
    98: "unknown", 103: "unknown", 129: "unknown",
}


# Palabras clave por familia para tags de texto libre (read_genre_tag). Se
# evalúan en el ORDEN de FAMILY_KEYWORD_PRECEDENCE: las familias más específicas
# ganan a las genéricas (p. ej. "hardstyle" antes que "dance"; "drum & bass"
# antes que un genérico "bass"). Comparación en minúsculas por subcadena.
FAMILY_KEYWORD_PRECEDENCE: tuple[str, ...] = (
    "hardstyle_hardcore",
    "dnb",
    "trance",
    "house_techno",
    "hiphop_reggaeton",
    "dance_pop",
    "pop_rock",
    "ballad",
)

TEXT_TO_FAMILY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "hardstyle_hardcore": (
        "hardstyle", "hardcore", "frenchcore", "gabber", "uptempo",
        "speedcore", "hardtek", "makina", "rawstyle",
    ),
    "dnb": (
        "drum & bass", "drum and bass", "dnb", "d&b", "jungle", "breakcore",
    ),
    "trance": (
        "trance", "psytrance", "goa", "uplifting", "hands up", "hardtrance",
        "hard trance", "remember", "jumpstyle",
    ),
    "house_techno": (
        "techno", "house", "dubstep", "electro", "edm", "dancefloor",
        "rave", "bigroom", "big room", "tech house", "deep house",
        "progressive", "trap",
    ),
    "hiphop_reggaeton": (
        "hip hop", "hip-hop", "hiphop", "rap", "reggaeton", "reggae",
        "dancehall", "ragga", "dub", "ska", "kwaito", "grime", "drill",
    ),
    "dance_pop": (
        "dance", "disco", "funk", "k-pop", "kpop", "j-pop", "jpop",
        "eurodance", "synthpop", "r&b", "rnb",
    ),
    "pop_rock": (
        "rock", "pop", "metal", "blues", "country", "chanson", "punk",
        "indie", "folk", "grunge", "alternative",
    ),
    "ballad": (
        "ballad", "balada", "lounge", "chill", "trip-hop", "trip hop",
        "ambient", "soul", "acoustic", "slow",
    ),
}


def _family_from_text(text: str) -> Optional[str]:
    """Familia por palabras clave de texto (precedencia explícita), o None."""
    lower = text.lower()
    for family in FAMILY_KEYWORD_PRECEDENCE:
        if any(keyword in lower for keyword in TEXT_TO_FAMILY_KEYWORDS[family]):
            return family
    return None


def _family_from_deezer_id(deezer_id: int) -> str:
    """Familia para un ID de Deezer, con cadena de fallback:

      1. Mapa directo ID → familia (independiente del idioma).
      2. Si el ID no está pero SÍ tiene nombre en DEEZER_GENRE_MAP, intenta
         clasificar por ese nombre vía keywords.
      3. "unknown" (loggeando el ID/nombre para poder añadirlo después).
    """
    family = DEEZER_TO_FAMILY_MAP.get(deezer_id)
    if family is not None:
        return family

    name = DEEZER_GENRE_MAP.get(deezer_id)
    if name is not None:
        by_name = _family_from_text(name)
        if by_name is not None:
            logger.debug(
                "Género Deezer %s ('%s') no está en DEEZER_TO_FAMILY_MAP; "
                "clasificado por nombre como '%s'. Considera añadirlo al mapa.",
                deezer_id, name, by_name,
            )
            return by_name

    logger.debug(
        "Género Deezer no reconocido (id=%s, nombre=%s) → prior 'unknown'. "
        "Añádelo a DEEZER_TO_FAMILY_MAP si conoces su familia de tempo.",
        deezer_id, DEEZER_GENRE_MAP.get(deezer_id),
    )
    return "unknown"


def classify_genre(genre: Union[int, str, None]) -> str:
    """Clasifica un género (ID de Deezer o texto libre) en una familia de tempo.

    Punto de entrada único. Devuelve siempre una clave válida de FAMILIES
    ("unknown" si no se reconoce). Prioridad:
      1. int (o str puramente numérica) → ID de Deezer, con cadena de fallback
         (mapa de familia → nombre de Deezer → keywords → unknown).
      2. str de texto → palabras clave por familia, en orden de precedencia.

    Cuando un género no se reconoce, se emite un log de nivel debug con el
    valor original para poder ampliar los mapas más adelante, y se degrada de
    forma segura al prior ancho 'unknown' (nunca falla).
    """
    if genre is None:
        return "unknown"

    # Camino 1: ID de Deezer (int o cadena numérica como "111").
    if isinstance(genre, int):
        return _family_from_deezer_id(genre)
    if isinstance(genre, str):
        stripped = genre.strip()
        if not stripped:
            return "unknown"
        if stripped.isdigit():
            return _family_from_deezer_id(int(stripped))

        # Camino 2: texto libre → keywords por familia (precedencia explícita).
        by_text = _family_from_text(stripped)
        if by_text is not None:
            return by_text
        logger.debug(
            "Género de texto no reconocido ('%s') → prior 'unknown'. "
            "Añade una keyword a TEXT_TO_FAMILY_KEYWORDS si procede.",
            stripped,
        )

    return "unknown"


def prior_for_genre(genre: Union[int, str, None]) -> TempoPrior:
    """Devuelve el TempoPrior de la familia a la que pertenece el género."""
    return FAMILIES[classify_genre(genre)]


# ── Compatibilidad hacia atrás ───────────────────────────────────
# Se mantienen como constantes independientes con sus valores históricos (no
# son alias de FAMILIES) para no cambiar el comportamiento de código/tests que
# los importan directamente. El sistema nuevo usa classify_genre + FAMILIES.
_PRIOR_EDM = TempoPrior(center=170.0, sigma=0.48, min_bpm=120.0, max_bpm=210.0)
_PRIOR_DEFAULT = TempoPrior(center=125.0, sigma=0.55, min_bpm=70.0, max_bpm=190.0)

# Familias consideradas "EDM" por el wrapper is_edm_genre (compatibilidad).
_EDM_FAMILIES = frozenset(
    {"hardstyle_hardcore", "dnb", "trance", "house_techno"}
)


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


def is_edm_genre(genre: Union[int, str, None]) -> bool:
    """True si el género sugiere electrónica de baile de pulso rápido.

    Wrapper de compatibilidad sobre classify_genre: es EDM si la familia
    resultante es una de las de electrónica rápida/de club.
    """
    if genre is None or genre == "":
        return False
    return classify_genre(genre) in _EDM_FAMILIES


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


def _tempo_from_envelope(onset_env: np.ndarray, prior: TempoPrior) -> Optional[float]:
    """Estima el tempo de una envolvente de onset con autocorrelación sesgada
    ponderada por un tempo prior log-normal (resuelve errores de octava).

    La ventana de búsqueda es SIEMPRE ancha (BPM_SEARCH_WINDOW): el prior solo
    pondera los picos (soft weighting), nunca recorta la búsqueda. Así un tema
    mal etiquetado no queda fuera del rango analizado.
    """
    search_min_bpm, search_max_bpm = BPM_SEARCH_WINDOW
    min_lag = int(_ENVELOPE_RATE * 60.0 / search_max_bpm)
    max_lag = int(_ENVELOPE_RATE * 60.0 / search_min_bpm)
    if min_lag < 1 or max_lag <= min_lag:
        return None

    env = onset_env - np.mean(onset_env)
    # Bandpass muy amplio (30-600 BPM) para evitar distorsión de fase.
    nyq = _ENVELOPE_RATE / 2.0
    low = (30.0 / 60.0) / nyq
    high = (600.0 / 60.0) / nyq
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
    log_ratio = np.log2(bpms / prior.center)
    prior_weights = np.exp(-0.5 * (log_ratio / prior.sigma) ** 2)

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
    genre: Union[int, str, None] = None,
) -> Optional[float]:
    """Detecta el BPM de un fichero de audio.

    El género (si se pasa como ID de Deezer o texto, o si se lee de los
    metadatos del propio fichero) se clasifica en una familia de tempo
    (classify_genre) y elige el "tempo prior" correspondiente. Cada familia
    (hardstyle, dnb, trance, house/techno, pop/rock, hip-hop/reggaeton,
    balada...) centra el prior en su tempo típico, resolviendo los errores de
    octava según el estilo. La búsqueda siempre es ancha (BPM_SEARCH_WINDOW):
    el prior solo pondera, así que un género mal etiquetado nunca impide
    detectar un tempo real fuerte.
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

    # Elegir el prior por familia de género: parámetro explícito (ID Deezer o
    # texto) o tag leído del fichero. classify_genre normaliza ambos casos.
    genre = genre if genre is not None else read_genre_tag(audio_path)
    prior = prior_for_genre(genre)

    onset_env = _spectral_flux_envelope(samples)
    if onset_env is None or len(onset_env) < 16:
        return None

    bpm = _tempo_from_envelope(onset_env, prior)
    if bpm is None:
        return None
    return round(bpm, 1)
