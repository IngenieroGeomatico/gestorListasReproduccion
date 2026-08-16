#!/usr/bin/env python3
"""Audita la clasificación por género de la biblioteca bakala.

Para cada archivo de audio identifica la canción (huella AcoustID + MusicBrainz,
con rescates en cascada igual que tag_library) y deduce su subgénero con
`detect_genre` sobre los metadatos identificados (título/artista/álbum, que es
mucho más fiable que el nombre del archivo). Compara ese género con la carpeta
que lo contiene y genera un CSV de "candidatos mal clasificados".

No mueve nada: solo informa. La decisión de mover es del usuario, carpeta a
carpeta (igual que con el etiquetado).

Uso:
  python scripts/audit_genre.py                     # audita todas las carpetas
  python scripts/audit_genre.py --only Poky Reggae  # audita solo esas carpetas
  python scripts/audit_genre.py --start-from Trance  # sigue a partir de Trance
  python scripts/audit_genre.py --limit 500          # máximo por pasada

Cada pasada muestra un resumen por carpeta y appendea a:
  log/audit_genre.csv  (path, carpeta, genero_detectado, artista, titulo, album, fuente, score)
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

from gestor_listas.config import acoustid_api_key
from gestor_listas.renamer import (
    detect_genre,
    fingerprint_file,
    identify_track,
    is_audio_file,
    search_recording,
    track_from_filename,
    track_from_partial_tags,
    track_from_tags,
)

DEFAULT_LIBRARY = Path("/run/media/radi/SI-Nena!!!/MÚSICA/bakala")
DEFAULT_REPORT = Path(__file__).resolve().parent.parent / "log" / "audit_genre.csv"
MIN_SCORE = 0.5

# El detector devuelve nombres canónicos; los igualamos a la carpeta de destino.
# Si el género detectado apunta a una carpeta distinta a la que contiene el
# archivo, lo marcamos como candidato a mover.
GENRE_TO_FOLDER = {
    "Poky": "Poky",
    "Makina": "Makina",
    "Hardstyle": "Hardstyle",
    "Hardcore": "Hardcore",
    "Hardtrance": "Hardtrance",
    "Hands Up": "Hands Up",
    "Jumpstyle": "Jumpstyle",
    "Trance": "Trance",
    "Drum & Bass": "Drum & Bass",
    "Techno": "Techno",
    "House": "House",
    "Progressive": "Progressive",
    "Melodías": "Melodías",
    "Cantaditas": "Cantaditas",
    "Eurodance": "Eurodance",
    "Dance": "Dance",
    "Rave": "Rave",
    "Acid": "Acid",
    "Pop": "Pop",
    "Reggae": "Reggae",
    "Hip Hop": "Hip Hop",
    "Remember": "Remember",
    "EDM": "Dance",
    "Electro": "Dance",
    "Dubstep": "Hardstyle",
    "Reggaeton": "Dance",
    "Latin": "Dance",
    "Rock": "Pop",
    "Rumba": "Dance",
    "Flamenco": "Dance",
}

# Familias que se toleran entre sí (no son "mal clasificado").
TOLERATED = {
    frozenset({"Remember", "Remember_viejo"}),
    frozenset({"Trance", "Hardtrance"}),
    frozenset({"Hardstyle", "Hardcore"}),
    frozenset({"Makina", "Poky"}),
    frozenset({"Dance", "EDM"}),
}


def read_easy(path: Path) -> dict:
    from mutagen import File as MutagenFile
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
    }


def identify_one(path: Path, api_key: str) -> tuple:
    """Igual cascada que tag_library. Devuelve (TrackInfo|None, fuente, score)."""
    try:
        fp = fingerprint_file(str(path))
        if fp:
            duration, fingerprint = fp
            track = identify_track(api_key, duration, fingerprint, MIN_SCORE)
            if track:
                return track, "huella", track.score
        track = track_from_tags(path)
        if track:
            return track, "tags", track.score
        track = track_from_filename(path)
        if track:
            return track, "archivo", track.score
        track = search_recording(Path(path).stem)
        if track:
            return track, "busqueda", track.score
        track = track_from_partial_tags(path)
        if track:
            return track, "parcial", 0.0
    except Exception:
        pass
    return None, "", 0.0


def is_tolerated(folder: str, detected_folder: str | None) -> bool:
    if not detected_folder or detected_folder == folder:
        return True
    return frozenset({folder, detected_folder}) in TOLERATED


def run(
    library: Path,
    only: list[str] | None,
    start_from: str | None,
    limit: int,
    report: Path,
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

    print(f"Carpetas a auditar: {', '.join(d.name for d in folders)}")

    progress = load_state(progress_path_for(report))
    stats = {"ok": 0, "skipped": 0, "candidates": 0}
    processed = 0

    for folder in folders:
        files = sorted(
            p for p in folder.iterdir()
            if p.is_file() and is_audio_file(str(p))
        )
        if not files:
            print(f"\n  [{folder.name}] sin archivos de audio")
            continue

        folder_stats = {"ok": 0, "candidates": 0}
        print(f"\n=== {folder.name} ({len(files)} archivos) ===")
        for path in files:
            if str(path) in progress:
                stats["skipped"] += 1
                folder_stats["ok"] += 1
                continue

            if limit and processed >= limit:
                print(f"[--limit: {limit} archivos alcanzados en esta pasada]")
                print(
                    f"  {folder.name}: {folder_stats['ok']} ok, "
                    f"{folder_stats['candidates']} candidatos"
                )
                return stats

            processed += 1
            track, source, score = identify_one(path, api_key)
            folder_stats["ok"] += 1
            stats["ok"] += 1

            if track is None:
                # Sin identificación ni metadatos: no podemos auditar.
                save_progress(progress_path_for(report), path)
                continue

            detected = detect_genre(track.title or "", track.artist or "", track.album or "")
            detected_folder = GENRE_TO_FOLDER.get(detected) if detected else None

            if not is_tolerated(folder.name, detected_folder):
                stats["candidates"] += 1
                folder_stats["candidates"] += 1
                save_candidate(report, path, folder.name, detected,
                               track.artist, track.title, track.album, source, score)
                print(f"  ? {path.name!s:.52} -> {folder.name} -> {detected_folder}"
                      f" [{detected}] ({source}, {score:.2f})")

            save_progress(progress_path_for(report), path)
            # Pausa para respetar el límite de requests de MusicBrainz.
            if source in ("huella", "busqueda"):
                time.sleep(1)

        print(f"  {folder.name}: {folder_stats['ok']} ok, "
              f"{folder_stats['candidates']} candidatos")

    return stats


def load_state(report: Path) -> set[str]:
    done: set[str] = set()
    if report.exists():
        with report.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                done.add(row["path"])
    return done


def progress_path_for(report: Path) -> Path:
    return report.with_name(report.stem + "_progress.csv")


def save_progress(progress: Path, path: Path) -> None:
    write_header = not progress.exists() or progress.stat().st_size == 0
    if write_header:
        progress.parent.mkdir(parents=True, exist_ok=True)
    with progress.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["path"])
        if write_header:
            writer.writeheader()
        writer.writerow({"path": str(path)})


def save_candidate(report: Path, path: Path, folder: str, detected: str | None,
                   artist: str | None, title: str | None, album: str | None,
                   source: str, score: float) -> None:
    write_header = not report.exists() or report.stat().st_size == 0
    if write_header:
        report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["path", "folder", "detected", "artist", "title",
                            "album", "source", "score"]
        )
        if write_header:
            writer.writeheader()
        writer.writerow({
            "path": str(path),
            "folder": folder,
            "detected": detected or "",
            "artist": artist or "",
            "title": title or "",
            "album": album or "",
            "source": source,
            "score": f"{score:.2f}",
        })


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--library", "-l", type=Path, default=DEFAULT_LIBRARY)
    ap.add_argument("--only", nargs="+", default=None,
                    help="Auditar solo estas carpetas.")
    ap.add_argument("--start-from", default=None,
                    help="Auditar a partir de esta carpeta (inclusive).")
    ap.add_argument("--limit", type=int, default=0,
                    help="Máximo de archivos a auditar en ESTA pasada.")
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT,
                    help="CSV de candidatos (default: log/audit_genre.csv).")
    ap.add_argument("--key", default=None, help="Clave API de AcoustID.")
    args = ap.parse_args()

    key = args.key or acoustid_api_key()
    if not key:
        print("ERROR: falta la clave API de AcoustID (--key o ACOUSTID_API_KEY).",
              file=sys.stderr)
        return 2

    stats = run(args.library, args.only, args.start_from, args.limit,
                args.report, key)
    print("\n=== Resumen auditoría ===")
    print(f"  Auditar: {stats['ok']} | ya en informe: {stats['skipped']} | "
          f"candidatos a revisar: {stats['candidates']}")
    print(f"  Informe: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())