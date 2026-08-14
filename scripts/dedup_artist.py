#!/usr/bin/env python
"""Deduplica el artista repetido que queda tras limpiar webs.

"Artista - Artista - Título" -> "Artista - Título"
"siglas - Artista completo - Título" (prefijo) -> "Artista completo - Título"
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

AUDIO_EXTS = {".mp3", ".flac", ".wav", ".m4a", ".ogg", ".oga", ".opus"}
LOG_DIR = Path("log")
SPACE = re.compile(r"\s+")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def dedup(stem: str) -> str:
    parts = [p.strip() for p in stem.split(" - ")]
    if len(parts) < 3:
        return stem
    changed = True
    while changed and len(parts) > 2:
        changed = False
        a, b = norm(parts[0]), norm(parts[1])
        if a == b:
            parts.pop(0)
            changed = True
        elif a and b.startswith(a):
            parts.pop(0)
            changed = True
        else:
            break
    return " - ".join(parts)


def main() -> None:
    if len(sys.argv) < 2:
        print("Uso: dedup_artist.py <carpeta>...")
        sys.exit(2)
    LOG_DIR.mkdir(exist_ok=True)
    total = 0
    for arg in sys.argv[1:]:
        folder = Path(arg)
        logf = LOG_DIR / f"dedup_artist_{folder.name}.log"
        for path in sorted(folder.iterdir()):
            if not (path.is_file() and path.suffix.lower() in AUDIO_EXTS):
                continue
            stem = path.stem
            new_stem = dedup(stem)
            if new_stem == stem:
                continue
            target = path.with_name(new_stem + path.suffix)
            if target.exists():
                print(f"  !! DESTINO EXISTE: {target.name}")
                continue
            path.rename(target)
            total += 1
            with logf.open("a", encoding="utf-8") as fh:
                fh.write(f"{path.name}\t->\t{target.name}\n")
            print(f"  {folder.name}/{path.name}\n     -> {target.name}")
    print(f"\nRenombrados: {total}")


if __name__ == "__main__":
    main()