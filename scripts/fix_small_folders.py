#!/usr/bin/env python
"""Aplica correcciones manuales (verificadas con huella acústica) a carpetas
pequeñas de la biblioteca bakala. Renombra, corrige tags y mueve de género.

Ejecución puntual; cada acción se registra en log/fix_<carpeta>.log.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from library_utils import write_meta, write_genre, write_rating  # noqa: E402
from gestor_listas.renamer import TrackInfo, move_file, resolve_library_target  # noqa: E402

BASE = Path("/run/media/radi/SI-Nena!!!/MÚSICA/bakala")


def log(msg: str, logf: Path) -> None:
    print(msg)
    with logf.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


def rename_in_place(logf: Path, folder: str, old: str, new: str) -> None:
    src = BASE / folder / old
    if not src.exists():
        log(f"  !! NO EXISTE {folder}/{old}", logf)
        return
    dst = BASE / folder / new
    if dst.exists():
        log(f"  !! DESTINO YA EXISTE {folder}/{new}", logf)
        return
    src.rename(dst)
    log(f"  rename: {folder}/{old}  ->  {folder}/{new}", logf)


def move_to_genre(logf: Path, folder: str, name: str, dest_folder: str,
                  artist: str, title: str, year: Optional[str] = None) -> None:
    src = BASE / folder / name
    if not src.exists():
        log(f"  !! NO EXISTE {folder}/{name}", logf)
        return
    dest = BASE / dest_folder
    dest.mkdir(exist_ok=True)
    track = TrackInfo(title=title, artist=artist, year=year)
    target = resolve_library_target(dest, track, src.suffix.lower())
    moved = move_file(src, target)
    if moved:
        log(f"  move: {folder}/{name}  ->  {dest_folder}/{target.name}", logf)
    else:
        log(f"  !! FALLO move: {folder}/{name}", logf)


def fix_meta(logf: Path, folder: str, name: str, artist: str, title: str,
             album: Optional[str] = None, year: Optional[str] = None,
             genre: Optional[str] = None, rating: Optional[float] = None) -> None:
    path = BASE / folder / name
    if not path.exists():
        log(f"  !! NO EXISTE {folder}/{name}", logf)
        return
    write_meta(path, title=title, artist=artist, album=album, year=year)
    if genre:
        write_genre(path, genre)
    if rating is not None:
        write_rating(path, rating)
    log(f"  tags: {folder}/{name}  <- {artist} - {title}"
        + (f" [{album}] {year}" if album or year else "")
        + (f" | genre={genre} rating={rating}" if genre or rating else ""), logf)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    folders = ["Acid", "Hands Up", "Eurodance", "Drum & Bass", "Rave",
               "Hip Hop", "Reggae", "Jumpstyle", "Hardtrance", "Pop"]
    if target != "all":
        folders = [target]

    for folder in folders:
        logf = Path("log") / f"fix_{folder}.log"
        log(f"\n=== FIX {folder} ===", logf)

        if folder == "Acid":
            rename_in_place(logf, "Acid", " - Emmanuel Top - Acid Phase.flac",
                            "Emmanuel Top - Acid Phase.flac")
            fix_meta(logf, "Acid", "George Acosta - Emotions (DJ Marc la Cruz mix).wav",
                     "George Acosta", "Emotions (DJ Marc la Cruz mix)")
            fix_meta(logf, "Acid", "Megamind - Taub (Picotto mix).flac",
                     "Megamind", "Taub (Picotto mix)")

        elif folder == "Hands Up":
            rename_in_place(logf, "Hands Up", " - Pinball - Hands Up (Riphouse edit).mp3",
                            "Pinball - Hands Up (Riphouse edit).mp3")
            fix_meta(logf, "Hands Up", "Pinball - Hands Up (Riphouse edit).mp3",
                     "Pinball", "Hands Up (Riphouse edit)")
            rename_in_place(logf, "Hands Up", " - Urta And Navarro - Put Your Hands Up (DJ Pedrolax).mp3",
                            "Urta And Navarro - Put Your Hands Up (DJ Pedrolax).mp3")

        elif folder == "Eurodance":
            rename_in_place(logf, "Eurodance", " - Kate Project - A Better World.mp3",
                            "Kate Project - A Better World.mp3")
            fix_meta(logf, "Eurodance", "Kate Project - A Better World.mp3",
                     "Kate Project", "A Better World")
            fix_meta(logf, "Eurodance", "Kate Project - A Better World.wav",
                     "Kate Project", "A Better World")
            fix_meta(logf, "Eurodance", "Rozalla - Everybody's Free (To Feel Good).flac",
                     "Rozalla", "Everybody's Free (To Feel Good)")
            fix_meta(logf, "Eurodance", "Wildside - Open My Door.flac",
                     "Wildside", "Open My Door")

        elif folder == "Drum & Bass":
            rename_in_place(logf, "Drum & Bass", " - Mulhouse - Rave in the Jungle.mp3",
                            "Mulhouse - Rave in the Jungle.mp3")
            fix_meta(logf, "Drum & Bass", "Mulhouse - Rave in the Jungle.mp3",
                     "Mulhouse", "Rave in the Jungle")
            rename_in_place(logf, "Drum & Bass", " - PB 2000 - In Da Jungle (Crazy Drummer remix).mp3",
                            "PB 2000 - In Da Jungle (Crazy Drummer remix).mp3")
            fix_meta(logf, "Drum & Bass", "PB 2000 - In Da Jungle (Crazy Drummer remix).mp3",
                     "PB 2000", "In Da Jungle (Crazy Drummer remix)")
            rename_in_place(logf, "Drum & Bass", " - PB 2000 - In Da Jungle (Crazy Drummer remix) (1).mp3",
                            "PB 2000 - In Da Jungle (Crazy Drummer remix) (1).mp3")
            fix_meta(logf, "Drum & Bass", "PB 2000 - In Da Jungle (Crazy Drummer remix) (1).mp3",
                     "PB 2000", "In Da Jungle (Crazy Drummer remix)")

        elif folder == "Rave":
            rename_in_place(logf, "Rave", " - 06.CriticalMass - Burnin' Love (Rave Radio Edit).wav",
                            "CriticalMass - Burnin' Love (Rave Radio Edit).wav")
            fix_meta(logf, "Rave", "CriticalMass - Burnin' Love (Rave Radio Edit).wav",
                     "CriticalMass", "Burnin' Love (Rave Radio Edit)")
            rename_in_place(logf, "Rave", " - 89ers - Wap Bam Boogie (rave radio mix).mp3",
                            "89ers - Wap Bam Boogie (rave radio mix).mp3")
            fix_meta(logf, "Rave", "89ers - Wap Bam Boogie (rave radio mix).mp3",
                     "89ers", "Wap Bam Boogie (rave radio mix)")
            rename_in_place(logf, "Rave", " - Atmospheric - Oxigene (Hard Rave version).mp3",
                            "Atmospheric - Oxigene (Hard Rave version).mp3")
            fix_meta(logf, "Rave", "Atmospheric - Oxigene (Hard Rave version).mp3",
                     "Atmospheric", "Oxigene (Hard Rave version)")
            rename_in_place(logf, "Rave", " - Atmospheric - Oxigene (Hard Rave version) (1).mp3",
                            "Atmospheric - Oxigene (Hard Rave version) (1).mp3")
            fix_meta(logf, "Rave", "Atmospheric - Oxigene (Hard Rave version) (1).mp3",
                     "Atmospheric", "Oxigene (Hard Rave version)")
            rename_in_place(logf, "Rave", " - Highlander - Hold Me Now (Bass D & King Matthew remix).mp3",
                            "Highlander - Hold Me Now (Bass D & King Matthew remix).mp3")
            fix_meta(logf, "Rave", "Highlander - Hold Me Now (Bass D & King Matthew remix).mp3",
                     "Highlander", "Hold Me Now (Bass D & King Matthew remix)")
            rename_in_place(logf, "Rave", " - Rave Allstars - Braucht Ihr Mehr.mp3",
                            "Rave Allstars - Braucht Ihr Mehr.mp3")
            fix_meta(logf, "Rave", "Rave Allstars - Braucht Ihr Mehr.mp3",
                     "Rave Allstars", "Braucht Ihr Mehr")
            rename_in_place(logf, "Rave", " - Rave Box - Made for jump.mp3",
                            "Rave Box - Made for jump.mp3")
            fix_meta(logf, "Rave", "Rave Box - Made for jump.mp3",
                     "Rave Box", "Made for jump")
            fix_meta(logf, "Rave", "Aqualoop - Twilight Zone.flac",
                     "Aqualoop", "Twilight Zone")

        elif folder == "Hip Hop":
            rename_in_place(logf, "Hip Hop", " - dani bpm - rap.mp3",
                            "dani bpm - rap.mp3")

        elif folder == "Reggae":
            rename_in_place(logf, "Reggae", " - Piramide - Ragga Style.mp3",
                            "Piramide - Ragga Style.mp3")
            rename_in_place(logf, "Reggae", " - Reggae New Som - Pancadão New Som.mp3",
                            "Reggae New Som - Pancadão New Som.mp3")
            fix_meta(logf, "Reggae", "Reggae New Som - Pancadão New Som.mp3",
                     "Reggae New Som", "Pancadão New Som")

        elif folder == "Jumpstyle":
            rename_in_place(logf, "Jumpstyle", " - the_jumpstyle_lovers - Jumpstyle Lover.mp3",
                            "the_jumpstyle_lovers - Jumpstyle Lover.mp3")

        elif folder == "Hardtrance":
            rename_in_place(logf, "Hardtrance", " - UBM - Lovin' You (Hardtrance mix).mp3",
                            "UBM - Lovin' You (Hardtrance mix).mp3")
            fix_meta(logf, "Hardtrance", "UBM - Lovin' You (Hardtrance mix).mp3",
                     "UBM", "Lovin' You (Hardtrance mix)")
            fix_meta(logf, "Hardtrance", "Kaos Rock - The Bells.mp3",
                     "Kaos Rock", "The Bells")

        elif folder == "Pop":
            fix_meta(logf, "Pop", "ATB - 9 PM (Till I Come) (UK edit).wav",
                     "ATB", "9 PM (Till I Come) (UK edit)",
                     genre="Pop", rating=3.05)
            fix_meta(logf, "Pop", "Dee Dee - The One (extended mix).wav",
                     "Dee Dee", "The One (extended mix)")

    print("\nListo.")
