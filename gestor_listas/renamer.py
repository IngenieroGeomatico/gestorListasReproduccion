"""Renombrado de canciones por huella acústica (AcoustID + MusicBrainz).

Identifica una canción por su forma de onda (no por el nombre del archivo),
consulta AcoustID para encontrar grabaciones candidatas, enriquece con
metadatos de MusicBrainz y renombra el archivo como "Artista - Título".
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import acoustid
import requests
from mutagen import File as MutagenFile

from .audio import write_genre, write_rating
from .config import acoustid_api_key, resolve_ffmpeg

log = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {
    ".mp3",
    ".flac",
    ".wav",
    ".ogg",
    ".oga",
    ".opus",
    ".m4a",
    ".mp4",
    ".aac",
    ".wma",
    ".ape",
    ".alac",
}

MUSICBRAINZ_BASE = "https://musicbrainz.org/ws/2"
MUSICBRAINZ_HEADERS = {
    "User-Agent": "gestor-listas/0.1.0 (https://github.com/anomalyco/opencode)"
}

MIN_SCORE = 0.5

# Pausa entre canciones para respetar el límite de uso de las APIs
# (MusicBrainz pide ~1 req/seg; AcoustID permite hasta 3 req/seg).
REQUEST_DELAY = 1.0

ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
MULTISPACE = re.compile(r"\s+")

# Umbral de confianza (0-100, tal y como la devuelve MusicBrainz) para el
# rescate por búsqueda de texto: como estos candidatos se infieren del nombre
# del archivo, exigimos un mínimo de acierto para no renombrar a cualquier cosa.
SEARCH_MIN_SCORE = 30


@dataclass
class TrackInfo:
    """Metadatos de una canción identificada."""

    title: str
    artist: str
    album: str | None = None
    year: str | None = None
    score: float = 0.0
    recording_id: str | None = None
    release_id: str | None = None
    release_group_id: str | None = None
    rating: float | None = None
    rating_count: int | None = None
    genre: str | None = None
    source: str = ""


# ───────────────────────────── Huella acústica ───────────────────────────────


def _ensure_ffmpeg_on_path() -> None:
    """Asegura que audioread (usado por pyacoustid) encuentre un comando 'ffmpeg'.

    Prefiere el ffmpeg del sistema si ya está en el PATH. Si no, usa el binario
    empaquetado por `imageio-ffmpeg` (misma resolución que config.resolve_ffmpeg):
    como ese binario tiene nombre con versión (p. ej. ffmpeg-linux-x86_64-v7.0.2,
    o ...-win-....exe en Windows) y audioread solo busca el comando literal
    'ffmpeg'/'ffmpeg.exe', se expone con ese nombre en ~/.cache/gestor-listas/bin
    y se añade ese directorio al PATH.

    Cross-platform: en Windows el ejecutable es 'ffmpeg.exe' y los symlinks
    requieren privilegios de administrador, así que se copia el binario en vez de
    enlazarlo; en Unix se usa un symlink (barato).
    """
    if shutil.which("ffmpeg"):
        return
    try:
        exe = Path(resolve_ffmpeg())
    except Exception:
        return

    # Nombre de comando que audioread buscará en el PATH según el SO.
    command_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"

    # Si el binario resuelto ya se llama como el comando esperado, basta con
    # añadir su carpeta al PATH.
    if exe.name.lower() == command_name.lower():
        parent = str(exe.parent)
    else:
        bindir = Path.home() / ".cache" / "gestor-listas" / "bin"
        bindir.mkdir(parents=True, exist_ok=True)
        target = bindir / command_name
        if not target.exists():
            try:
                if os.name == "nt":
                    # symlink poco fiable en Windows: copiamos el binario.
                    shutil.copy2(exe, target)
                else:
                    target.symlink_to(exe)
            except OSError:
                return
        parent = str(bindir)

    if parent not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = parent + os.pathsep + os.environ.get("PATH", "")


def is_audio_file(path: str) -> bool:
    """Devuelve True si la extensión del archivo es de audio reconocida."""
    return Path(path).suffix.lower() in AUDIO_EXTENSIONS


def fingerprint_file(path: str) -> tuple[float, str] | None:
    """Genera la huella acústica de un archivo de audio.

    Devuelve una tupla (duración_en_segundos, huella) o None si falla.
    """
    _ensure_ffmpeg_on_path()
    try:
        return acoustid.fingerprint_file(path)
    except acoustid.NoBackendError:
        log.error(
            "No se encontró Chromaprint. Instálalo con: "
            "sudo apt install libchromaprint-tools"
        )
        raise
    except acoustid.FingerprintGenerationError as exc:
        log.warning("No se pudo generar huella para %s: %s", path, exc)
        return None


# ─────────────────────────── AcoustID + MusicBrainz ──────────────────────────


def _get_artist_name(artist: dict[str, Any]) -> str:
    return artist.get("name") or artist.get("id") or "Desconocido"


def _get_year(release: dict[str, Any]) -> str | None:
    for date_key in ("date", "release-date"):
        value = release.get(date_key)
        if value:
            return str(value)[:4]
    return None


def _parse_acoustid_result(data: dict[str, Any]) -> list[TrackInfo]:
    """Convierte la respuesta de AcoustID en una lista de TrackInfo."""
    tracks: list[TrackInfo] = []
    for result in data.get("results", []):
        score = result.get("score", 0.0)
        for recording in result.get("recordings", []):
            title = recording.get("title")
            artists = recording.get("artists", [])
            artist = ", ".join(_get_artist_name(a) for a in artists) or "Desconocido"
            releases = recording.get("releases", [])
            album = releases[0].get("title") if releases else None
            year = next((y for y in (_get_year(r) for r in releases) if y), None)
            release = releases[0] if releases else {}
            release_group = release.get("release-group") or {}
            tracks.append(
                TrackInfo(
                    title=title or "Título desconocido",
                    artist=artist,
                    album=album,
                    year=year,
                    score=score,
                    recording_id=recording.get("id"),
                    release_id=release.get("id"),
                    release_group_id=release_group.get("id"),
                )
            )
    return tracks


def lookup_fingerprint(api_key: str, duration: float, fingerprint: str) -> list[TrackInfo]:
    """Consulta AcoustID con una huella y devuelve los candidatos ordenados."""
    try:
        result = acoustid.lookup(api_key, fingerprint, duration, meta="recordings releases")
    except acoustid.WebServiceError as exc:
        log.error("Error consultando AcoustID: %s", exc)
        return []
    if result.get("status") != "ok":
        log.error("AcoustID devolvió estado: %s", result.get("status"))
        return []
    return _parse_acoustid_result(result)


def enrich_from_musicbrainz(track: TrackInfo) -> TrackInfo:
    """Completa metadatos de una grabación usando la API de MusicBrainz."""
    if not track.recording_id:
        return track
    # MusicBrainz pide ~1 req/s: esperamos 1s antes de cada consulta para no
    # saturar el servicio (los 503 se daban por lanzar peticiones en ráfaga).
    time.sleep(REQUEST_DELAY)
    url = f"{MUSICBRAINZ_BASE}/recording/{track.recording_id}"
    params = {"inc": "releases ratings genres", "fmt": "json"}
    try:
        resp = requests.get(url, params=params, headers=MUSICBRAINZ_HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("MusicBrainz falló para %s: %s", track.recording_id, exc)
        return track

    data = resp.json()
    if data.get("title"):
        track.title = data["title"]
    artist_credits = data.get("artist-credit", [])
    if artist_credits:
        track.artist = " ".join(
            credit.get("name", "")
            if not isinstance(credit, dict)
            else (credit.get("name", "") + credit.get("joinphrase", ""))
            for credit in artist_credits
        ).strip()
    releases = data.get("releases", [])
    if releases:
        if releases[0].get("title"):
            track.album = releases[0]["title"]
        year = _get_year(releases[0])
        if year:
            track.year = year
        track.release_id = releases[0].get("id") or track.release_id
        release_group = releases[0].get("release-group") or {}
        track.release_group_id = release_group.get("id") or track.release_group_id
    rating = data.get("rating")
    if isinstance(rating, dict):
        if rating.get("value") is not None:
            track.rating = float(rating["value"])
        if rating.get("count") is not None:
            track.rating_count = int(rating["count"])
    genres = data.get("genres") or []
    if genres:
        names = [g.get("name") for g in genres if g.get("name")]
        if names:
            track.genre = names[0]
    return track


def identify_track(
    api_key: str, duration: float, fingerprint: str, min_score: float = MIN_SCORE
) -> TrackInfo | None:
    """Identifica una canción por su huella. Devuelve el mejor candidato o None."""
    candidates = lookup_fingerprint(api_key, duration, fingerprint)
    candidates = [c for c in candidates if c.score >= min_score]
    if not candidates:
        return None
    best = candidates[0]
    return enrich_from_musicbrainz(best)


# ─────────────────────────────── Renombrado ──────────────────────────────────


def sanitize_component(text: str) -> str:
    """Limpia un fragmento (artista/título) para usarlo en un nombre de archivo.

    Las barras se usan como separador de artistas múltiples en las etiquetas,
    así que se convierten en ' & ' en lugar de eliminarse.
    """
    text = text.strip()
    text = text.replace("/", " & ")
    text = ILLEGAL_CHARS.sub("", text)
    text = MULTISPACE.sub(" ", text)
    text = text.rstrip(". ")
    return text[:180]


def build_filename(track: TrackInfo, extension: str, include_year: bool = False) -> str:
    """Construye el nombre de archivo estándar 'Artista - Título'."""
    artist = sanitize_component(track.artist)
    title = sanitize_component(track.title)
    name = f"{artist} - {title}"
    if include_year and track.year:
        name = f"{name} ({track.year})"
    return f"{name}{extension}"


def resolve_target(source: Path, track: TrackInfo, include_year: bool = False) -> Path:
    """Calcula la ruta destino evitando colisiones y sobreescrituras."""
    directory = source.parent
    extension = source.suffix.lower()
    candidate = build_filename(track, extension, include_year)

    target = directory / candidate
    if target == source:
        return target

    counter = 1
    stem = Path(candidate).stem
    while target.exists() and target.resolve() != source.resolve():
        candidate = f"{stem} ({counter}){extension}"
        target = directory / candidate
        counter += 1
    return target


def rename_file(source: Path, track: TrackInfo, include_year: bool = False) -> Path | None:
    """Renombra el archivo. Devuelve la nueva ruta o None si no cambia."""
    target = resolve_target(source, track, include_year)
    if target == source:
        return None
    try:
        source.rename(target)
    except OSError as exc:
        log.error("No se pudo renombrar %s a %s: %s", source, target, exc)
        return None
    log.info("Renombrado: %s -> %s", source.name, target.name)
    return target


def resolve_library_target(
    directory: Path, track: TrackInfo, extension: str, include_year: bool = False
) -> Path:
    """Calcula la ruta destino en la biblioteca evitando colisiones."""
    candidate = build_filename(track, extension, include_year)
    target = directory / candidate
    counter = 1
    stem = Path(candidate).stem
    while target.exists():
        candidate = f"{stem} ({counter}){extension}"
        target = directory / candidate
        counter += 1
    return target


def move_file(source: Path, target: Path) -> Path | None:
    """Mueve el archivo a su destino. Devuelve la nueva ruta o None si falla."""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            source.rename(target)
        except OSError:
            shutil.move(str(source), str(target))
    except OSError as exc:
        log.error("No se pudo mover %s a %s: %s", source, target, exc)
        return None
    log.info("Movido: %s -> %s", source, target)
    return target


# ─────────────────────────── Orquestación ────────────────────────────────────


def _collect_files(paths: list[Path], recursive: bool) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            if is_audio_file(str(path)):
                files.append(path)
            else:
                log.warning("Ignorando archivo no soportado: %s", path)
        elif path.is_dir():
            iterator = path.rglob("*") if recursive else path.glob("*")
            files.extend(p for p in iterator if p.is_file() and is_audio_file(str(p)))
        else:
            log.warning("Ruta no encontrada: %s", path)
    return sorted(set(files))


def track_from_tags(path: Path) -> TrackInfo | None:
    """Construye un TrackInfo desde las etiquetas title/artist del archivo.

    Sirve de respaldo cuando AcoustID no encuentra coincidencia: si el archivo
    trae metadatos internos, permite renombrarlo igualmente.
    """
    try:
        tags = MutagenFile(str(path), easy=True)
    except Exception:
        return None
    if not tags:
        return None

    def _first(value) -> str | None:
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if not value:
            return None
        return str(value).strip() or None

    title = _first(tags.get("title"))
    artist = _first(tags.get("artist"))
    if not title or not artist:
        return None
    year = _first(tags.get("date"))
    return TrackInfo(
        title=title,
        artist=artist,
        album=_first(tags.get("album")),
        year=str(year)[:4] if year else None,
    )


def track_from_partial_tags(path: Path) -> TrackInfo | None:
    """Rescate final: artista del tag + nombre de archivo como título.

    Algunos temas bakala vienen con la etiqueta de artista rellena pero sin
    título, y el nombre del archivo es el nombre popular por el que se conoce
    el tema (p. ej. "wenakom.mp3", "pokytazo .mp3"). Sin rating ni genre.
    """
    try:
        tags = MutagenFile(str(path), easy=True)
    except Exception:
        return None
    if not tags:
        return None

    def _first(value) -> str | None:
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if not value:
            return None
        return str(value).strip() or None

    artist = _first(tags.get("artist"))
    title = clean_filename_bits(Path(path).stem)
    if not artist and not title:
        return None
    if not artist:
        artist = "Artista desconocido"
    else:
        # Algunos temas traen el artista con un separador colgando
        # (p. ej. "urta navarro -"), que quedaría doble en el nombre final.
        artist = artist.rstrip(" -–—")
    if not title:
        title = Path(path).stem
    return TrackInfo(title=title, artist=artist, source="partial-tags")


# ─────────────────── Rescate: nombre de archivo y búsqueda ───────────────────

# Basura típica de descargas que hay que limpiar del nombre del archivo.
_FILENAME_JUNK = [
    r"\(?\d{3,4}p\)?",  # (480p) (720p) (1080p)
    r"\(?[A-Za-z0-9]+\.blogspot\.[A-Za-z0-9.]+\)?",  # [temazosdance.blogspot.com]
    r"\[[^\]]*(?:\.com|\.net|\.info|\.blogspot|wordpress)[^\]]*\]",  # [mp3hamster.net]
    r"\(?offici?al\s+(?:music\s+)?(?:video|lyrics?)\)?",  # (Official Video)
    r"\(?(?:HD|HQ|4K)\)?",
    r"_H\.mp3$",
    r"\b\d+p\b",  # 480p, 720p, 1080p
    r"\(?\b\d+kbits?\b\)?",  # (192kbit), 192kbps
]
FILENAME_JUNK_RE = re.compile(
    "|".join(_FILENAME_JUNK), re.IGNORECASE
)


def clean_filename_bits(name: str) -> str:
    """Limpia la basura de descarga de un nombre de archivo (sin extensión)."""
    text = name
    text = FILENAME_JUNK_RE.sub(" ", text)
    # Colapsa guiones bajos y espacios repetidos.
    text = text.replace("_", " ")
    text = MULTISPACE.sub(" ", text)
    return text.strip(" .-–—")


def track_from_filename(path: Path) -> TrackInfo | None:
    """Crea un TrackInfo a partir del propio nombre del archivo.

    Respaldo final cuando AcoustID no encuentra coincidencia y las etiquetas
    internas tampoco sirven: extrae "Artista - Título" del nombre, limpiando
    la basura típica de descargas web. Sin rating (no hay identificador).
    """
    stem = Path(path).stem
    parts = [clean_filename_bits(p) for p in re.split(r"\s+-\s+", stem)]
    if len(parts) < 2:
        return None
    artist, title = parts[0], parts[1]
    if not artist or not title:
        return None
    if len(artist) < 2 or len(title) < 2:
        return None
    return TrackInfo(title=title, artist=artist, source="filename")


def search_recording(query: str) -> TrackInfo | None:
    """Busca una grabación en MusicBrainz por texto (rescate arriesgado).

    Usado cuando la huella no coincide y no hay etiquetas ni nombre parseable.
    El usuario acepta el riesgo de que el primer resultado sea incorrecto.
    """
    time.sleep(REQUEST_DELAY)
    url = f"{MUSICBRAINZ_BASE}/recording/"
    params = {"query": query, "fmt": "json", "limit": 3}
    try:
        resp = requests.get(url, params=params, headers=MUSICBRAINZ_HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Búsqueda en MusicBrainz falló para %r: %s", query, exc)
        return None

    recordings = resp.json().get("recordings", [])
    if not recordings:
        return None
    best = recordings[0]
    title = best.get("title")
    if not title:
        return None
    artists = best.get("artist-credit", [])
    artist = " ".join(
        (a.get("name", "") if isinstance(a, dict) else str(a)) for a in artists
    ).strip()
    if not artist or artist.lower() in ("unknown artist", "various artists"):
        return None
    track = TrackInfo(
        title=title,
        artist=artist,
        recording_id=best.get("id"),
        score=max(float(best.get("score", 0)) / 100.0, 0.0),
        source="search",
    )
    # Sin puntuación de calidad suficiente, no nos fiamos del rescate.
    if track.score < SEARCH_MIN_SCORE / 100:
        return None
    return enrich_from_musicbrainz(track)


# ─────────────────────────── Detección de género ──────────────────────────────
#
# Cuando MusicBrainz no trae género (muy habitual en temas bakala/makina),
# detectamos el subgénero por palabras clave del nombre de archivo y metadatos.
# El orden importa: los estilos más específicos van primero para que ganen a
# los genéricos (p. ej. "hardstyle" antes que "dance" o "hardcore").

GENRE_KEYWORD_PRECEDENCE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Poky", ("poky", "poke")),
    ("Makina", ("makina", "mákina", "máquina", "maquina", "bakala")),
    ("Hardstyle", ("hardstyle", "hard style", "rawstyle")),
    ("Hardcore", ("hardcore", "hard core", "gabber", "gabba", "uptempo", "speedcore", "frenchcore", "hardtek", "terror")),
    ("Hardtrance", ("hardtrance", "hard trance", "hardtechno", "hard techno")),
    ("Remember", ("remember", "old school", "oldskool", "old skool")),
    ("Hands Up", ("hands up", "handsup", "handz up")),
    ("Jumpstyle", ("jumpstyle", "jump style")),
    ("Trance", ("trance", "psytrance", "goa", "uplifting")),
    ("Drum & Bass", ("dnb", "drum and bass", "drum & bass", "jungle", "breakcore")),
    ("Dubstep", ("dubstep", "brostep")),
    ("Electro", ("electro", "electrohouse", "electro house")),
    ("Techno", ("techno", "schranz", "acid techno")),
    ("House", ("house", "tech house", "deep house", "progressive house", "minimal")),
    ("Progressive", ("progressive", "progresivo")),
    ("Melodías", ("melodia", "melodía", "melodic", "melódico")),
    ("Cantaditas", ("cantadita", "cantaditas", "cantada", "cantado")),
    ("Eurodance", ("eurodance", "euro dance")),
    ("Dance", ("dance", "dancefloor", "club")),
    ("Rave", ("rave", "old school", "hardrave")),
    ("EDM", ("edm",)),
    ("Acid", ("acid",)),
    ("Rumba", ("rumba", "rumbeta")),
    ("Rock", ("rock", "punk", "metal", "indie", "grunge", "alternative")),
    ("Pop", ("pop", "synthpop", "synth pop")),
    ("Flamenco", ("flamenco", "sevillanas")),
    ("Reggaeton", ("reggaeton", "reggaetón", "perreo", "dembow")),
    ("Latin", ("salsa", "bachata", "merengue", "cumbia", "son")),
    ("Reggae", ("reggae", "dancehall", "ska", "ragga")),
    ("Hip Hop", ("hip hop", "hip-hop", "rap", "rnb", "r&b")),
)


def detect_genre(*texts: str) -> str | None:
    """Detecta el subgénero por palabras clave. Devuelve el primero que acierte.

    Las keywords cortas (<=4 letras) se comparan con límites de palabra para
    evitar falsos positivos por subcadena (p. ej. "son" dentro de "Simpson").
    Las compuestas y largas se buscan como subcadena (p. ej. "TechnoBase").
    """
    haystack = " ".join(t.lower() for t in texts if t)
    for genre, keywords in GENRE_KEYWORD_PRECEDENCE:
        for keyword in keywords:
            if genre == "Electro" and _has_derived_form(haystack):
                continue
            if len(keyword) <= 4:
                if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", haystack):
                    return genre
            elif keyword in haystack:
                return genre
    return None


_ELECTRO_DERIVED = re.compile(r"\belectr[oó]nic[ao]s?\b|\belectronic\b")

INSTRUMENTAL_PATTERN = re.compile(
    r"\b(instrumental|inst\.?|dub mix|dub ?version|karaoke|acapella\s-?\s?backing|"
    r"\bdub\b)(\b|\s|-|$)", re.IGNORECASE
)


def _has_derived_form(haystack: str) -> bool:
    """True si 'electro' aparece como parte de 'electrónico/electrónica'."""
    return bool(_ELECTRO_DERIVED.search(haystack))


def _genre_from_ancestors(path: Path, stop: Path | None = None) -> str | None:
    """Busca el género en los nombres de las carpetas desde la más cercana.

    Se detiene en `stop` (la raíz de origen de una pasada de biblioteca) para
    no heredar el nombre de la carpeta de colección (p. ej. `Remember`) como
    si fuera un género. En modo biblioteca, `stop` se pasa ya resuelto.
    """
    for directory in path.parents:
        if stop is not None and directory.resolve() == stop.resolve():
            break
        genre = detect_genre(directory.name)
        if genre:
            return genre
    return None


def _process_file(
    path: Path,
    api_key: str,
    min_score: float,
    include_year: bool,
    apply: bool,
    dest: Path | None = None,
    source_root: Path | None = None,
) -> tuple[bool, bool]:
    """Procesa un archivo. Devuelve (ok, renombrado/movido).

    Si `dest` es una carpeta (modo biblioteca), el archivo se mueve a
    `dest/<Género>/Artista - Título.ext` en lugar de renombrarse en su sitio.
    """
    try:
        return _process_file_inner(
            path, api_key, min_score, include_year, apply, dest, source_root
        )
    except FileNotFoundError:
        # El archivo pudo desaparecer (p. ej. una carpeta eliminada a mitad
        # de la pasada). No debe tumbar el proceso completo.
        print(f"  -> El archivo ya no existe (fue eliminado o movido).")
        return False, False
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"  -> Error inesperado: {exc}")
        return False, False


def _process_file_inner(
    path: Path,
    api_key: str,
    min_score: float,
    include_year: bool,
    apply: bool,
    dest: Path | None = None,
    source_root: Path | None = None,
) -> tuple[bool, bool]:
    print(f"\n[{path}]")
    fingerprint = fingerprint_file(str(path))
    if fingerprint is None:
        print("  -> No se pudo generar la huella acústica.")
        return False, False
    duration, fp = fingerprint

    track = identify_track(api_key, duration, fp, min_score)
    if not track:
        track = track_from_tags(path)
    if not track:
        track = track_from_filename(path)
    if not track:
        track = search_recording(Path(path).stem)
    if not track:
        track = track_from_partial_tags(path)
    if not track:
        print("  -> No se encontró ninguna coincidencia en AcoustID.")
        return False, False

    # Género: carpeta madre (clasificación explícita del usuario) → palabras
    # clave del nombre/título/artista → MusicBrainz. Se prueban todos los
    # niveles de directorios ancestros: un archivo dentro de
    # `-- MAKINA/Recopilatorio X/track.mp3` sigue heredando Makina de su
    # carpeta de género. El keyword prioriza sobre MusicBrainz porque MB suele
    # etiquetar géneros genéricos (p. ej. "Remember") que no clasifican nada.
    genre = _genre_from_ancestors(path, source_root)
    if not genre:
        genre = detect_genre(Path(path).stem, track.title, track.artist, track.album)
    if not genre and track.genre:
        # MusicBrainz puede devolver géneros crudos o múltiples ("Trance",
        # "alternative punk"). Se normalizan a la taxonomía por keywords.
        genre = detect_genre(track.genre)
    if not genre and dest is not None:
        # Último recurso en modo biblioteca: los remember/eurodance de los 90
        # casi siempre llevan vocal; si el título dice instrumental/dub, va a
        # Melodías, el resto a Cantaditas.
        title = track.title or Path(path).stem
        genre = "Melodías" if INSTRUMENTAL_PATTERN.search(title) else "Cantaditas"

    if dest is not None:
        return _process_library(path, track, genre, include_year, apply, dest)

    target = resolve_target(path, track, include_year)
    if track.source == "search":
        desc = (
            f"  Rescatada por búsqueda (score={track.score:.2f}): "
            f"{track.artist} - {track.title}"
        )
    elif track.source == "filename":
        desc = f"  Nombre del archivo: {track.artist} - {track.title}"
    elif track.score:
        desc = (
            f"  Coincidencia (score={track.score:.2f}): "
            f"{track.artist} - {track.title}"
        )
    else:
        desc = f"  Metadatos del archivo: {track.artist} - {track.title}"
    print(desc + (f" [{track.album}] {track.year}" if track.album or track.year else ""))
    if track.rating is not None:
        votes = f", {track.rating_count} votos" if track.rating_count else ""
        print(f"  Puntuación (MusicBrainz): {track.rating:.1f}/5 estrellas{votes}")
    if genre:
        print(f"  Género: {genre}")
    print(f"  Nombre propuesto: {target.name}")

    if target == path:
        print("  El archivo ya tiene un nombre correcto.")
        if apply and track.rating is not None:
            if write_rating(path, track.rating):
                print(f"  Puntuación guardada en metadatos: {track.rating:.1f}/5")
        if apply and genre:
            if write_genre(path, genre):
                print(f"  Género guardado en metadatos: {genre}")
        return True, False

    if not apply:
        print("  [previsualización] usa --apply para renombrar.")
        return True, False

    new_path = rename_file(path, track, include_year)
    if not new_path:
        return False, False

    if track.rating is not None:
        if write_rating(new_path, track.rating):
            print(f"  Puntuación guardada en metadatos: {track.rating:.1f}/5")
    if genre:
        if write_genre(new_path, genre):
            print(f"  Género guardado en metadatos: {genre}")
    return True, True


def _process_library(
    path: Path,
    track: TrackInfo,
    genre: str | None,
    include_year: bool,
    apply: bool,
    dest: Path,
) -> tuple[bool, bool]:
    """Mueve el archivo a la biblioteca `dest/<Género>/Artista - Título.ext`."""
    genre_dir = dest / (genre or "Sin género")
    target = resolve_library_target(
        genre_dir, track, path.suffix.lower(), include_year
    )

    if track.source == "search":
        desc = (
            f"  Rescatada por búsqueda (score={track.score:.2f}): "
            f"{track.artist} - {track.title}"
        )
    elif track.source == "filename":
        desc = f"  Nombre del archivo: {track.artist} - {track.title}"
    elif track.score:
        desc = (
            f"  Coincidencia (score={track.score:.2f}): "
            f"{track.artist} - {track.title}"
        )
    else:
        desc = f"  Metadatos del archivo: {track.artist} - {track.title}"
    print(desc + (f" [{track.album}] {track.year}" if track.album or track.year else ""))
    if track.rating is not None:
        votes = f", {track.rating_count} votos" if track.rating_count else ""
        print(f"  Puntuación (MusicBrainz): {track.rating:.1f}/5 estrellas{votes}")
    if genre:
        print(f"  Género: {genre}")
    print(f"  Mover a: {target}")

    if not apply:
        print("  [previsualización] usa --apply para mover.")
        return True, False

    new_path = move_file(path, target)
    if not new_path:
        return False, False

    if track.rating is not None:
        if write_rating(new_path, track.rating):
            print(f"  Puntuación guardada en metadatos: {track.rating:.1f}/5")
    if genre:
        if write_genre(new_path, genre):
            print(f"  Género guardado en metadatos: {genre}")
    return True, True


def run_rename(
    paths: list[Path] | list[str],
    recursive: bool = False,
    apply: bool = False,
    api_key: Optional[str] = None,
    min_score: float = MIN_SCORE,
    include_year: bool = False,
    dest: Optional[Path | str] = None,
) -> dict[str, int]:
    """Lógica compartida entre el CLI principal y el main() de este módulo.

    Si `dest` se indica (modo biblioteca), los archivos identificados se mueven
    a `dest/<Género>/Artista - Título.ext` en lugar de renombrarse en el sitio.
    """
    key = api_key or acoustid_api_key()
    if not key:
        print(
            "ERROR: falta la clave API de AcoustID.\n"
            "Obtén una gratis en https://acoustid.org/new-application\n"
            "y pásala con --key TU_CLAVE o la variable ACOUSTID_API_KEY.",
            file=sys.stderr,
        )
        sys.exit(2)

    files = _collect_files([Path(p) for p in paths], recursive)
    if not files:
        print("No se encontraron archivos de audio para procesar.")
        sys.exit(1)

    dest_path = Path(dest) if dest is not None else None
    if dest_path is not None:
        dest_path.mkdir(parents=True, exist_ok=True)

    resolved_roots = []
    for p in paths:
        r = Path(p).resolve()
        resolved_roots.append(r if r.is_dir() else r.parent)
    resolved_roots = sorted(set(resolved_roots))

    print(
        f"Procesando {len(files)} archivo(s) "
        f"({'modo aplicar' if apply else 'modo previsualización'})"
    )
    stats: dict[str, int] = {"scanned": len(files), "renamed": 0, "errors": 0}
    for i, path in enumerate(files):
        if i:
            time.sleep(REQUEST_DELAY)
        # Raíz de origen = la ruta pasada más profunda que aún es ancestro del
        # archivo. Permite a _genre_from_ancestors frizar la herencia en la
        # carpeta de colección (p. ej. `Remember`) sin tratarla como género.
        candidates = [
            r for r in resolved_roots if path.resolve().is_relative_to(r)
        ]
        source_root = max(candidates, key=lambda r: len(str(r))) if candidates else None
        ok, renamed = _process_file(
            path, key, min_score, include_year, apply, dest_path, source_root
        )
        if not ok:
            stats["errors"] += 1
        if renamed:
            stats["renamed"] += 1

    print_stats(stats)
    return stats


def print_stats(stats: dict[str, int]) -> None:
    print()
    print(f"  Escaneados: {stats['scanned']}")
    print(f"  Renombrados: {stats['renamed']}")
    print(f"  Errores: {stats['errors']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gestor-listas-rename",
        description=(
            "Renombra archivos de audio identificando la canción "
            "por huella acústica (AcoustID + MusicBrainz)."
        ),
    )
    parser.add_argument("paths", nargs="+", type=str, help="Archivos o carpetas a procesar.")
    parser.add_argument("-r", "--recursive", action="store_true", help="Procesa carpetas recursivamente.")
    parser.add_argument("--apply", action="store_true", help="Renombra realmente (sin esto solo previsualiza).")
    parser.add_argument("--key", dest="api_key", default="", help="Clave API de AcoustID (o ACOUSTID_API_KEY).")
    parser.add_argument("--min-score", type=float, default=MIN_SCORE,
                        help="Puntuación mínima de coincidencia (0-1, por defecto 0.5).")
    parser.add_argument("--year", action="store_true", help="Incluye el año: 'Artista - Título (Año)'.")
    parser.add_argument("--dest", default="",
                        help="Modo biblioteca: mover a DEST/<Género>/Artista - Título.ext (borra el origen).")
    args = parser.parse_args()

    run_rename(
        args.paths,
        recursive=args.recursive,
        apply=args.apply,
        api_key=args.api_key or None,
        min_score=args.min_score,
        include_year=args.year,
        dest=Path(args.dest) if args.dest else None,
    )


if __name__ == "__main__":
    main()
