#!/usr/bin/env python
"""Audita una carpeta de la biblioteca y genera un plan CSV de correcciones.

Solo lectura: NO renombra ni mueve nada. Produce, por archivo:
  - nombre (stem) y su parseo en (artista, título) asumiendo 'Artista - Título'
  - metadatos reales (título, artista, álbum, género, año, BPM)
  - name_ok: el nombre del archivo coincide con los metadatos
  - proposed_name: nombre correcto según metadatos (si los hay)
  - detected_genre: género por keywords (detect_genre del renamer)
  - folder_genre: género actual derivado de la carpeta
  - genre_ok: si coinciden
  - action: ok / rename / fill_meta / fingerprint / review

Uso:
  python scripts/audit_folder.py "/run/.../bakala/Rock" --out log/audit_Rock.csv
  python scripts/audit_folder.py <folder> --csv global.log  # acumulativo resumible
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

from mutagen import File as MutagenFile

from gestor_listas.renamer import detect_genre, sanitize_component

AUDIO_EXTS = {".mp3", ".flac", ".wav", ".ogg", ".oga", ".opus", ".m4a", ".mp4", ".aac", ".wma", ".ape", ".alac"}

# Taxonomía de carpetas válidas de la biblioteca (los géneros de detect_genre
# se normalizan a estas carpetas).
FOLDERS = {
    "Acid", "Cantaditas", "Dance", "Drum & Bass", "Eurodance", "Hands Up",
    "Hardcore", "Hardstyle", "Hardtrance", "Hip Hop", "House", "Jumpstyle",
    "Makina", "Melodías", "Poky", "Pop", "Progressive", "Rave", "Reggae",
    "Remember", "Rock", "Techno", "Trance", "Sin género",
}

# Carpetas NO electrónicas: los archivos que caigan aquí hay que sacarlos.
NON_ELECTRONIC = {"Rock", "Pop", "Hip Hop", "Reggae"}

SEP_RE = re.compile(r"\s+-\s+")
MULTISPACE = re.compile(r"\s+")


def norm(text: str) -> str:
    """Normaliza para comparar nombres: minús, sin signos de puntuación."""
    text = text.lower()
    text = re.sub(r"[\W_]+", "", text)
    return text


def parse_filename(stem: str) -> tuple[str, str] | None:
    """Divide 'Artista - Título' devolviendo (artista, título) o None."""
    parts = [p.strip() for p in SEP_RE.split(stem)]
    if len(parts) < 2:
        return None
    artist, title = parts[0], " - ".join(parts[1:])
    if not artist or not title:
        return None
    return artist, title


def read_tags(path: Path) -> dict:
    try:
        tags = MutagenFile(str(path), easy=True)
    except Exception:
        return {}
    if not tags:
        return {}

    def first(key):
        v = tags.get(key)
        if isinstance(v, (list, tuple)):
            v = v[0] if v else None
        return str(v).strip() if v else None

    return {
        "title": first("title"),
        "artist": first("artist"),
        "album": first("album"),
        "genre": first("genre"),
        "year": first("date"),
        "bpm": first("bpm") or first("TBPM"),
    }


def name_from_meta(meta: dict, ext: str) -> str | None:
    if meta.get("title") and meta.get("artist"):
        artist = sanitize_component(meta["artist"])
        title = sanitize_component(meta["title"])
        return f"{artist} - {title}{ext}"
    return None


def audit_folder(root: Path, out_path: Path) -> dict[str, int]:
    if not root.is_dir():
        print(f"ERROR: {root} no es una carpeta", file=sys.stderr)
        sys.exit(2)
    folder_genre = root.name

    files = sorted(
        p for p in root.iterdir()
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS
    )
    if not files:
        print(f"Nada que auditar en {root.name}")
        return {}

    rows: list[dict] = []
    stats = {"ok": 0, "rename": 0, "fill_meta": 0, "fingerprint": 0, "review": 0, "genre_mismatch": 0}
    for path in files:
        stem = path.stem
        ext = path.suffix.lower()
        meta = read_tags(path)

        parsed = parse_filename(stem)
        file_artist = parsed[0] if parsed else ""
        file_title = " - ".join(parsed[1:]) if parsed else stem

        proposed_name = name_from_meta(meta, ext)

        # ¿El nombre actual coincide con los metadatos?
        name_ok = False
        if parsed and meta.get("title") and meta.get("artist"):
            name_ok = (
                norm(file_artist) == norm(meta["artist"])
                and norm(file_title) == norm(meta["title"])
            )
        elif parsed and not (meta.get("title") and meta.get("artist")):
            # Solo parseable + sin metadatos → completar metadatos si el nombre
            # es razonable ("Artista - Título" con ambas partes no vacías).
            name_ok = bool(file_artist) and bool(file_title)

        # Género: keywords del nombre + título + artista + género tag.
        detected = detect_genre(stem, meta.get("title") or "", meta.get("artist") or "", meta.get("genre") or "")
        if not detected:
            detected = detect_genre(meta.get("genre") or "")
        folder_is_known = folder_genre in FOLDERS
        genre_ok = not folder_is_known or detected is None or detected == folder_genre

        # Decidir acción.
        if not name_ok and proposed_name:
            action = "rename"
        elif not name_ok and meta.get("title") and not meta.get("artist"):
            action = "review"  # hay título pero no artista
        elif not (meta.get("title") and meta.get("artist")):
            if parsed:
                action = "fill_meta"  # nombre parseable, rellenar tags
            else:
                action = "fingerprint"  # sin pistas: huella acústica
        else:
            action = "ok"

        stats[action] += 1
        if action == "ok" and folder_is_known and detected and not genre_ok:
            if detected in NON_ELECTRONIC or folder_genre in NON_ELECTRONIC or detected != folder_genre:
                stats["genre_mismatch"] += 1

        rows.append({
            "path": str(path),
            "filename": path.name,
            "stem": stem,
            "file_artist": file_artist,
            "file_title": file_title,
            "tag_artist": meta.get("artist") or "",
            "tag_title": meta.get("title") or "",
            "tag_album": meta.get("album") or "",
            "tag_genre": meta.get("genre") or "",
            "tag_year": meta.get("year") or "",
            "tag_bpm": meta.get("bpm") or "",
            "name_ok": name_ok,
            "proposed_name": proposed_name or "",
            "detected_genre": detected or "",
            "folder_genre": folder_genre,
            "genre_ok": genre_ok,
            "action": action,
        })

    write_header = not out_path.exists() or out_path.stat().st_size == 0
    with out_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        if write_header:
            writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f"\n=== Auditoría de {root.name} ({len(files)} archivos) ===")
    for k, v in stats.items():
        print(f"  {k:<16} {v}")
    print(f"  Plan en: {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folder", type=str, help="Carpeta a auditar.")
    ap.add_argument("--out", type=str, default="", help="CSV de salida (por defecto log/audit_<carpeta>.csv).")
    args = ap.parse_args()

    folder = Path(args.folder)
    out = Path(args.out) if args.out else Path("log") / f"audit_{folder.name}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    audit_folder(folder, out)


if __name__ == "__main__":
    main()