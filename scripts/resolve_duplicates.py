#!/usr/bin/env python
"""Resuelve los 16 archivos duplicados con prefijo ' - ' inicial.

Regla elegida por el usuario: conservar la copia de MAYOR bitrate (o la de
nombre limpio si empatan), siempre con nombre 'Artista - Título', y borrar
la otra. Verificado por huella acústica: cada par es la misma pista.
"""
from pathlib import Path
from mutagen import File

BASE = Path("/run/media/radi/SI-Nena!!!/MÚSICA/bakala")
LOG = Path("log/duplicates.log")

pairs = [
    ("Cantaditas/ - Cascada - Everytime We Touch (radio mix).mp3", "Cantaditas/Cascada - Everytime We Touch (radio mix).mp3"),
    ("Cantaditas/ - Clublanders - World of Love.mp3", "Cantaditas/Clublanders - World of Love.mp3"),
    ("Cantaditas/ - De La Cruz, Taleesa - My Love Is a DJ.mp3", "Cantaditas/De La Cruz, Taleesa - My Love Is a DJ.mp3"),
    ("Cantaditas/ - Outworld - The End.mp3", "Cantaditas/Outworld - The End.mp3"),
    ("Dance/ - Gigi D’Agostino - La Passion.mp3", "Dance/Gigi D’Agostino - La Passion.mp3"),
    ("Dance/ - Kate Ryan - U R (My Love).mp3", "Dance/Kate Ryan - U R (My Love).mp3"),
    ("Dance/ - Miss Jane - It’s a Fine Day (ATB club mix).mp3", "Dance/Miss Jane - It’s a Fine Day (ATB club mix).mp3"),
    ("Dance/ - Brooklyn Bounce - Get Ready to Bounce (club attack).mp3", "Dance/Brooklyn Bounce - Get Ready to Bounce (club attack).mp3"),
    ("Dance/ - Cabballero - Dancing With Tears in My Eyes (dance maxi).mp3", "Dance/Cabballero - Dancing With Tears in My Eyes (dance maxi).mp3"),
    ("Dance/ - Dance Nation - Sunshine (original vocal radio edit).mp3", "Dance/Dance Nation - Sunshine (original vocal radio edit).mp3"),
    ("Dance/ - DJ Miki - Dance Più.mp3", "Dance/DJ Miki - Dance Più.mp3"),
    ("Dance/ - Essential - My Destiny (XTM club mix) (1).mp3", "Dance/Essential - My Destiny (XTM club mix) (1).mp3"),
    ("Dance/ - Jam & Spoon - Right in the Night (original 12 version).mp3", "Dance/Jam & Spoon - Right in the Night (original 12 version).mp3"),
    ("Dance/ - Lock ’n Load - Blow Ya Mind (Club Caviar radio edit).mp3", "Dance/Lock ’n Load - Blow Ya Mind (Club Caviar radio edit).mp3"),
    ("Dance/ - Melodie MC - Dum Da Dum (club version).mp3", "Dance/Melodie MC - Dum Da Dum (club version).mp3"),
    ("Poky/ - Ladybub & Bacalao - Poky Poky (1).mp3", "Poky/Ladybub & Bacalao - Poky Poky (1).mp3"),
]


def bitrate(p: Path) -> int:
    try:
        return int(File(p).info.bitrate)
    except Exception:
        return -1


def main() -> None:
    for dirty, clean in pairs:
        dp, cp = BASE / dirty, BASE / clean
        if not dp.exists():
            print(f"!! no existe dirty: {dirty}")
            continue
        if not cp.exists():
            print(f"!! no existe clean: {clean}  (dirty se queda)")
            continue
        bd, bc = bitrate(dp), bitrate(cp)
        keep_dirty = bd > bc  # mayor bitrate y además es la ' - '
        if keep_dirty:
            print(f"{dirty}\n   dirty {bd}k > clean {bc}k  -> conservar dirty, borrar clean")
            cp.unlink()
            dp.rename(cp)
            action = f"keep dirty {bd}k, borrada clean {bc}k, renombrada a limpia"
        else:
            print(f"{dirty}\n   clean {bc}k >= dirty {bd}k  -> borrar dirty, conservar clean")
            dp.unlink()
            action = f"delete dirty {bd}k, keep clean {bc}k"
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{action}\t{dirty}\t->\t{clean}\n")


if __name__ == "__main__":
    main()
