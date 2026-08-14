#!/usr/bin/env python
"""Audita el género de una carpeta de la biblioteca sin mover nada.

Para cada archivo aplica la misma cascada del renamer (keyword del nombre →
género de MusicBrainz) e imprime el reparto. Solo lectura; útil para detectar
canciones mal clasificadas (p. ej. dentro de Makina que no son makina).
"""

import argparse
import sys
import time
from pathlib import Path
from collections import Counter
from typing import Optional

from gestor_listas.renamer import (
    detect_genre,
    fingerprint_file,
    identify_track,
    acoustid_api_key,
    is_audio_file,
)


def classify(path: Path, key: str) -> Optional[str]:
    genre = detect_genre(path.stem)
    if genre:
        return genre
    fp = fingerprint_file(str(path))
    if not fp:
        return None
    duration, fingerprint = fp
    try:
        track = identify_track(key, duration, fingerprint, 0.5)
    except Exception:
        return None
    if not track:
        return None
    if track.genre:
        genre = detect_genre(track.genre)
        if genre:
            return genre
    return detect_genre(path.stem, track.title, track.artist, track.album)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folder", nargs="+", type=str, help="Carpetas a auditar.")
    ap.add_argument("--show", action="store_true",
                    help="Muestra el listado completo (no solo el reparto).")
    ap.add_argument("--limit", type=int, default=0,
                    help="Audita solo N archivos (para pruebas rápidas).")
    args = ap.parse_args()

    key = acoustid_api_key()
    if not key:
        print("ERROR: falta ACOUSTID_API_KEY", file=sys.stderr)
        sys.exit(2)

    counts: Counter[str] = Counter()
    detail: list[tuple[str, str]] = []
    total = 0
    for folder in args.folder:
        root = Path(folder)
        for p in sorted(root.iterdir()):
            if not p.is_file() or not is_audio_file(str(p)):
                continue
            if args.limit and total >= args.limit:
                break
            total += 1
            genre = classify(p, key)
            counts[genre or "sin género"] += 1
            detail.append((p.name, genre or "sin género"))
            if genre is None or not args.limit:
                time.sleep(1)  # respetar rate limit de MusicBrainz
            if args.show:
                print(f"{p.name}\t{genre or 'sin género'}")
    print()
    print(f"Total: {total}")
    for g, n in counts.most_common():
        print(f"  {n:4d} {g}")


if __name__ == "__main__":
    main()