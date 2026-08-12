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

from .audio import write_rating
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


@dataclass
class TrackInfo:
    """Metadatos de una canción identificada."""

    title: str
    artist: str
    album: str | None = None
    year: str | None = None
    score: float = 0.0
    recording_id: str | None = None
    rating: float | None = None
    rating_count: int | None = None


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
            tracks.append(
                TrackInfo(
                    title=title or "Título desconocido",
                    artist=artist,
                    album=album,
                    year=year,
                    score=score,
                    recording_id=recording.get("id"),
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
    url = f"{MUSICBRAINZ_BASE}/recording/{track.recording_id}"
    params = {"inc": "releases ratings", "fmt": "json"}
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
    rating = data.get("rating")
    if isinstance(rating, dict):
        if rating.get("value") is not None:
            track.rating = float(rating["value"])
        if rating.get("count") is not None:
            track.rating_count = int(rating["count"])
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


def _process_file(
    path: Path, api_key: str, min_score: float, include_year: bool, apply: bool
) -> tuple[bool, bool]:
    """Procesa un archivo. Devuelve (ok, renombrado)."""
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
        print("  -> No se encontró ninguna coincidencia en AcoustID.")
        return False, False

    target = resolve_target(path, track, include_year)
    if track.score:
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
    print(f"  Nombre propuesto: {target.name}")

    if target == path:
        print("  El archivo ya tiene un nombre correcto.")
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
    return True, True


def run_rename(
    paths: list[Path] | list[str],
    recursive: bool = False,
    apply: bool = False,
    api_key: Optional[str] = None,
    min_score: float = MIN_SCORE,
    include_year: bool = False,
) -> dict[str, int]:
    """Lógica compartida entre el CLI principal y el main() de este módulo."""
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

    print(
        f"Procesando {len(files)} archivo(s) "
        f"({'modo aplicar' if apply else 'modo previsualización'})"
    )
    stats: dict[str, int] = {"scanned": len(files), "renamed": 0, "errors": 0}
    for i, path in enumerate(files):
        if i:
            time.sleep(REQUEST_DELAY)
        ok, renamed = _process_file(path, key, min_score, include_year, apply)
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
    args = parser.parse_args()

    run_rename(
        args.paths,
        recursive=args.recursive,
        apply=args.apply,
        api_key=args.api_key or None,
        min_score=args.min_score,
        include_year=args.year,
    )


if __name__ == "__main__":
    main()
