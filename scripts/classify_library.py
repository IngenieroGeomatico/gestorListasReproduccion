"""Clasifica la biblioteca bacala por género real y genera un plan CSV.

Objetivo: auditar los ~4700 archivos de /MÚSICA/bakala, que DEBEN ser música
electrónica, y proponer para cada uno su carpeta de género correcta.

Señales por archivo (en cascada, de más a menos fiable):
  1. Género de MusicBrainz (vía huella AcoustID → identify_track → enrich).
  2. Keywords del título/artista real (devueltos por AcoustID/MB).
  3. Keywords del nombre de archivo (fallback, poco fiable en esta biblioteca).
  4. BPM (tag existente o recálculo) → carpeta por rangos (mapeo del usuario).

Clasificaciones producidas:
  - electrónica -> carpeta de género actual de la biblioteca (Trance, House,
    Makina, Hardstyle, ..., Cantaditas, Melodías).
  - no electrónica (Rock, Pop, Hip Hop, Reggae, latin, rumba, flamenco...) ->
    carpeta de cuarentena "NO_ELECTRONICA".

Resumible: escribe el CSV línea a línea y no reprocesa archivos ya presentes.
Modo --apply mueve los archivos; sin él solo genera el plan.

Ejemplos:
  python scripts/classify_library.py                     # genera plan CSV (limitado a --limit si se pasa)
  python scripts/classify_library.py --limit 20          # prueba rápida
  python scripts/classify_library.py --apply             # mueve según el plan
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path
from typing import Optional

from gestor_listas.config import acoustid_api_key
from gestor_listas.renamer import (
    detect_genre,
    fingerprint_file,
    identify_track,
    is_audio_file,
)
from gestor_listas.bpm_analyzer import read_existing_bpm, get_bpm

# Raíz de la biblioteca: todas las carpetas de género están aquí.
DEFAULT_LIBRARY = Path("/run/media/radi/SI-Nena!!!/MÚSICA/bakala")
# Cuarentena para lo no electrónico (no existe todavía; se crea con --apply).
NON_ELECTRONIC_DIR = "NO_ELECTRONICA"
DEFAULT_OUTPUT = Path("log/bakala_classification.csv")

# Géneros que NO son electrónica según la taxonomía de keywords del renamer.
NON_ELECTRONIC_GENRES = frozenset(
    {"Rock", "Pop", "Hip Hop", "Reggae", "Reggaeton", "Latin", "Rumba", "Flamenco"}
)

# Mapeo BPM -> carpeta (fallback, solo cuando ninguna otra señal decide).
# Sigue el mapeo mental del usuario:
#   160+ Hardstyle/Hardcore, 145-159 Makina, 138-145 Trance/Remember,
#   <138 House/Dance/etc.
BPM_TO_FOLDER = [
    (175, "Hardcore"),
    (160, "Hardstyle"),
    (145, "Makina"),
    (138, "Trance"),
    (120, "House"),
    (0, "Dance"),
]


def bpm_to_folder(bpm: float) -> str:
    for threshold, folder in BPM_TO_FOLDER:
        if bpm >= threshold:
            return folder
    return "Dance"


# ─── Clasificación por archivo ────────────────────────────────────────────


def classify_one(
    path: Path,
    api_key: str,
    prefer_fingerprint: bool = True,
) -> dict:
    """Calcula todas las señales de un archivo. Nunca lanza errores.

    Devuelve un dict con: bpm, mb_genre, keyword_stem, keyword_real,
    identified (bool), proposed (str), is_electronic (bool), signal (str).
    """
    result: dict = {
        "bpm": None,
        "mb_genre": None,
        "keyword_stem": None,
        "keyword_real": None,
        "track_title": None,
        "track_artist": None,
        "identified": False,
    }

    # BPM: tag existente o recálculo.
    bpm = read_existing_bpm(path)
    if bpm is None:
        bpm = get_bpm(path)
    result["bpm"] = round(bpm, 1) if bpm else None

    # 1) Género por huella acústica (AcoustID -> MB). Solo si hay clave API.
    if prefer_fingerprint and api_key:
        ok = False
        try:
            fp = fingerprint_file(str(path))
            if fp:
                duration, fingerprint = fp
                track = identify_track(api_key, duration, fingerprint, 0.5)
                if track:
                    ok = True
                    result["identified"] = True
                    result["track_title"] = track.title
                    result["track_artist"] = track.artist
                    if track.genre:
                        result["mb_genre"] = track.genre
        except Exception:
            ok = False
        # prettyprint lento (1 req/s de MB) — resumible por CSV.
        if ok:
            time.sleep(0.5)

    # 2) Keywords del título/artista real (si se identificó la canción).
    if result["track_title"] or result["track_artist"]:
        detected = detect_genre(result["track_title"], result["track_artist"])
        if detected:
            result["keyword_real"] = detected

    # 3) Keywords del nombre de archivo (fallback).
    if result["keyword_real"] is None:
        detected = detect_genre(path.stem)
        if detected:
            result["keyword_stem"] = detected

    proposed, is_electronic, signal = _decide(result)
    result["proposed"] = proposed
    result["is_electronic"] = is_electronic
    result["signal"] = signal
    return result


def _decide(result: dict) -> tuple[str, bool, str]:
    """Elige la carpeta destino y si es electrónica, con la señal usada.

    Regla de oro: la decisión de "no electrónica" sale SOLO del género de
    MusicBrainz (autoridad real). Los keywords del nombre de archivo son ruido
    (p. ej. "Dj Richy - Rock Star" o "Pop Goes the World" no son rock/pop), así
    que jamás deciden por sí solos. Los keywords del título REMPLIDO por
    AcoustID sí valen para subgénero electrónico (un tema real llamado "...Acid
    Nightmare" es acid). Si nada decide, BPM -> carpeta electrónica.
    """
    # 1) Autoridad: género de MusicBrainz (cuando el tema se identifica y MB lo trae).
    if result["mb_genre"]:
        genre = result["mb_genre"]
        if detect_genre(genre) in NON_ELECTRONIC_GENRES:
            return NON_ELECTRONIC_DIR, False, genre
        folder = normalize_folder(genre)
        return folder, True, genre

    # 2) Keyword del título/artista REAL identificado: solo sirve para
    #    subgéneros electrónicos (resuelve BPMs doblados/mitad de octava),
    #    jamas para clasificar como no-electrónica.
    if result["keyword_real"]:
        genre = result["keyword_real"]
        if genre in NON_ELECTRONIC_GENRES:
            # p. ej. un artista con nombre "D-Rock": lo ignoramos y seguimos.
            pass
        else:
            return normalize_folder(genre), True, genre

    # 3) Fallback por BPM (la biblioteca DEBE ser electrónica: no hay
    #    señal en contrario → se conserva como electrónica).
    if result["bpm"] is not None:
        folder = bpm_to_folder(result["bpm"])
        return folder, True, f"bpm:{result['bpm']}"
    return "Dance", True, "no_bpm"


# Normalización de un género detectado (keyword o MB) a una carpeta existente.
_ALIASES = {
    "House": "House",
    "Tech House": "House",
    "Deep House": "House",
    "Progressive House": "House",
    "Minimal": "House",
    "Techno": "Techno",
    "Acid Techno": "Techno",
    "Schranz": "Techno",
    "Trance": "Trance",
    "Psytrance": "Trance",
    "Goa": "Trance",
    "Hardtrance": "Hardtrance",
    "Hard Trance": "Hardtrance",
    "Hardstyle": "Hardstyle",
    "Hard Style": "Hardstyle",
    "Rawstyle": "Hardstyle",
    "Hardcore": "Hardcore",
    "Gabber": "Hardcore",
    "Gabba": "Hardcore",
    "Uptempo": "Hardcore",
    "Speedcore": "Hardcore",
    "Frenchcore": "Hardcore",
    "Hardtek": "Hardcore",
    "Terror": "Hardcore",
    "Makina": "Makina",
    "Mákina": "Makina",
    "Poky": "Poky",
    "Pokey": "Poky",
    "Eurodance": "Eurodance",
    "Euro Dance": "Eurodance",
    "Dance": "Dance",
    "Dancefloor": "Dance",
    "Club": "Dance",
    "Rave": "Rave",
    "Hard Rave": "Rave",
    "Acid": "Acid",
    "Jack Trax": "Acid",
    "Hands Up": "Hands Up",
    "HandsUp": "Hands Up",
    "Jumpstyle": "Jumpstyle",
    "Drum & Bass": "Drum & Bass",
    "Drum and Bass": "Drum & Bass",
    "Dnb": "Drum & Bass",
    "Jungle": "Drum & Bass",
    "Breakcore": "Drum & Bass",
    "Progressive": "Progressive",
    "Remember": "Remember",
    "Old School": "Remember",
    "Oldskool": "Remember",
    "Melodías": "Melodías",
    "Melodias": "Melodías",
    "Melodic": "Melodías",
    "Cantaditas": "Cantaditas",
    "Balada": "Cantaditas",
    "Ballad": "Cantaditas",
    "EDM": "Dance",
    "Electro": "Techno",
    "Electro House": "House",
    "Dubstep": "House",
}
_REVERSE = {k.lower(): v for k, v in _ALIASES.items()}


def normalize_folder(genre: str) -> str:
    """Mapea un género detectado a la carpeta real de la biblioteca."""
    for candidate in (genre, genre.lower()):
        if candidate in _REVERSE:
            return _REVERSE[candidate]
    # Terminología "sucia" (multitag, "x / y", mayúsculas raras).
    first_token = (genre.split("/")[0].split(",")[0]).strip()
    if first_token.lower() in _REVERSE:
        return _REVERSE[first_token.lower()]
    # Desconocido y no electrónico -> cuarentena; electrónico ambiguo -> Dance.
    if detect_genre(first_token) in NON_ELECTRONIC_GENRES:
        return NON_ELECTRONIC_DIR
    return "Dance"


# ─── Scan y escritura CSV ─────────────────────────────────────────────────


def collect_audio_files(library: Path) -> list[Path]:
    files: list[Path] = []
    for folder in sorted(library.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        for p in sorted(folder.rglob("*")):
            if p.is_file() and is_audio_file(str(p)):
                files.append(p)
    return files


def load_done(output: Path) -> set[Path]:
    done: set[Path] = set()
    if output.exists():
        with output.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                done.add(Path(row["path"]))
    return done


def save_row(output: Path, row: dict) -> None:
    write_header = not output.exists()
    with output.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "path", "folder", "bpm", "mb_genre", "keyword_stem",
                "keyword_real", "track_title", "track_artist", "identified",
                "proposed", "is_electronic", "signal",
            ],
        )
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def run(
    library: Path = DEFAULT_LIBRARY,
    output: Path = DEFAULT_OUTPUT,
    api_key: Optional[str] = None,
    limit: int = 0,
    apply: bool = False,
) -> dict[str, int]:
    key = api_key or acoustid_api_key()
    if not key:
        print("ERROR: falta ACOUSTID_API_KEY (o --key). No se hará huella acústica.")
        sys.exit(2)

    files = collect_audio_files(library)
    done = load_done(output)
    pending = [p for p in files if p not in done]
    print(
        f"Total: {len(files)} | ya en CSV: {len(done)} | "
        f"por clasificar: {len(pending)}"
    )
    if limit and pending:
        pending = pending[:limit]
        print(f"(limitado a las primeras {limit} pistas)")

    stats: dict[str, int] = {"classified": 0, "errors": 0, "skipped": 0}
    for i, path in enumerate(pending, 1):
        t0 = time.time()
        try:
            rel = path.relative_to(library)
            folder = rel.parts[0] if len(rel.parts) > 1 else ""
            data = classify_one(path, key, prefer_fingerprint=True)
            row = {
                "path": str(path),
                "folder": folder,
                "bpm": data["bpm"],
                "mb_genre": data["mb_genre"],
                "keyword_stem": data["keyword_stem"],
                "keyword_real": data["keyword_real"],
                "track_title": data["track_title"],
                "track_artist": data["track_artist"],
                "identified": data["identified"],
                "proposed": data["proposed"],
                "is_electronic": data["is_electronic"],
                "signal": data["signal"],
            }
            save_row(output, row)
            stats["classified"] += 1
            print(
                f"[{i}/{len(pending)}] {path.name[:40]:40s} "
                f"bpm={data['bpm']!s:>5} propuesto={data['proposed']:<14} "
                f"sig={data['signal']:<16} ({time.time() - t0:.1f}s)"
            )
        except Exception as exc:  # noqa: BLE001 - un fallo no aborta el scan
            stats["errors"] += 1
            print(f"[{i}/{len(pending)}] ERROR en {path}: {exc}")

    # Modo aplicar: mueve todo i lo que el CSV decide (resumible: un --apply
    # posterior vuelve a procesarlo; los ya movidos ya no están aquí).
    if apply:
        print(f"\nAplicando movimientos según {output} ...")
        moved = apply_plan(
            library, output, move_electronic=True, move_non_electronic=True
        )
        stats["moved"] = moved

    print(
        f"\nClasificadas: {stats['classified']} | errores: {stats['errors']} | "
        f"movidos: {stats.get('moved', 0)}"
    )
    print(f"Plan en: {output}")
    return stats


def apply_plan(
    library: Path,
    output: Path,
    move_electronic: bool = True,
    move_non_electronic: bool = True,
) -> int:
    """Mueve los archivos según el CSV del plan. Devuelve el nº movido."""
    import shutil

    moved = 0
    errors = 0
    with output.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            source = Path(row["path"])
            if not source.exists():
                continue
            proposed = row["proposed"]
            if not proposed:
                continue
            is_electronic = row["is_electronic"].lower() == "true"
            if is_electronic and not move_electronic:
                continue
            if not is_electronic and not move_non_electronic:
                continue
            dest_dir = library / proposed
            dest_dir.mkdir(parents=True, exist_ok=True)
            target = dest_dir / source.name
            counter = 1
            stem = source.stem
            while target.exists():
                target = dest_dir / f"{stem} ({counter}){source.suffix}"
                counter += 1
            try:
                source.rename(target)
            except OSError:
                shutil.move(str(source), target)
            moved += 1
            print(f"  {source.name[:50]:50s} -> {proposed}/")
    return moved


def summarize(output: Path) -> dict:
    from collections import Counter

    counts: Counter = Counter()
    by_folder: Counter = Counter()
    with output.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            counts[row["proposed"]] += 1
            if row["is_electronic"].lower() == "true":
                by_folder[row["folder"]] += 1
    print(f"\n=== Resumen del plan ({output}) ===")
    for g, n in counts.most_common():
        print(f"  {n:5d}  {g}")
    return dict(counts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--library", "-l", type=Path, default=DEFAULT_LIBRARY)
    ap.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--key", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--summary", action="store_true", help="Resume el CSV plan ya generado")
    args = ap.parse_args()

    if args.summary:
        summarize(args.output)
        sys.exit(0)

    run(
        library=args.library,
        output=args.output,
        api_key=args.key,
        limit=args.limit,
        apply=args.apply,
    )


if __name__ == "__main__":
    main()