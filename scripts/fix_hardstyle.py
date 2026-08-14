#!/usr/bin/env python
"""Correcciones de Hardstyle (verificadas con huella acústica).

La huella confirma que los NOMBRES de archivo son correctos y los tags son
basura. Se corrigen los tags basura al nombre verificado. SIN-COINC se omite.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from library_utils import write_meta  # noqa: E402

BASE = Path("/run/media/radi/SI-Nena!!!/MÚSICA/bakala/Hardstyle")
LOGF = Path("log/fix_Hardstyle.log")
CONFIRMED = "log/fp_Hardstyle.csv"


def log(msg: str) -> None:
    print(msg)
    with LOGF.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


def main() -> None:
    log("== fix_Hardstyle (huella confirma nombres) ==")
    fixes = 0
    with open(CONFIRMED, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r["id_artist"]:
                log(f"  !! SIN-COINC: {r['file']}")
                continue
            ok = write_meta(BASE / r["file"], artist=r["id_artist"], title=r["id_title"])
            log(f"  {'OK ' if ok else 'FAIL'} tags {r['id_artist']} - {r['id_title']}  <<  {r['file']}")
            fixes += 1
    log(f"== fin fix_Hardstyle: {fixes} tags corregidos ==")


if __name__ == "__main__":
    main()