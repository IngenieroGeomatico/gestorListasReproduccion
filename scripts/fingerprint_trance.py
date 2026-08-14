#!/usr/bin/env python
"""Fingerprint de los renames conflictivos de Trance para decidir nombre correcto.

Criterio del usuario: los metadatos mandan salvo que sean basura -> entonces la
huella acústica decide. Estos 74 archivos tienen tags que contradicen el nombre.
"""
from pathlib import Path
import csv
import time

from gestor_listas.renamer import fingerprint_file, identify_track
from gestor_listas.config import acoustid_api_key

BASE = Path("/run/media/radi/SI-Nena!!!/MÚSICA/bakala")
OUT = Path("log/fingerprint_Trance.csv")


def same_artist(a: str, b: str) -> bool:
    return a.lower().replace(" ", "") == b.lower().replace(" ", "")


def main() -> None:
    seen: set[str] = set()
    targets: list[dict] = []
    for r in csv.DictReader(open("log/audit_Trance.csv")):
        k = r["filename"]
        if k in seen:
            continue
        seen.add(k)
        if r["action"] == "rename" and not same_artist(r["file_artist"], r["tag_artist"]):
            targets.append(r)

    print(f"Fingerprint de {len(targets)} archivos conflictivos...")
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "id_artist", "id_title", "id_score"])
        for r in targets:
            p = BASE / "Trance" / r["filename"]
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