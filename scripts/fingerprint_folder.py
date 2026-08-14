#!/usr/bin/env python
"""Fingerprint de renames conflictivos (artist difiere) en una carpeta."""
from pathlib import Path
import csv
import sys
import time

from gestor_listas.renamer import fingerprint_file, identify_track
from gestor_listas.config import acoustid_api_key

BASE = Path("/run/media/radi/SI-Nena!!!/MÚSICA/bakala")


def same_artist(a: str, b: str) -> bool:
    return a.lower().replace(" ", "") == b.lower().replace(" ", "")


def main() -> None:
    if len(sys.argv) < 3:
        print("Uso: fingerprint_folder.py <carpeta> <audit_csv> <out_csv> [cosmetic|all]")
        sys.exit(2)
    folder, audit_csv, out_csv = sys.argv[1:4]
    mode = sys.argv[4] if len(sys.argv) > 4 else "conflict"
    seen: set[str] = set()
    targets: list[dict] = []
    for r in csv.DictReader(open(audit_csv)):
        k = r["filename"]
        if k in seen:
            continue
        seen.add(k)
        if r["action"] != "rename":
            continue
        if mode == "conflict" and not same_artist(r["file_artist"], r["tag_artist"]):
            targets.append(r)
        elif mode == "cosmetic" and same_artist(r["file_artist"], r["tag_artist"]):
            targets.append(r)
        elif mode == "all":
            targets.append(r)

    print(f"Fingerprint de {len(targets)} archivos ({mode}) en {folder}...")
    with open(out_csv, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "id_artist", "id_title", "id_score"])
        for r in targets:
            p = BASE / folder / r["filename"]
            artist = title = score = ""
            fp = fingerprint_file(str(p))
            if fp:
                duration, fingerprint = fp
                rec = identify_track(acoustid_api_key(), duration, fingerprint, min_score=0.85)
                time.sleep(1)
                if rec:
                    artist, title, score = rec.artist, rec.title, f"{rec.score:.3f}"
            w.writerow([r["filename"], artist, title, score])
            fh.flush()
            print(f"  {r['filename'][:55]:55s} -> {artist} - {title} ({score})", flush=True)


if __name__ == "__main__":
    main()