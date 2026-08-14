"""Utilidades de auditoría/arreglo de la biblioteca bakala.

Helpers para escribir metadatos (title/artist/album/year/genre/rating) en los
formatos de la biblioteca y reutilizar desde los scripts de arreglo.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from mutagen import File as MutagenFile
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TALB, TDRC, TIT2, TPE1
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

from gestor_listas.audio import write_genre, write_rating

log = logging.getLogger(__name__)


def write_meta(
    filepath: str | Path,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    year: Optional[str] = None,
) -> bool:
    """Escribe title/artist/album/year en MP3, FLAC, OGG, OPUS y M4A.

    WAV no soporta tags de manera estándar con mutagen: se omite sin error.
    """
    path = Path(filepath)
    ext = path.suffix.lower()
    try:
        if ext == ".mp3":
            tags = ID3(str(path))
            if title:
                tags["TIT2"] = TIT2(encoding=3, text=title)
            if artist:
                tags["TPE1"] = TPE1(encoding=3, text=artist)
            if album:
                tags["TALB"] = TALB(encoding=3, text=album)
            if year:
                tags["TDRC"] = TDRC(encoding=3, text=year)
            tags.save(str(path))
            return True
        if ext == ".flac":
            tags = FLAC(str(path))
            if title:
                tags["title"] = [title]
            if artist:
                tags["artist"] = [artist]
            if album:
                tags["album"] = [album]
            if year:
                tags["date"] = [year]
            tags.save()
            return True
        if ext in (".ogg", ".oga"):
            tags = OggVorbis(str(path))
            if title:
                tags["title"] = [title]
            if artist:
                tags["artist"] = [artist]
            if album:
                tags["album"] = [album]
            if year:
                tags["date"] = [year]
            tags.save()
            return True
        if ext == ".opus":
            tags = OggOpus(str(path))
            if title:
                tags["title"] = [title]
            if artist:
                tags["artist"] = [artist]
            if album:
                tags["album"] = [album]
            if year:
                tags["date"] = [year]
            tags.save()
            return True
        if ext in (".m4a", ".mp4", ".aac"):
            tags = MP4(str(path))
            if title:
                tags["\xa9nam"] = [title]
            if artist:
                tags["\xa9ART"] = [artist]
            if album:
                tags["\xa9alb"] = [album]
            if year:
                tags["\xa9day"] = [year]
            tags.save()
            return True
        log.info("Formato %s sin soporte de tags (omitido).", ext)
        return False
    except Exception as exc:  # noqa: BLE001
        log.error("No se pudieron escribir tags en %s: %s", path, exc)
        return False


def fill_meta(filepath: str | Path, artist: str, title: str) -> bool:
    """Rellena artist/title completos (no sobrescribe lo existente)."""
    return write_meta(filepath, title=title, artist=artist)
