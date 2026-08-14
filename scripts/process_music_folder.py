#!/usr/bin/env python3
"""Procesa una carpeta de música: BPM + renombrado acústico, carpeta a carpeta."""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

AUDIO_EXTS = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wav", ".wma"}


def find_subdirs(root: Path) -> list[Path]:
    """Subdirectorios que contienen archivos de audio."""
    dirs = []
    for d in sorted(root.iterdir()):
        if d.is_dir():
            has_audio = any(f.suffix.lower() in AUDIO_EXTS for f in d.rglob("*") if f.is_file())
            if has_audio:
                dirs.append(d)
    return dirs


def run_cmd(cmd: list[str], cwd: Path | None = None) -> bool:
    """Ejecuta comando y loguea. Devuelve True si éxito."""
    log.info("Ejecutando: %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)
        if result.stdout:
            log.debug(result.stdout.strip())
        return True
    except subprocess.CalledProcessError as e:
        log.error("Falló: %s", e.stderr.strip() if e.stderr else str(e))
        return False


def process_folder(
    folder: Path,
    acoustid_key: str | None = None,
    min_score: float = 0.5,
    force_bpm: bool = False,
    apply_rename: bool = False,
    include_year: bool = False,
) -> bool:
    """Procesa una carpeta: BPM -> rename (preview -> apply)."""
    log.info("=== Procesando: %s ===", folder.name)

    # 1. BPM analysis
    bpm_cmd = ["gestor-listas", "bpm", str(folder), "-r"]
    if force_bpm:
        bpm_cmd.append("-f")
    if not run_cmd(bpm_cmd):
        log.warning("BPM falló en %s, continúo...", folder.name)

    # 2. Rename preview (dry-run)
    rename_cmd = [
        "gestor-listas",
        "rename",
        str(folder),
        "-r",
        "--min-score",
        str(min_score),
    ]
    if acoustid_key:
        rename_cmd.extend(["--key", acoustid_key])
    if not run_cmd(rename_cmd):
        log.warning("Rename preview falló en %s", folder.name)
        return False

    # 3. Apply rename if requested
    if apply_rename:
        apply_cmd = rename_cmd + ["--apply"]
        if include_year:
            apply_cmd.append("--year")
        if not run_cmd(apply_cmd):
            log.error("Rename apply falló en %s", folder.name)
            return False
        log.info("Renombrado aplicado en %s", folder.name)
    else:
        log.info("Preview solo (usa --apply para renombrar de verdad)")

    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Procesa música carpeta a carpeta")
    parser.add_argument("root", type=Path, help="Carpeta raíz con subcarpetas de música")
    parser.add_argument("--key", help="AcoustID API key (o env ACOUSTID_API_KEY)")
    parser.add_argument("--min-score", type=float, default=0.5, help="Score mínimo 0-1 para rename")
    parser.add_argument("--force-bpm", action="store_true", help="Forzar re-cálculo BPM aunque exista")
    parser.add_argument("--apply", action="store_true", help="Aplicar renombrado (no solo preview)")
    parser.add_argument("--year", action="store_true", help="Incluir año en nombre al renombrar")
    parser.add_argument("--start-from", help="Empezar desde esta subcarpeta (inclusive)")
    parser.add_argument("--only", nargs="+", help="Procesar solo estas subcarpetas")
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    if not root.exists():
        log.error("No existe: %s", root)
        return 1

    subdirs = find_subdirs(root)
    if not subdirs:
        log.warning("No hay subcarpetas con audio en %s", root)
        return 0

    log.info("Encontradas %d subcarpetas con audio", len(subdirs))

    # Filtrar por --start-from / --only
    if args.only:
        only_set = set(args.only)
        subdirs = [d for d in subdirs if d.name in only_set]
        if not subdirs:
            log.error("No existen subcarpetas: %s", ", ".join(args.only))
            return 1
    elif args.start_from:
        found = False
        filtered = []
        for d in subdirs:
            if d.name == args.start_from:
                found = True
            if found:
                filtered.append(d)
        subdirs = filtered
        if not subdirs:
            log.error("No se encontró --start-from: %s", args.start_from)
            return 1

    log.info("Procesando %d carpetas:", len(subdirs))
    for d in subdirs:
        log.info("  - %s", d.name)

    # Confirmar si --apply
    if args.apply:
        confirm = input("\n⚠️  Se RENOMBRARÁN archivos (--apply). ¿Continuar? [s/N]: ").strip().lower()
        if confirm != "s":
            log.info("Cancelado por usuario")
            return 0

    failed = []
    for i, folder in enumerate(subdirs, 1):
        log.info("\n[%d/%d] %s", i, len(subdirs), folder.name)
        try:
            ok = process_folder(
                folder,
                acoustid_key=args.key,
                min_score=args.min_score,
                force_bpm=args.force_bpm,
                apply_rename=args.apply,
                include_year=args.year,
            )
            if not ok:
                failed.append(folder.name)
        except KeyboardInterrupt:
            log.info("\nInterrumpido por usuario")
            return 130
        except Exception as e:  # noqa: BLE001
            log.exception("Error inesperado en %s: %s", folder.name, e)
            failed.append(folder.name)

    if failed:
        log.warning("\nFallaron: %s", ", ".join(failed))
        return 1

    log.info("\n✅ Todas las carpetas procesadas correctamente")
    return 0


if __name__ == "__main__":
    sys.exit(main())