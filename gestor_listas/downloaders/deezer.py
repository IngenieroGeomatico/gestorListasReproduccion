from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import requests

from ..model import Track
from ..providers.deezer import DeezerProvider

BLOWFISH_SECRET = b"g4el58wc0zvf9na1"
CHUNK_SIZE = 2048


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


COVER_BASE = "https://cdn-images.dzcdn.net/images/cover"


class DeezerDownloader:
    def __init__(self, provider: Optional[DeezerProvider] = None) -> None:
        self._provider = provider or DeezerProvider()

    def download(self, track: Track, output_dir: str | Path) -> Optional[Path]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        safe_name = f"{track.artist} - {track.title}".replace("/", "_").replace("\0", "")
        output_path = output_dir / f"{safe_name}.mp3"

        if output_path.exists():
            return output_path

        deezer_id = self._resolve_deezer_id(track)
        if not deezer_id:
            return None

        stream_url = self._get_stream_url(deezer_id)
        if not stream_url:
            return None

        resp = requests.get(stream_url, stream=True, timeout=120)
        resp.raise_for_status()
        encrypted = resp.content

        decrypted = _decrypt(encrypted, deezer_id)

        with open(output_path, "wb") as f:
            f.write(decrypted)

        self._tag_file(output_path, deezer_id)

        return output_path

    def _resolve_deezer_id(self, track: Track) -> Optional[str]:
        if track.id.isdigit():
            return track.id
        if track.isrc:
            return None
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

        resp = requests.post("https://media.deezer.com/v1/get_url", json=payload, timeout=30)
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
                        cover_data = requests.get(cover_url, timeout=15).content
                    except Exception:
                        pass
            except Exception:
                pass

        from ..audio import _genre_name
        genre = _genre_name(genre_id)

        write_id3_tags(
            mp3_path,
            title=title,
            artist=artist,
            album=album,
            year=year,
            track_number=track_number,
            genre=genre,
            cover_data=cover_data,
        )

        bpm = detect_bpm(mp3_path)
        if bpm is not None:
            write_id3_tags(mp3_path, bpm=bpm)
