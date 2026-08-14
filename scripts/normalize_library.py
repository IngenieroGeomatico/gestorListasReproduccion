#!/usr/bin/env python
"""Normaliza mecánicamente los nombres de una carpeta de la biblioteca.

Corrige sin interpretación (fuente: el propio nombre del archivo):
   1. Decorar el ' - ' suelto inicial: " - Artista - Título" -> "Artista - Título"
  2. Doble separador: "Artista - - Título" -> "Artista - Título"
     y "Artista - - www.eltentaculo.info - Título" -> "Artista - Título"
  3. Prefijo de número de pista: "12. Tim Wokan - Título" -> "Tim Wokan - Título"

Estos patrones rompen el estándar 'Artista - Título' y no requieren huella.
No toca archivos sin esos patrones. La raíz por carpeta se pasa como argumento.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

AUDIO_EXTS = {".mp3", ".flac", ".wav", ".ogg", ".oga", ".opus", ".m4a", ".mp4", ".aac", ".wma", ".ape", ".alac"}
LEADING_DASH = re.compile(r"^\s*-\s+")
DOUBLE_DASH = re.compile(r"\s+-\s+-\s+")
TRACK_NUM = re.compile(r"^\d+\.[\s.]*")
MULTISPACE = re.compile(r"\s+")


def normalize_stem(stem: str) -> str:
    new = LEADING_DASH.sub("", stem)
    new = DOUBLE_DASH.sub(" - ", new)
    new = TRACK_NUM.sub("", new)
    # Limpia espacios dobles y guiones/espacios residuales de los bordes.
    new = MULTISPACE.sub(" ", new).strip(" -")
    return new


def normalize_folder(folder: Path, log_path: Path) -> int:
    changed = 0
    for path in sorted(folder.iterdir()):
        if not (path.is_file() and path.suffix.lower() in AUDIO_EXTS):
            continue
        stem = path.stem
        new_stem = normalize_stem(stem)
        if new_stem == stem:
            continue
        target = path.with_name(new_stem + path.suffix)
        if target.exists():
            print(f"  !! destino ya existe: {target.name}", file=sys.stderr)
            continue
        path.rename(target)
        changed += 1
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"{path.name}\t->\t{target.name}\n")
        print(f"  {folder.name}/{path.name}  ->  {target.name}")
    return changed


def main() -> None:
    if len(sys.argv) < 2:
        print("Uso: normalize_library.py <carpeta> [carpeta...]", file=sys.stderr)
        sys.exit(2)
    log_dir = Path("log")
    log_dir.mkdir(exist_ok=True)
    total = 0
    for arg in sys.argv[1:]:
        folder = Path(arg)
        logf = log_dir / f"normalize_{folder.name}.log"
        total += normalize_folder(folder, logf)
    print(f"\nRenombrados en total: {total}")


if __name__ == "__main__":
    main()