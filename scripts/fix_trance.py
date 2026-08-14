#!/usr/bin/env python
"""Correcciones de Trance (verificadas con huella acústica).

La huella confirma que los NOMBRES de archivo son correctos y los tags son
basura. Se corrigen los tags basura (de los archivos confirmados) al nombre
verificado y se rellenan los FLAC sin tags. Los SIN-COINC y WAV se omiten.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from library_utils import write_meta  # noqa: E402

BASE = Path("/run/media/radi/SI-Nena!!!/MÚSICA/bakala/Trance")
LOGF = Path("log/fix_Trance.log")

CONFIRMED = "log/fingerprint_Trance.csv"


def log(msg: str) -> None:
    print(msg)
    with LOGF.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


def split_name(name: str) -> tuple[str, str]:
    stem = Path(name).stem
    artist, _, title = stem.partition(" - ")
    return artist.strip(), title.strip()


FILL = [
    ("Alphazone - Sunrise (original club dub).flac", "Alphazone", "Sunrise (original club dub)"),
    ("Bossanova - Stonecold (Alphazone Rocktrance Remix).flac", "Bossanova", "Stonecold (Alphazone Rocktrance Remix)"),
    ("JS Ten - Spiritualized (Basswizzards remix).flac", "JS Ten", "Spiritualized (Basswizzards remix)"),
    ("Vandall - Can't Explain (Alphazone remix).flac", "Vandall", "Can't Explain (Alphazone remix)"),
]


def main() -> None:
    log("== fix_Trance (huella confirma nombres) ==")
    fixes = 0
    with open(CONFIRMED, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r["id_artist"]:
                log(f"  !! SIN-COINC (sin huella): {r['file']}")
                continue
            p = BASE / r["file"]
            ok = write_meta(p, artist=r["id_artist"], title=r["id_title"])
            log(f"  {'OK ' if ok else 'FAIL'} tags {r['id_artist']} - {r['id_title']}  <<  {r['file']}")
            fixes += 1
    log(f"== fin fix_Trance: {fixes} tags corregidos ==")
    for name, artist, title in FILL:
        ok = write_meta(BASE / name, artist=artist, title=title)
        log(f"  fill {'OK ' if ok else 'FAIL'} {artist} - {title}  <<  {name}")


if __name__ == "__main__":
    main()