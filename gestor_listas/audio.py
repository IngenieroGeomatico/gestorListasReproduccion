from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.signal import butter, sosfilt

from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TRCK, TCON, TBPM, APIC, error as MutagenError

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


def detect_bpm(audio_path: str | Path, max_duration: float = 60.0) -> Optional[float]:
    audio_path = Path(audio_path)
    if not audio_path.exists():
        return None

    with tempfile.NamedTemporaryFile(suffix=".raw", delete=True) as tmp:
        tmp_path = tmp.name

        cmd = [
            "ffmpeg", "-y",
            "-i", str(audio_path),
            "-t", str(max_duration),
            "-acodec", "pcm_s16le",
            "-ar", "22050",
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

    hop_length = 512
    frame_length = 2048
    num_frames = (len(samples) - frame_length) // hop_length
    if num_frames < 10:
        return None

    energy = np.zeros(num_frames)
    for i in range(num_frames):
        start = i * hop_length
        frame = samples[start:start + frame_length]
        energy[i] = np.sqrt(np.mean(frame ** 2))

    energy = energy - np.mean(energy)
    sos = butter(4, [0.5 / (22050 / (2 * hop_length)), 5.0 / (22050 / (2 * hop_length))], btype="band", output="sos")
    envelope = sosfilt(sos, energy)

    min_bpm, max_bpm = 60, 180
    min_lag = int(22050 * 60.0 / max_bpm / hop_length)
    max_lag = int(22050 * 60.0 / min_bpm / hop_length)

    if len(envelope) < max_lag * 2:
        return None

    autocorr = np.correlate(envelope, envelope, mode="full")
    mid = len(autocorr) // 2
    ac = autocorr[mid + min_lag:mid + max_lag + 1]

    if len(ac) < 2:
        return None

    peak_idx = np.argmax(ac)
    lag = min_lag + peak_idx
    bpm = 60.0 / (lag * hop_length / 22050.0)

    return round(bpm, 1)
