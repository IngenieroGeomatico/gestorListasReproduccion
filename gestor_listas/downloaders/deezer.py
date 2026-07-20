from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from ..http import make_session
from ..model import Track
from ..providers.deezer import DeezerProvider
from ..util import safe_filename

logger = logging.getLogger(__name__)

BLOWFISH_SECRET = b"g4el58wc0zvf9na1"
CHUNK_SIZE = 2048

# Sesión con reintentos compartida para descargas y carátulas.
_session = make_session()


def _blowfish_key(track_id: str) -> bytes:
    import hashlib
    h = hashlib.md5(track_id.encode()).hexdigest()
    return bytes(ord(h[i]) ^ ord(h[i + 16]) ^ BLOWFISH_SECRET[i] for i in range(16))


def _decrypt_chunk(chunk: bytes, key: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    c = Cipher(algorithms.Blowfish(key), modes.CBC(b"\x00\x01\x02\x03\x04\x05\x06\x07"))
    decryptor = c.decryptor()
    return decryptor.update(chunk) + decryptor.finalize()


def _decrypt(data: bytes, track_id: str) -> bytes:
    key = _blowfish_key(track_id)
    out = bytearray()
    for i in range(0, len(data), CHUNK_SIZE):
        chunk = data[i : i + CHUNK_SIZE]
        if (i // CHUNK_SIZE) % 3 == 0 and len(chunk) == CHUNK_SIZE:
            out.extend(_decrypt_chunk(chunk, key))
        else:
            out.extend(chunk)
    return bytes(out)


def _decrypt_stream_to_file(resp, track_id: str, output_path: Path) -> None:
    """Descifra el stream de Deezer bloque a bloque y lo escribe a disco.

    Evita cargar el fichero completo en memoria: acumula bytes en un buffer,
    procesa los bloques de 2048 completos (cada tercero cifrado) y escribe el
    resto pendiente al final.
    """
    key = _blowfish_key(track_id)
    buffer = bytearray()
    block_index = 0
    with open(output_path, "wb") as f:
        for part in resp.iter_content(chunk_size=CHUNK_SIZE * 128):
            if not part:
                continue
            buffer.extend(part)
            while len(buffer) >= CHUNK_SIZE:
                block = bytes(buffer[:CHUNK_SIZE])
                del buffer[:CHUNK_SIZE]
                if block_index % 3 == 0:
                    f.write(_decrypt_chunk(block, key))
                else:
                    f.write(block)
                block_index += 1
        # Último bloque parcial: nunca se cifra.
        if buffer:
            f.write(bytes(buffer))


COVER_BASE = "https://cdn-images.dzcdn.net/images/cover"


class DeezerDownloader:
    def __init__(self, provider: Optional[DeezerProvider] = None) -> None:
        self._provider = provider or DeezerProvider()

    def download(self, track: Track, output_dir: str | Path) -> Optional[Path]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        safe_name = safe_filename(f"{track.artist} - {track.title}")
        output_path = output_dir / f"{safe_name}.mp3"

        if output_path.exists():
            return output_path

        deezer_id = self._resolve_deezer_id(track)
        if not deezer_id:
            return None

        stream_url = self._get_stream_url(deezer_id)
        if not stream_url:
            return None

        resp = _session.get(stream_url, stream=True, timeout=120)
        resp.raise_for_status()
        _decrypt_stream_to_file(resp, deezer_id, output_path)

        self._tag_file(output_path, deezer_id)

        return output_path

    def _resolve_deezer_id(self, track: Track) -> Optional[str]:
        if track.id.isdigit():
            return track.id
        found = self._provider.search_track(track.title, track.artist)
        if found:
            return found.id
        return None

    def _get_stream_url(self, track_id: str) -> Optional[str]:
        try:
            data = self._provider._gw("song.getData", {"sng_id": int(track_id)})
        except Exception:
            return None

        track_token = data.get("TRACK_TOKEN")
        if not track_token:
            return None

        user_data = self._provider._gw("deezer.getUserData")
        license_token = user_data["USER"]["OPTIONS"]["license_token"]

        payload = {
            "license_token": license_token,
            "media": [{"type": "FULL", "formats": [{"cipher": "BF_CBC_STRIPE", "format": "MP3_128"}]}],
            "track_tokens": [track_token],
        }

        resp = _session.post("https://media.deezer.com/v1/get_url", json=payload, timeout=30)
        if resp.status_code != 200:
            return None

        try:
            return resp.json()["data"][0]["media"][0]["sources"][0]["url"]
        except (KeyError, IndexError):
            return None

    def _tag_file(self, mp3_path: Path, track_id: str) -> None:
        from ..audio import write_id3_tags, detect_bpm

        try:
            song = self._provider._gw("song.getData", {"sng_id": int(track_id)})
        except Exception:
            return

        title = song.get("SNG_TITLE")
        artist = song.get("ART_NAME")
        album_id = song.get("ALB_ID")
        track_number = song.get("TRACK_NUMBER")
        genre_id = song.get("GENRE_ID")

        album = None
        year = None
        genre = None
        cover_data = None
        if album_id:
            try:
                album_data = self._provider._gw("album.getData", {"alb_id": album_id})
                album = album_data.get("ALB_TITLE")
                release = album_data.get("PHYSICAL_RELEASE_DATE") or album_data.get("DIGITAL_RELEASE_DATE")
                if release:
                    year = release[:4]
                if not genre_id:
                    genre_id = album_data.get("GENRE_ID")
                cover_hash = album_data.get("ALB_PICTURE")
                if cover_hash:
                    cover_url = f"{COVER_BASE}/{cover_hash}/500x500-000000-80-0-0.jpg"
                    try:
                        cover_data = _session.get(cover_url, timeout=15).content
                    except Exception:
                        pass
            except Exception:
                pass

        from ..audio import _genre_name
        genre = _genre_name(genre_id)

        # Calculamos el BPM antes de escribir para hacer una sola pasada de tags.
        # Pasamos el género explícito (el fichero aún no tiene tags) para elegir
        # el tempo prior adecuado (EDM vs balanceado).
        try:
            bpm = detect_bpm(mp3_path, genre=genre)
        except Exception:
            bpm = None

        write_id3_tags(
            mp3_path,
            title=title,
            artist=artist,
            album=album,
            year=year,
            track_number=track_number,
            genre=genre,
            cover_data=cover_data,
            bpm=bpm,
        )
