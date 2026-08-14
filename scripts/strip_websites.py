#!/usr/bin/env python
"""Elimina la basura 'www.<sitio>' incrustada en nombres de archivo.

Patrones típicos:
  "Artista - www.eltentaculo.info - Título"      -> "Artista - Título"
  "Titulo [www.clubmuzon.com]"                    -> "Titulo"
  "Titulo (www.primemusic.ru)"                    -> "Titulo"
  "Titulo {www.mp3failai.com}"                    -> "Titulo"
  "Artista (www.X) - Título"                      -> "Artista - Título"
  "Artista www.X - Título"                        -> "Artista - Título"
  "Artista --www.X - Artista - Título"            -> "Artista - Título" (dedup)

Mecánico y reversible (log). Uso: python strip_websites.py <carpeta>...
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

AUDIO_EXTS = {".mp3", ".flac", ".wav", ".m4a", ".ogg", ".oga", ".opus"}
LOG_DIR = Path("log")

WEB = re.compile(r"www\.\S+", re.IGNORECASE)
# Elimina segmento ' - www.X ' o ' www.X - ' o ' -www.X'
SEGMENT = re.compile(r"\s*-{1,2}\s*" + WEB.pattern + r"\s*-{1,2}")
# Elimina '[www.X]', '(www.X)', '{www.X}' y ' www.X' colgante
BRACKETS = re.compile(r"\s*[\[({]\s*" + WEB.pattern + r"\s*[\])}]\s*")
TRAILING = re.compile(r"\s+" + WEB.pattern + r"\s*$")
DOUBLE_SPACE = re.compile(r"\s{2,}")
MULTIDASH = re.compile(r"\s*-\s*-\s*")


def strip_websites(stem: str) -> str:
    new = SEGMENT.sub(" - ", stem)
    new = BRACKETS.sub(" ", new)
    new = TRAILING.sub("", new)
    new = WEB.sub("", new)
    new = MULTIDASH.sub(" - ", new)
    new = DOUBLE_SPACE.sub(" ", new).strip(" -")
    return new


def main() -> None:
    if len(sys.argv) < 2:
        print("Uso: strip_websites.py <carpeta>...")
        sys.exit(2)
    LOG_DIR.mkdir(exist_ok=True)
    total = 0
    for arg in sys.argv[1:]:
        folder = Path(arg)
        logf = LOG_DIR / f"strip_websites_{folder.name}.log"
        for path in sorted(folder.iterdir()):
            if not (path.is_file() and path.suffix.lower() in AUDIO_EXTS):
                continue
            stem = path.stem
            if "www." not in stem:
                continue
            new_stem = strip_websites(stem)
            if new_stem == stem:
                print(f"  sin cambio: {path.name}")
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