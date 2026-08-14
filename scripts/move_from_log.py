#!/usr/bin/env python
"""Mueve de una carpeta a sus géneros detectados según el log de inspect_genre.

Usa el log `log/makina_inspect.log` (nombre<TAB>género): por cada archivo cuyo
género detectado difiera del original (y no sea "sin género"), lo mueve a
`DEST/<Género>/` con su tag de género actualizado.
"""

import argparse
import sys
from pathlib import Path

from gestor_listas.renamer import (
    TrackInfo,
    INSTRUMENTAL_PATTERN,
    move_file,
    resolve_library_target,
)
from gestor_listas.audio import write_genre


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log", type=str, help="Log de inspect_genre (nombre<TAB>género).")
    ap.add_argument("source", type=str, help="Carpeta de origen.")
    ap.add_argument("dest", type=str, help="Carpeta de destino de la biblioteca.")
    ap.add_argument("original", type=str, default="Makina",
                    help="Género original a sacar de (por defecto Makina).")
    ap.add_argument("--apply", action="store_true", help="Mover de verdad.")
    args = ap.parse_args()

    source = Path(args.source)
    dest = Path(args.dest)
    moves = 0
    for line in Path(args.log).read_text(encoding="utf-8").splitlines():
        if "\t" not in line:
            continue
        name, genre = line.split("\t", 1)
        genre = genre.strip()
        if not genre or genre == args.original or genre == "sin género":
            continue
        if genre == "Remember":
            # La carpeta Remember se desmanteló en pasadas anteriores: aplicar
            # la regla vocal/instrumental (instrumental/dub -> Melodías, resto
            # -> Cantaditas), igual que en la re-clasificación original.
            genre = ("Melodías" if INSTRUMENTAL_PATTERN.search(name)
                     else "Cantaditas")
        path = source / name
        if not path.exists():
            print(f"  -> No existe: {name}")
            continue
        track = TrackInfo(title=Path(name).stem, artist="")
        target = resolve_library_target(dest / genre, track, path.suffix.lower())
        print(f"  {genre:12} <- {name}")
        if not args.apply:
            continue
        moved = move_file(path, target)
        if not moved:
            print(f"    ERROR moviendo {name}")
            continue
        if write_genre(moved, genre):
            print(f"    género {genre} guardado")
        moves += 1
    print(f"\nMover: {moves} (modo {'aplicar' if args.apply else 'previsualización'})")


if __name__ == "__main__":
    main()