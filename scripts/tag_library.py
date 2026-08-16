#!/usr/bin/env python3
"""Etiqueta y renombra la biblioteca bakala, carpeta por carpeta y por lotes.

Por cada archivo de audio y de forma ESTRICTAMENTE secuencial (un archivo a la
vez, para no llenar RAM y respetar el límite de ~1 req/s de MusicBrainz):

  1. Identifica la canción por huella acústica (AcoustID + MusicBrainz), con
     rescates en cascada: tags internos -> nombre de archivo -> búsqueda MB.
  2. BPM: si el archivo no lo tiene (o --force-bpm), lo calcula y lo escribe,
     usando la familia de género de la carpeta como prior (mejora la detección).
  3. Género: escribe el tag de género con el nombre de la carpeta (la biblioteca
     ya está organizada por géneros) si el archivo no lo tiene.
  4. Rating: escribe el rating comunitario de MusicBrainz 0-5 si no lo tiene.
  5. Metadatos: rellena SOLO lo que falta (título/artista/álbum/año).
  6. Renombrado 'Artista - Título' (solo con --rename y --apply).

Es RESUMIBLE: guarda en un CSV de estado (log/tag_library_progress.csv) cada
archivo que ya se aplicó, y en la siguiente pasada se los salta. Puedes procesar
una carpeta hoy, otras mañana, y el estado conserva el progreso. Los modos de
tamaño de lote: --only (carpetas), --start-from (retomar), --limit (archivos en
esta pasada) y --limit-folder (lotes pequeños por carpeta).

Sin --apply solo MUESTRA lo que haría (previsualización, no toca nada).

Ejemplos:
  python scripts/tag_library.py                              # preview de todo
  python scripts/tag_library.py --only Hardstyle             # preview de una carpeta
  python scripts/tag_library.py --only Makina --apply        # aplicar solo Makina
  python scripts/tag_library.py --start-from Poky --apply    # retomar desde Poky
  python scripts/tag_library.py --limit-folder 25 --apply    # lotes de 25 por carpeta
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import requests
from mutagen import File as MutagenFile
from mutagen.flac import FLAC
from mutagen.id3 import ID3, POPM
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

from gestor_listas.audio import detect_bpm, has_cover, write_cover, write_genre, write_rating
from gestor_listas.bpm_analyzer import read_existing_bpm, write_bpm
from gestor_listas.config import acoustid_api_key
from gestor_listas.renamer import (
    TrackInfo,
    fingerprint_file,
    identify_track,
    is_audio_file,
    rename_file,
    resolve_target,
    search_recording,
    track_from_filename,
    track_from_partial_tags,
    track_from_tags,
)

DEFAULT_LIBRARY = Path("/run/media/radi/SI-Nena!!!/MÚSICA/bakala")
DEFAULT_STATE = Path(__file__).resolve().parent.parent / "log" / "tag_library_progress.csv"
DEFAULT_COVER_STATE = Path(__file__).resolve().parent.parent / "log" / "tag_library_covers.csv"
MIN_SCORE = 0.5

COVERART_BASE = "https://coverartarchive.org"
COVERART_HEADERS = {
    "User-Agent": "gestor-listas/0.1.0 (https://github.com/anomalyco/opencode)"
}

# Formatos con soporte completo para escribir tags (metadatos/género/rating/BPM).
TAGGABLE = {".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".mp4", ".aac", ".wav"}


# ───────────────────────────── Lectura de tags ─────────────────────────────


def read_easy(path: Path) -> dict:
    if path.suffix.lower() == ".wav":
        return _read_wave_ids(path)
    try:
        tags = MutagenFile(str(path), easy=True)
    except Exception:
        return {}
    if not tags:
        return {}

    def first(key):
        v = tags.get(key)
        if isinstance(v, (list, tuple)):
            v = v[0] if v else None
        return str(v).strip() if v else None

    return {
        "title": first("title"),
        "artist": first("artist"),
        "album": first("album"),
        "year": first("date"),
        "genre": first("genre"),
    }


def _read_wave_ids(path: Path) -> dict:
    """Lee metadatos de un WAV usando el contenedor WAVE de mutagen (ID3).

    Algunos WAV traen el tag ID3 al INICIO del archivo (antes del RIFF), que
    el contenedor WAVE de mutagen no sabe parsear; se lee el ID3 directo.
    """
    from mutagen.id3 import ID3 as ID3File
    from mutagen.wave import WAVE as Wave

    try:
        direct = ID3File(str(path))
        if len(direct) or next(iter(direct), None):
            def dframe(key):
                f = direct.get(key)
                if f is not None and f.text:
                    return str(f.text[0])
                return None
            return {
                "title": dframe("TIT2"),
                "artist": dframe("TPE1"),
                "album": dframe("TALB"),
                "year": dframe("TDRC"),
                "genre": dframe("TCON"),
            }
    except Exception:
        pass

    try:
        audio = Wave(str(path))
    except Exception:
        return {}
    tags = audio.tags
    if tags is None:
        return {}

    def frame(key):
        f = tags.get(key)
        if f is not None and f.text:
            return str(f.text[0])
        return None

    return {
        "title": frame("TIT2"),
        "artist": frame("TPE1"),
        "album": frame("TALB"),
        "year": frame("TDRC"),
        "genre": frame("TCON"),
    }


def folder_as_genre(folder_name: str) -> str:
    """Convierte el nombre de carpeta en tag de género ('Remember_viejo' -> 'Remember viejo')."""
    return folder_name.replace("_", " ").strip() or folder_name


def has_rating(path: Path) -> bool:
    ext = path.suffix.lower()
    try:
        if ext in (".mp3", ".wav"):
            from mutagen.wave import WAVE as Wave
            from mutagen.id3 import ID3
            tags = ID3(str(path)) if ext == ".mp3" else (Wave(str(path)).tags or None)
            if tags is None:
                return False
            for frame in tags.getall("POPM"):
                if frame.email == "MusicBrainz" and frame.rating:
                    return True
            return False
        if ext == ".flac":
            return bool(FLAC(str(path)).get("RATING"))
        if ext == ".opus":
            return bool(OggOpus(str(path)).get("RATING"))
        if ext in (".ogg", ".oga"):
            return bool(OggVorbis(str(path)).get("RATING"))
    except Exception:
        pass
    return False


# ─────────────────────── Escritura de metadatos (solo faltantes) ───────────


def fill_missing_meta(path: Path, track: TrackInfo) -> int:
    """Rellena título/artista/álbum/año SOLO si faltan. Devuelve nº campos escritos."""
    existing = read_easy(path)
    ext = path.suffix.lower()
    if ext not in TAGGABLE:
        return 0

    values = {
        "title": track.title if not existing.get("title") else None,
        "artist": track.artist if not existing.get("artist") else None,
        "album": track.album if not existing.get("album") else None,
        "year": track.year if not existing.get("year") else None,
    }
    if not any(values.values()):
        return 0

    if ext == ".wav":
        return _fill_wave_meta(path, values)

    written = 0
    try:
        tags = MutagenFile(str(path), easy=True)
        if not tags:
            return 0
        for key, val in values.items():
            if val:
                tags[key] = [val]
                written += 1
        tags.save()
    except Exception:
        return 0
    return written


def _fill_wave_meta(path: Path, values: dict) -> int:
    """Rellena metadatos ID3 en un WAV contenedor WAVE."""
    from mutagen.id3 import TALB, TDRC, TIT2, TPE1
    from mutagen.wave import WAVE as Wave
    map_keys = {
        "title": "TIT2", "artist": "TPE1", "album": "TALB", "year": "TDRC",
    }
    frame_types = {
        "title": TIT2, "artist": TPE1, "album": TALB, "year": TDRC,
    }
    written = 0
    try:
        audio = Wave(str(path))
        if audio.tags is None:
            audio.add_tags()
        for key, val in values.items():
            if val:
                audio.tags[map_keys[key]] = frame_types[key](encoding=3, text=val)
                written += 1
        audio.save()
    except Exception:
        return 0
    return written


def count_missing_meta(path: Path, track: TrackInfo) -> int:
    """Campos (título/artista/álbum/año) que faltan y se rellenarían."""
    existing = read_easy(path)
    return sum(
        1
        for key, attr in (("title", "title"), ("artist", "artist"),
                          ("album", "album"), ("year", "year"))
        if not existing.get(key) and getattr(track, attr)
    )


def fetch_cover(track: TrackInfo) -> bytes | None:
    """Descarga la carátula del Cover Art Archive usando el release ID.

    MusicBrainz aloja las portadas de los lanzamientos en coverartarchive.org,
    accesible sin clave API. Devuelve los bytes de la imagen o None si no hay.
    """
    release_ids = [track.release_group_id, track.release_id]
    if not any(release_ids):
        # Identificados por tags/nombre (sin IDs de MB): buscamos el
        # release-group por artista+título para poder pedir su portada.
        searchable = _cover_searchable(track)
        if searchable:
            try:
                found = search_recording(searchable)
                if found:
                    release_ids = [found.release_group_id, found.release_id]
            except Exception:
                release_ids = []
    for release_id in release_ids:
        if not release_id:
            continue
        url = f"{COVERART_BASE}/release-group/{release_id}/front-500"
        try:
            resp = requests.get(
                url, headers=COVERART_HEADERS, timeout=15, allow_redirects=True
            )
            if resp.status_code == 200 and resp.content:
                return resp.content
        except requests.RequestException:
            continue
    return None


def fetch_cover_deezer(title: str | None, artist: str | None) -> bytes | None:
    """Descarga la portada del álbum desde Deezer (API pública, sin clave).

    Deezer tiene mucha mejor cobertura de música electrónica/bakala que el
    Cover Art Archive de MusicBrainz. Devuelve los bytes de la imagen (500px)
    o None si no encuentra nada.
    """
    import re
    title = (title or "").strip()
    artist = (artist or "").strip()
    if not title:
        return None
    relaxed = re.sub(r"[()\[\]!?.,:;'\"&+\-]", " ", title).strip()
    queries = [f'artist:"{artist}" track:"{title}"']
    if artist:
        queries.append(f'{relaxed} {artist}')
    queries.append(f'track:"{relaxed}"')
    seen: set[str] = set()
    for query in queries:
        if query in seen:
            continue
        seen.add(query)
        try:
            resp = requests.get(
                "https://api.deezer.com/search",
                params={"q": query, "limit": 1},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json().get("data") or []
            if not data:
                continue
            cover_url = (data[0].get("album") or {}).get("cover_big")
            if not cover_url:
                continue
            img = requests.get(cover_url, timeout=20)
            if img.status_code == 200 and img.content:
                return img.content
        except requests.RequestException:
            continue
    return None


def _cover_searchable(track: TrackInfo) -> str | None:
    """Consulta de búsqueda para portadas cuando no hay ID de MusicBrainz."""
    import re
    title = re.sub(r"[()\[\]!?.,:;'\"&+\-]", " ", track.title or "").strip()
    artist = (track.artist or "").strip().lower()
    if not title or "desconocido" in artist:
        return None
    if not title.replace(" ", ""):
        return None
    return f'artist:"{track.artist}" AND recording:"{title}"'


# ───────────────────────────────── Identificación ──────────────────────────


def identify_one(path: Path, api_key: str, min_score: float) -> TrackInfo | None:
    """Huella -> AcoustID/MB, con rescates en cascada. Nunca lanza."""
    try:
        fp = fingerprint_file(str(path))
        if fp:
            duration, fingerprint = fp
            track = identify_track(api_key, duration, fingerprint, min_score)
            if track:
                return track
        track = track_from_tags(path)
        if track:
            return track
        track = track_from_filename(path)
        if track:
            return track
        track = search_recording(Path(path).stem)
        if track:
            return track
        return track_from_partial_tags(path)
    except Exception:
        return None


# ─────────────────────────── Procesado de un archivo ────────────────────────


def process_file(
    path: Path,
    folder_genre: str,
    api_key: str,
    min_score: float,
    include_year: bool,
    do_rename: bool,
    apply: bool,
    force_bpm: bool,
) -> dict:
    """Prepara y (si apply) aplica todos los cambios a un archivo.

    Devuelve un dict con el resultado (campos escritos / propuestos ↔ path).
    """
    info: dict = {
        "path": str(path),
        "bpm": None,
        "bpm_existing": False,
        "bpm_written": False,
        "rating_written": False,
        "genre_written": False,
        "meta_written": 0,
        "cover_written": False,
        "renamed": False,
        "proposed_name": None,
        "mb_rating": None,
        "notes": [],
    }

    track = identify_one(path, api_key, min_score)

    # 1) BPM: si falta (o --force-bpm), lo calcula con el prior de la carpeta.
    existing_bpm = read_existing_bpm(path)
    if existing_bpm is not None and not force_bpm:
        info["bpm"] = existing_bpm
        info["bpm_existing"] = True
    else:
        try:
            bpm = detect_bpm(path, genre=folder_genre)
            info["bpm"] = round(bpm, 1) if bpm else None
            if bpm and apply and write_bpm(path, bpm):
                info["bpm_written"] = True
        except Exception:
            pass

    # 2) Género de carpeta (solo si falta).
    genre_label = folder_as_genre(folder_genre)
    if not read_easy(path).get("genre"):
        if apply:
            if path.suffix.lower() in TAGGABLE and write_genre(path, genre_label):
                info["genre_written"] = True
            else:
                info["notes"].append(f"género no escribible en {path.suffix}")
        else:
            info["genre_written"] = "pendiente"

    # 3) Rating de MusicBrainz (solo si falta y MB lo conoce).
    if track is not None:
        info["mb_rating"] = track.rating
    if track is not None and track.rating is not None and not has_rating(path):
        if apply:
            if write_rating(path, track.rating):
                info["rating_written"] = True
            else:
                info["notes"].append(f"rating no escribible en {path.suffix}")
        else:
            info["rating_written"] = "pendiente"
    elif track is None:
        info["notes"].append("sin identificación (no hay metadatos ni rating MB)")
    elif track.rating is None:
        info["notes"].append("MusicBrainz sin rating")
    elif has_rating(path):
        info["notes"].append("ya tenía rating")

    # 4) Metadatos faltantes (título/artista/álbum/año).
    if track is not None:
        if apply:
            info["meta_written"] = fill_missing_meta(path, track)
        else:
            info["meta_written"] = count_missing_meta(path, track)

    # 5) Carátula del Cover Art Archive (solo si no la tiene; metadatos).
    track_can_cover = track is not None and (
        track.release_group_id is not None or track.release_id is not None
    )
    if track_can_cover and not has_cover(path):
        cover = None if not apply else fetch_cover(track)
        if apply:
            if cover and path.suffix.lower() in TAGGABLE and write_cover(path, cover):
                info["cover_written"] = True
            elif cover and path.suffix.lower() not in TAGGABLE:
                info["notes"].append(f"carátula no escribible en {path.suffix}")
            else:
                info["notes"].append("sin carátula en el Cover Art Archive")
        else:
            info["cover_written"] = "pendiente"

    # 6) Renombrar 'Artista - Título'.
    if do_rename and track is not None:
        target = resolve_target(path, track, include_year)
        if target != path:
            info["proposed_name"] = target.name
            if apply:
                new_path = rename_file(path, track, include_year)
                if new_path:
                    info["renamed"] = True
                    info["path"] = str(new_path)
        else:
            info["notes"].append("el nombre ya es correcto")

    return info


# ─────────────────────────── Estado (reanudación) ───────────────────────────


def load_state(state: Path) -> set[str]:
    done: set[str] = set()
    if state.exists():
        with state.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                done.add(row["path"])
    return done


def save_row(state: Path, info: dict) -> None:
    write_header = not state.exists() or state.stat().st_size == 0
    if write_header:
        state.parent.mkdir(parents=True, exist_ok=True)
    with state.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["path", "bpm", "rating", "genre", "meta", "renamed"]
        )
        if write_header:
            writer.writeheader()
        writer.writerow({
            "path": info.get("path", ""),
            "bpm": info.get("bpm") if info.get("bpm") is not None else "",
            "rating": "1" if info.get("rating_written") else "",
            "genre": "1" if info.get("genre_written") else "",
            "meta": info.get("meta_written", 0),
            "renamed": "1" if info.get("renamed") else "",
        })


# ──────────────────────────── Carátulas en masa ──────────────────────────────


def run_covers(
    library: Path,
    only: list[str] | None,
    start_from: str | None,
    limit: int,
    apply: bool,
    state_file: Path,
    api_key: str,
) -> dict:
    """Rellena la carátula (Cover Art Archive) de los archivos que no la tienen.

    Usa su propio CSV de estado (log/tag_library_covers.csv) para ser resumible
    SIN pisar el progreso del etiquetado: los archivos ya etiquetados se siguen
    saltando en tag_library_progress.csv, pero aquí se reescanean para obtener la
    portada. Solo reescribe si el archivo no tiene imagen incrustada.
    """
    if not library.is_dir():
        print(f"ERROR: {library} no es una carpeta.")
        sys.exit(2)

    folders = sorted(d for d in library.iterdir() if d.is_dir() and not d.name.startswith("."))
    if only:
        wanted = set(only)
        folders = [d for d in folders if d.name in wanted]
        if not folders:
            print(f"ERROR: no existen carpetas: {', '.join(only)}")
            sys.exit(2)
    elif start_from:
        try:
            idx = next(i for i, d in enumerate(folders) if d.name == start_from)
        except StopIteration:
            print(f"ERROR: no existe la carpeta --start-from: {start_from}")
            sys.exit(2)
        folders = folders[idx:]

    print(f"Carpetas a procesar: {', '.join(d.name for d in folders)}")
    print(f"Modo: {'APLICAR' if apply else 'previsualización'} (solo carátulas)")

    done = load_state(state_file)
    stats = {"ok": 0, "errors": 0, "skipped": 0, "written_cover": 0, "already": 0}
    processed = 0

    for folder in folders:
        files = sorted(
            p for p in folder.iterdir()
            if p.is_file() and is_audio_file(str(p))
        )
        if not files:
            print(f"\n  [{folder.name}] sin archivos de audio")
            continue

        print(f"\n=== {folder.name} ({len(files)} archivos) ===")
        for path in files:
            if str(path) in done:
                stats["skipped"] += 1
                continue

            if limit and processed >= limit:
                print(f"[--limit: {limit} archivos alcanzados en esta pasada]")
                return stats

            processed += 1
            if has_cover(path):
                stats["already"] += 1
                if apply:
                    save_row(state_file, {"path": str(path)})
                continue

            # Fuente rápida: tags ya rellenados (sin huella acústica).
            existing = read_easy(path)
            cover_data = None
            source = ""
            if existing.get("title"):
                cover_data = fetch_cover_deezer(existing["title"], existing.get("artist"))
                source = "Deezer"
            if not cover_data:
                import time
                time.sleep(1)
                track = identify_one(path, api_key, MIN_SCORE)
                if track is not None:
                    cover_data = fetch_cover(track)
                    source = "Cover Art Archive"

            if not cover_data:
                stats["errors"] += 1
                if apply:
                    save_row(state_file, {"path": str(path)})
                print(f"  {path.name!s:.60} -> sin portada (Deezer ni CAA)")
                continue

            if not apply:
                stats["ok"] += 1
                print(f"  {path.name!s:.60} -> portada {source} ({len(cover_data)} B)")
                continue

            if write_cover(path, cover_data):
                stats["ok"] += 1
                stats["written_cover"] += 1
            else:
                stats["errors"] += 1
            save_row(state_file, {"path": str(path)})

    return stats


# ──────────────────────────────── Orquestación ──────────────────────────────


def run(
    library: Path,
    only: list[str] | None,
    start_from: str | None,
    limit: int,
    limit_folder: int,
    apply: bool,
    rename: bool,
    include_year: bool,
    min_score: float,
    force_bpm: bool,
    state_file: Path,
    api_key: str,
) -> dict:
    if not library.is_dir():
        print(f"ERROR: {library} no es una carpeta.")
        sys.exit(2)

    folders = sorted(d for d in library.iterdir() if d.is_dir() and not d.name.startswith("."))

    if only:
        wanted = set(only)
        folders = [d for d in folders if d.name in wanted]
        if not folders:
            print(f"ERROR: no existen carpetas: {', '.join(only)}")
            sys.exit(2)
    elif start_from:
        try:
            idx = next(i for i, d in enumerate(folders) if d.name == start_from)
        except StopIteration:
            print(f"ERROR: no existe la carpeta --start-from: {start_from}")
            sys.exit(2)
        folders = folders[idx:]

    print(f"Carpetas a procesar: {', '.join(d.name for d in folders)}")
    print(f"Modo: {'APLICAR' if apply else 'previsualización'} | "
          f"renombrar: {'sí' if rename else 'no'}")

    done_paths = load_state(state_file)

    stats = {"ok": 0, "errors": 0, "skipped": 0, "written_bpm": 0, "written_rating": 0,
             "written_genre": 0, "written_meta": 0, "written_cover": 0, "renamed": 0}
    processed = 0

    for folder in folders:
        files = sorted(
            p for p in folder.iterdir()
            if p.is_file() and is_audio_file(str(p))
        )
        if not files:
            print(f"\n  [{folder.name}] sin archivos de audio")
            continue

        if limit_folder > 0:
            files = files[:limit_folder]

        print(f"\n=== {folder.name} ({len(files)} archivos) ===")
        for path in files:
            if str(path) in done_paths:
                stats["skipped"] += 1
                continue

            if limit and processed >= limit:
                print(f"[--limit: {limit} archivos alcanzados en esta pasada]")
                return stats

            processed += 1
            info = process_file(
                path, folder.name, api_key, min_score, include_year,
                rename, apply, force_bpm,
            )

            if not apply:
                print(f"  {path.name!s:.60}")
                if info["bpm"]:
                    estado = "ya tenía" if info["bpm_existing"] else "se calcularía"
                    print(f"    bpm: {info['bpm']} ({estado})")
                if info["genre_written"] == "pendiente":
                    print(f"    género: '{folder_as_genre(folder.name)}' (pendiente)")
                if info["rating_written"] == "pendiente":
                    print(f"    rating: {info['mb_rating']} estrellas (pendiente)")
                if info["meta_written"]:
                    print(f"    rellenará {info['meta_written']} campo(s) de metadatos")
                if info["cover_written"] == "pendiente":
                    print("    carátula (pendiente, Cover Art Archive)")
                if info["proposed_name"]:
                    print(f"    renombrará a: {info['proposed_name']}")
                for note in info["notes"]:
                    print(f"    · {note}")
                stats["ok"] += 1
                continue

            stats["ok"] += 1
            if info["bpm_written"]:
                stats["written_bpm"] += 1
            if info["rating_written"]:
                stats["written_rating"] += 1
            if info["genre_written"]:
                stats["written_genre"] += 1
            if info["meta_written"]:
                stats["written_meta"] += info["meta_written"]
            if info["cover_written"]:
                stats["written_cover"] += 1
            if info["renamed"]:
                stats["renamed"] += 1
            save_row(state_file, info)

    return stats


# ──────────────────────────────────── CLI ───────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--library", "-l", type=Path, default=DEFAULT_LIBRARY)
    ap.add_argument("--only", nargs="+", default=None,
                    help="Procesar solo estas carpetas de género.")
    ap.add_argument("--start-from", default=None,
                    help="Retomar a partir de esta carpeta (inclusive).")
    ap.add_argument("--limit", type=int, default=0,
                    help="Máximo de archivos a procesar en ESTA pasada (0 = sin límite).")
    ap.add_argument("--limit-folder", type=int, default=0,
                    help="Máximo de archivos por carpeta (lotes pequeños).")
    ap.add_argument("--apply", action="store_true",
                    help="ESCRIBE los cambios (sin esto solo previsualiza).")
    ap.add_argument("--rename", action="store_true",
                    help="Además de etiquetar, renombra a 'Artista - Título'.")
    ap.add_argument("--year", action="store_true",
                    help="En el renombrado, incluir año: 'Artista - Título (año)'.")
    ap.add_argument("--min-score", type=float, default=MIN_SCORE,
                    help="Puntuación mínima de coincidencia acoustid (0-1).")
    ap.add_argument("--force-bpm", action="store_true",
                    help="Recalcular y sobrescribir BPM aunque ya exista.")
    ap.add_argument("--state", type=Path, default=DEFAULT_STATE,
                    help="CSV de estado para reanudar (default: log/tag_library_progress.csv).")
    ap.add_argument("--key", default=None,
                    help="Clave API de AcoustID (o variable ACOUSTID_API_KEY).")
    ap.add_argument("--covers", action="store_true",
                    help="Modo solo carátulas (Cover Art Archive) con estado propio.")
    ap.add_argument("--cover-state", type=Path, default=DEFAULT_COVER_STATE,
                    help="CSV de estado de carátulas (default: log/tag_library_covers.csv).")
    args = ap.parse_args()

    key = args.key or acoustid_api_key()
    if not key:
        print(
            "ERROR: falta la clave API de AcoustID.\n"
            "Obtén una gratis en https://acoustid.org/new-application\n"
            "y pásala con --key TU_CLAVE o ponla como ACOUSTID_API_KEY en .env.",
            file=sys.stderr,
        )
        return 2

    if args.covers:
        stats = run_covers(
            library=args.library,
            only=args.only,
            start_from=args.start_from,
            limit=args.limit,
            apply=args.apply,
            state_file=args.cover_state,
            api_key=key,
        )
        print("\n=== Resumen (carátulas) ===")
        print(f"  OK: {stats['ok']} | sin portada/noid: {stats['errors']} | "
              f"ya procesados: {stats['skipped']} | ya tenían: {stats['already']}")
        print(f"  Carátulas escritas: {stats['written_cover']}")
        print(f"  Estado (para reanudar): {args.cover_state}")
        return 0

    stats = run(
        library=args.library,
        only=args.only,
        start_from=args.start_from,
        limit=args.limit,
        limit_folder=args.limit_folder,
        apply=args.apply,
        rename=args.rename,
        include_year=args.year,
        min_score=args.min_score,
        force_bpm=args.force_bpm,
        state_file=args.state,
        api_key=key,
    )

    print("\n=== Resumen ===")
    print(f"  OK: {stats['ok']} | errores: {stats['errors']} | ya procesados: {stats['skipped']}")
    print(f"  BPM escritos: {stats['written_bpm']}")
    print(f"  Ratings escritos: {stats['written_rating']}")
    print(f"  Géneros escritos: {stats['written_genre']}")
    print(f"  Campos de metadatos rellenados: {stats['written_meta']}")
    print(f"  Carátulas escritas: {stats['written_cover']}")
    print(f"  Renombrados: {stats['renamed']}")
    print(f"  Estado (para reanudar): {args.state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())