"""Rellena metadatos faltantes de la biblioteca desde el nombre de archivo.

Para cada audio sin título/artista en tags, los escribe a partir del nombre
"Artista - Título.mp3" (ya normalizado por el renombrado). No toca lo que ya
tiene. No requiere red.
"""

import argparse
import re
from pathlib import Path

from mutagen import File as MutagenFile

AUDIO_EXTS = {".mp3", ".flac", ".ogg", ".m4a", ".opus", ".wav", ".wma"}


def missing_fields(path: Path) -> tuple[list[str], str, str]:
    """Devuelve (campos_faltantes, artista, título) sin modificar el archivo."""
    try:
        tags = MutagenFile(str(path), easy=True)
    except Exception:
        return [], "", ""
    if not tags:
        return [], "", ""
    missing = [k for k in ("title", "artist") if not tags.get(k)]
    if not missing:
        return [], "", ""
    stem = path.stem
    parts = re.split(r"\s+-\s+", stem, maxsplit=1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return [], "", ""
    return missing, parts[0].strip(), parts[1].strip()


def fill_file(path: Path) -> tuple[int, str]:
    """Escribe título/artista faltantes. Devuelve (n_campos_escritos, desc.)."""
    missing, artist, title = missing_fields(path)
    if not missing:
        return 0, ""
    try:
        tags = MutagenFile(str(path), easy=True)
    except Exception:
        return 0, ""
    if not tags:
        return 0, ""
    written = 0
    if "artist" in missing and artist:
        tags["artist"] = [artist]
        written += 1
    if "title" in missing and title:
        tags["title"] = [title]
        written += 1
    try:
        tags.save()
    except Exception:
        return 0, ""
    return written, f"{artist} - {title}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    files = sorted(
        p for p in args.root.rglob("*")
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS
    )
    filled = 0
    for p in files:
        missing, artist, title = missing_fields(p)
        if not missing:
            continue
        if args.apply:
            n, desc = fill_file(p)
            if n:
                filled += 1
                print(f"  [fill] {p.relative_to(args.root)} <- {desc}")
        else:
            print(f"  [preview] {p.relative_to(args.root)} <- "
                  f"{artist} - {title} (faltan: {', '.join(missing)})")
            filled += 1
    print(f"\n  Archivos con tags a rellenar: {filled} de {len(files)}")


if __name__ == "__main__":
    main()
