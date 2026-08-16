#!/usr/bin/env python3
"""Mueve temas mal clasificados a su carpeta de género correcta.

Lee log/audit_genre.csv (candidatos del auditoría) y, para los cruces
considerados "seguros" (subgéneros de baile afines), mueve el archivo a la
carpeta destino y actualiza su tag de género (que se deriva de la carpeta).

Soporta reanudación: guarda en log/move_reclassified_progress.csv cada ruta
ya movida. Sin --apply solo muestra qué movería.

Uso:
  python scripts/move_reclassified.py                  # previsualización
  python scripts/move_reclassified.py --apply          # mover de verdad
  python scripts/move_reclassified.py --only Cantaditas --apply
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

from gestor_listas.audio import write_genre

DEFAULT_LIBRARY = Path("/run/media/radi/SI-Nena!!!/MÚSICA/bakala")
DEFAULT_AUDIT = Path(__file__).resolve().parent.parent / "log" / "audit_genre.csv"
DEFAULT_PROGRESS = Path(__file__).resolve().parent.parent / "log" / "move_reclassified_progress.csv"

# Cruces "afines" considerados seguros: mover el tema de la carpeta ORIGEN a la
# carpeta del género detectado. Escogidos porque son subgéneros de baile muy
# próximos donde el movimiento no cambia la intención musical.
SAFE_MOVES: set[tuple[str, str]] = {
    ("Progressive", "Trance"),
    ("Trance", "Progressive"),
    ("Progressive", "Dance"),
    ("Dance", "Progressive"),
    ("Dance", "Trance"),
    ("Trance", "Dance"),
    ("Progressive", "House"),
    ("Dance", "House"),
    ("House", "Dance"),
    ("Dance", "Techno"),
    ("Techno", "Dance"),
    ("Progressive", "Techno"),
    ("Trance", "Techno"),
    ("Techno", "Trance"),
    ("Melodías", "Dance"),
    ("Melodías", "Trance"),
    ("Melodías", "House"),
    ("Dance", "Melodías"),
    ("Trance", "Melodías"),
    ("Melodías", "Progressive"),
    ("Dance", "Cantaditas"),
    ("Cantaditas", "Dance"),
    ("Rave", "Dance"),
    ("Dance", "Rave"),
    ("Eurodance", "Dance"),
    ("Dance", "Eurodance"),
    ("Hands Up", "Dance"),
    ("Dance", "Hands Up"),
    ("Hardtrance", "Trance"),
    ("Trance", "Hardtrance"),
    ("Hardstyle", "Hardcore"),
    ("Hardcore", "Hardstyle"),
    ("Remember", "Trance"),
    ("Trance", "Remember"),
    ("Remember", "Dance"),
    ("Dance", "Remember"),
    ("Poky", "Makina"),
    ("Makina", "Poky"),
    ("Poky", "House"),
    ("Makina", "Rave"),
    ("Rave", "Makina"),
    ("Cantaditas", "Trance"),
    ("Trance", "Cantaditas"),
    ("Cantaditas", "House"),
    ("Jumpstyle", "Hardstyle"),
}


def folder_as_genre(folder_name: str) -> str:
    return folder_name.replace("_", " ").strip() or folder_name


def load_progress(progress: Path) -> set[str]:
    done: set[str] = set()
    if progress.exists():
        with progress.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                done.add(row["path"])
    return done


def save_progress(progress: Path, path: Path) -> None:
    write_header = not progress.exists() or progress.stat().st_size == 0
    if write_header:
        progress.parent.mkdir(parents=True, exist_ok=True)
    with progress.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["path"])
        if write_header:
            writer.writeheader()
        writer.writerow({"path": str(path)})


def update_state_paths(old: Path, new: Path) -> None:
    """Corrige la ruta en los CSV de estado (etiquetado/carátulas/auditoría)."""
    old_s, new_s = str(old), str(new)
    states = [
        Path(__file__).resolve().parent.parent / "log" / "tag_library_progress.csv",
        Path(__file__).resolve().parent.parent / "log" / "tag_library_covers.csv",
        Path(__file__).resolve().parent.parent / "log" / "audit_genre.csv",
        Path(__file__).resolve().parent.parent / "log" / "audit_genre_progress.csv",
    ]
    for state in states:
        if not state.exists():
            continue
        rows = list(csv.DictReader(state.open(encoding="utf-8", newline="")))
        updated = False
        for row in rows:
            if row["path"] == old_s:
                row["path"] = new_s
                updated = True
        if not updated:
            continue
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=state.parent, suffix=".tmp")
        with open(fd, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        Path(tmp).replace(state)


def move_unique(source: Path, dest_folder: Path) -> Path:
    """Mueve source a dest_folder evitando colisiones (sufijo (2), (3)...)."""
    dest_folder.mkdir(parents=True, exist_ok=True)
    target = dest_folder / source.name
    counter = 1
    while target.exists():
        target = dest_folder / f"{source.stem} ({counter}){source.suffix}"
        counter += 1
    shutil.move(str(source), str(target))
    return target


def run(library: Path, audit_csv: Path, progress_csv: Path,
        only: list[str] | None, apply: bool) -> dict:
    if not audit_csv.exists():
        print(f"ERROR: no existe {audit_csv}. Ejecuta primero scripts/audit_genre.py")
        sys.exit(2)

    with audit_csv.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    if only:
        wanted = set(only)
        rows = [r for r in rows if r["folder"] in wanted]

    moves = []
    for r in rows:
        src_folder, dest_folder = r["folder"], r["detected"]
        if (src_folder, dest_folder) not in SAFE_MOVES:
            continue
        src = Path(r["path"])
        moves.append((src, src_folder, dest_folder))

    if not moves:
        print("No hay cruces seguros para mover.")
        return {"ok": 0, "skipped": 0, "errors": 0}

    done = load_progress(progress_csv)
    stats = {"ok": 0, "skipped": 0, "errors": 0}

    print(f"Cruces a aplicar: {len(moves)} (seguros)")
    print(f"Modo: {'APLICAR' if apply else 'previsualización'}")

    by_dest: dict[tuple[str, str], int] = {}
    for src, src_folder, dest_folder in moves:
        by_dest[(src_folder, dest_folder)] = by_dest.get((src_folder, dest_folder), 0) + 1
    for (sf, df), n in sorted(by_dest.items()):
        print(f"  {sf:12s} -> {df:12s} x{n}")

    for src, src_folder, dest_folder in moves:
        if str(src) in done:
            stats["skipped"] += 1
            continue
        if not src.exists():
            print(f"  ! no existe: {src.name}")
            stats["errors"] += 1
            save_progress(progress_csv, src)
            continue

        dest_folder_path = library / dest_folder
        print(f"  {src_folder:12s} -> {dest_folder:12s} : {src.name!s:.60}")
        if not apply:
            stats["ok"] += 1
            continue

        try:
            new_path = move_unique(src, dest_folder_path)
            # El género se deriva de la carpeta: actualizamos el tag.
            write_genre(new_path, folder_as_genre(dest_folder))
            update_state_paths(src, new_path)
            stats["ok"] += 1
        except Exception as exc:  # noqa: BLE001
            print(f"    ERROR: {exc}")
            stats["errors"] += 1
        save_progress(progress_csv, src)

    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--library", "-l", type=Path, default=DEFAULT_LIBRARY)
    ap.add_argument("--audit", type=Path, default=DEFAULT_AUDIT,
                    help="CSV de candidatos (default: log/audit_genre.csv).")
    ap.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS,
                    help="CSV de progreso (default: log/move_reclassified_progress.csv).")
    ap.add_argument("--only", nargs="+", default=None,
                    help="Solo mover candidatos de estas carpetas origen.")
    ap.add_argument("--apply", action="store_true",
                    help="Mueve de verdad (sin esto solo previsualiza).")
    args = ap.parse_args()

    stats = run(args.library, args.audit, args.progress, args.only, args.apply)
    print("\n=== Resumen movimientos ===")
    print(f"  OK: {stats['ok']} | ya movidos: {stats['skipped']} | errores: {stats['errors']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())