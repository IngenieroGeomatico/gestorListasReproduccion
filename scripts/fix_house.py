#!/usr/bin/env python
"""Correcciones de House (verificadas con huella acústica).

Resultado de la huella: los NOMBRES son correctos; los tags eran basura.
Se corrigen los tags basura al nombre verificado y se rellena el FLAC sin tags.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from library_utils import write_meta  # noqa: E402

BASE = Path("/run/media/radi/SI-Nena!!!/MÚSICA/bakala")
LOGF = Path("log/fix_House.log")


def log(msg: str) -> None:
    print(msg)
    with LOGF.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


def set_meta(name: str, artist: str, title: str) -> None:
    p = BASE / "House" / name
    ok = write_meta(p, artist=artist, title=title)
    log(f"  {'OK ' if ok else 'FAIL'} tags {artist} - {title}  <<  {name}")


if __name__ == "__main__":
    log("== fix_House (huella confirma nombres) ==")
    # Tags basura -> nombre verificado por huella
    set_meta("DJ Dean - If I Could Be You (radio mix).mp3", "DJ Dean", "If I Could Be You (radio mix)")
    set_meta("Pinocchio - Pinocchio in Moskau.mp3", "Pinocchio", "Pinocchio in Moskau")
    set_meta("The Lighthouse - Late Night Swimming.mp3", "The Lighthouse", "Late Night Swimming")
    # FLAC sin artist/title -> rellenar desde nombre
    set_meta("Crusader - My House Is Your House (Alphazone Mix).flac",
             "Crusader", "My House Is Your House (Alphazone Mix)")
    # Absolom: tag title omitia 'Fucking' pero la huella lo confirma
    set_meta("Absolom - Fucking Baby Boomers.flac", "Absolom", "Fucking Baby Boomers")
    # Tags con subtítulos omitidos/extra: sincronizar al título verificado
    set_meta("Arrow - Back in the House (Kai Tracid mix).mp3",
             "Arrow", "Back in the House (Kai Tracid mix)")
    set_meta("Striking Man - My House (It's Not Even Music) (radio mix).mp3",
             "Striking Man", "My House (It's Not Even Music) (radio mix)")
    log("== fin fix_House ==")