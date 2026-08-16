#!/usr/bin/env python3
"""Calcula y escribe el BPM de la biblioteca bakala por lotes de N archivos.

Procesa los archivos de audio en LOTES (por defecto 200) con un Pool de
procesos (limitado a las CPUs disponibles). Por cada archivo:

  * Si ya tiene tag de BPM (y no --force) lo salta.
  * Si no, calcula el BPM con detect_bpm usando el nombre de la carpeta de
    género como prior (la biblioteca ya está organizada por géneros).

Es RESUMIBLE: cada archivo procesado se guarda en un CSV de estado
(log/bpm_analysis.csv) y en la siguiente pasada solo procesa los que falten.
Cada lote imprime una línea de resumen a stdout (con flush) que se puede
seguir en tiempo real en log/calc_bpm.log.

Ejemplos:
  python scripts/calc_bpm.py --batch 200
  python scripts/calc_bpm.py --batch 200 --force      # recalcular todo
  python scripts/calc_bpm.py --library /ruta/otra     # otra biblioteca
"""

from __future__ import annotations

import argparse
import csv
import multiprocessing as mp
import sys
import time
from pathlib import Path

from gestor_listas.audio import detect_bpm
from gestor_listas.bpm_analyzer import AUDIO_EXTENSIONS, read_existing_bpm, write_bpm

DEFAULT_LIBRARY = Path("/run/media/radi/SI-Nena!!!1/MÚSICA/bakala")
DEFAULT_STATE = Path(__file__).resolve().parent.parent / "log" / "bpm_analysis.csv"


def audio_files(root: Path) -> list[tuple[Path, str]]:
    """Archivos de audio ordenados, con el nombre de su carpeta de género."""
    out: list[tuple[Path, str]] = []
    for folder in sorted(d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")):
        for path in sorted(
            p for p in folder.rglob("*")
            if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
        ):
            out.append((path, folder.name))
    return out


def load_state(state: Path) -> set[str]:
    done: set[str] = set()
    if state.exists():
        with state.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                done.add(row["path"])
    return done


def save_row(state: Path, path: Path, bpm: float | None, error: bool) -> None:
    write_header = not state.exists() or state.stat().st_size == 0
    if write_header:
        state.parent.mkdir(parents=True, exist_ok=True)
    with state.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["path", "bpm", "error"])
        if write_header:
            writer.writeheader()
        writer.writerow({
            "path": str(path),
            "bpm": "" if bpm is None else round(bpm, 1),
            "error": "1" if error else "",
        })


def _worker(args: tuple) -> dict:
    """Analiza UN archivo y escribe el tag. Devuelve el resultado (sin I/O de estado)."""
    path, genre, force = args
    if not force and read_existing_bpm(path) is not None:
        return {"path": str(path), "bpm": None, "skipped": True, "error": False}
    try:
        bpm = detect_bpm(path, genre=genre)
    except Exception:
        return {"path": str(path), "bpm": None, "skipped": False, "error": True}
    if bpm is None:
        return {"path": str(path), "bpm": None, "skipped": False, "error": True}
    ok = False
    try:
        ok = write_bpm(path, bpm)
    except Exception:
        ok = False
    return {"path": str(path), "bpm": bpm, "skipped": False, "error": not ok}


def run(library: Path, batch: int, force: bool, workers: int, state: Path) -> int:
    all_files = audio_files(library)
    done = load_state(state)
    pending = [(p, g) for p, g in all_files if str(p) not in done]

    print(f"Biblioteca: {library}")
    print(f"Archivos: {len(all_files)} | ya en estado: {len(all_files) - len(pending)} | pendientes: {len(pending)}")
    print(f"Lotes de {batch} archivos, {workers} procesos (force={force})")
    sys.stdout.flush()

    total_start = time.time()
    batches = (len(pending) + batch - 1) // batch or 1
    for i in range(0, len(pending), batch):
        chunk = pending[i:i + batch]
        num, of = i // batch + 1, batches
        t0 = time.time()
        with mp.Pool(workers) as pool:
            results = pool.map(_worker, [(p, g, force) for p, g in chunk])

        written = sum(1 for r in results if not r["skipped"] and not r["error"] and r["bpm"] is not None)
        errors = sum(1 for r in results if r["error"])
        skipped = sum(1 for r in results if r["skipped"])
        for result in results:
            path = Path(result["path"])
            save_row(
                state, path,
                bpm=result["bpm"] if not result["error"] else None,
                error=result["error"],
            )
        dt = time.time() - t0
        elapsed = time.time() - total_start
        print(f"LOTE {num}/{of} ({len(chunk)} archivos) "
              f"-> escritos={written} saltados={skipped} errores={errors} | {dt:.0f}s | total {elapsed:.0f}s")
        sys.stdout.flush()
    print(f"FIN: {len(pending)} pendientes procesados en {time.time() - total_start:.0f}s")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--library", "-l", type=Path, default=DEFAULT_LIBRARY)
    ap.add_argument("--batch", "-b", type=int, default=200)
    ap.add_argument("--workers", "-w", type=int, default=max(1, mp.cpu_count()))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--state", type=Path, default=DEFAULT_STATE)
    args = ap.parse_args()
    return run(args.library, args.batch, args.force, args.workers, args.state)


if __name__ == "__main__":
    sys.exit(main())