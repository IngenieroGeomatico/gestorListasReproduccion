#!/usr/bin/env python
"""Fingerprint de pares duplicados ambiguos para decidir cuál conservar."""
from pathlib import Path
import time

from gestor_listas.renamer import fingerprint_file, identify_track
from gestor_listas.config import acoustid_api_key

base = Path("/run/media/radi/SI-Nena!!!/MÚSICA/bakala")
files = [
    "Dance/Gigi D’Agostino - La Passion.mp3",
    "Dance/ - Gigi D’Agostino - La Passion.mp3",
    "Dance/Jam & Spoon - Right in the Night (original 12 version).mp3",
    "Dance/ - Jam & Spoon - Right in the Night (original 12 version).mp3",
    "Poky/Ladybub & Bacalao - Poky Poky (1).mp3",
    "Poky/ - Ladybub & Bacalao - Poky Poky (1).mp3",
    "Cantaditas/ - Cascada - Everytime We Touch (radio mix).mp3",
    "Cantaditas/Cascada - Everytime We Touch (radio mix).mp3",
    "Cantaditas/ - Clublanders - World of Love.mp3",
    "Cantaditas/Clublanders - World of Love.mp3",
    "Cantaditas/ - De La Cruz, Taleesa - My Love Is a DJ.mp3",
    "Cantaditas/De La Cruz, Taleesa - My Love Is a DJ.mp3",
    "Dance/ - Kate Ryan - U R (My Love).mp3",
    "Dance/Kate Ryan - U R (My Love).mp3",
]
for rel in files:
    p = base / rel
    print("==", rel)
    fp = fingerprint_file(str(p))
    if not fp:
        print("   sin huella")
        continue
    duration, fingerprint = fp
    rec = identify_track(acoustid_api_key(), duration, fingerprint, min_score=0.85)
    time.sleep(1)
    if rec is None:
        print("   SIN-COINC")
        continue
    print(f"   -> {rec.artist} - {rec.title} ({rec.score:.3f})")
