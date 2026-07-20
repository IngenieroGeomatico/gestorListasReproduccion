from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from ..config import resolve_ffmpeg
from ..errors import DownloadError
from ..model import Track
from ..util import safe_filename


def _ffmpeg_location() -> Optional[str]:
    """Ruta a ffmpeg para yt-dlp, o None si no hay ninguno disponible.

    A diferencia de resolve_ffmpeg(), no lanza: si no hay ffmpeg dejamos que
    yt-dlp lo gestione (puede descargar audio nativo sin post-procesado).
    """
    try:
        return resolve_ffmpeg()
    except Exception:  # noqa: BLE001 - degradar sin --ffmpeg-location
        return None


class YouTubeDownloader:
    def __init__(self, output_format: str = "best") -> None:
        self.output_format = output_format

    def _get_url(self, track: Track) -> str:
        if track.uri and "youtube.com/watch?v=" in track.uri:
            return track.uri
        return f"ytsearch:{track.artist} - {track.title}"

    def _build_cmd(self, url: str, output_template: str) -> list[str]:
        # En modo best/opus preferimos el webm nativo (opus) sin recodificar.
        audio_source = "bestaudio[ext=webm]/bestaudio" if self.output_format in ("best", "opus") else "bestaudio/best"
        audio_format = "opus" if self.output_format in ("best", "opus") else self.output_format

        cmd = [
            "yt-dlp",
            "-f", audio_source,
            "--extract-audio",
            "--audio-format", audio_format,
            "--audio-quality", "0",
            "--embed-thumbnail",
            "--embed-metadata",
            "-o", output_template,
            "--no-playlist",
            # Imprime la ruta final del fichero tras moverlo, para no adivinarla.
            "--print", "after_move:filepath",
            "--no-simulate",
            url,
        ]

        # Indica a yt-dlp qué ffmpeg usar (sistema o el de imageio-ffmpeg).
        ffmpeg = _ffmpeg_location()
        if ffmpeg:
            cmd.insert(1, "--ffmpeg-location")
            cmd.insert(2, ffmpeg)

        deno_path = shutil.which("deno")
        if deno_path:
            cmd.insert(1, "--js-runtimes")
            cmd.insert(2, f"deno:{deno_path}")
        return cmd

    def download(self, track: Track, output_dir: str | Path) -> Optional[Path]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        safe_name = safe_filename(f"{track.artist} - {track.title}")
        output_template = str(output_dir / f"{safe_name}.%(ext)s")

        cmd = self._build_cmd(self._get_url(track), output_template)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except FileNotFoundError:
            raise DownloadError("yt-dlp no está instalado. Ejecuta: pip install yt-dlp")

        if result.returncode != 0:
            return None

        output_path = self._parse_output_path(result.stdout, output_dir, safe_name)
        if output_path is None:
            return None

        from ..bpm_analyzer import get_bpm, write_bpm
        bpm = get_bpm(output_path)
        if bpm is not None:
            write_bpm(output_path, bpm)

        return output_path

    @staticmethod
    def _parse_output_path(stdout: str, output_dir: Path, safe_name: str) -> Optional[Path]:
        # yt-dlp imprime la ruta final gracias a --print after_move:filepath.
        for line in reversed(stdout.splitlines()):
            candidate = Path(line.strip())
            if line.strip() and candidate.exists() and candidate.is_file():
                return candidate

        # Fallback: buscar por nombre en el directorio de salida.
        for f in output_dir.iterdir():
            if f.stem == safe_name and f.suffix.lower() in {".mp3", ".m4a", ".opus", ".ogg", ".webm"}:
                return f
        return None
