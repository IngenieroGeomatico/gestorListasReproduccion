from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from ..model import Track


VALID_FORMATS = {"best", "mp3", "opus", "m4a"}


class YouTubeDownloader:
    def __init__(self, output_format: str = "best") -> None:
        if output_format not in VALID_FORMATS:
            raise ValueError(f"Formato inválido: {output_format}. Válidos: {', '.join(sorted(VALID_FORMATS))}")
        self.output_format = output_format

    def download(self, track: Track, output_dir: str | Path) -> Optional[Path]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        safe_name = f"{track.artist} - {track.title}".replace("/", "_").replace("\0", "")
        ext = "opus" if self.output_format == "best" else self.output_format
        output_path = output_dir / f"{safe_name}.{ext}"

        if output_path.exists():
            return output_path

        search_query = f"ytsearch:{track.artist} - {track.title}"

        if self.output_format == "best":
            cmd = [
                "yt-dlp",
                "-f", "bestaudio/best",
                "-S", "codec:opus,ext:webm",
                "--embed-thumbnail",
                "--embed-metadata",
                "-o", str(output_path),
                "--no-playlist",
                search_query,
            ]
        else:
            cmd = [
                "yt-dlp",
                "-f", "bestaudio/best",
                "-x",
                "--audio-format", self.output_format,
                "--audio-quality", "0",
                "--embed-thumbnail",
                "--embed-metadata",
                "-o", str(output_path),
                "--no-playlist",
                search_query,
            ]

        import shutil
        deno_path = shutil.which("deno")
        if deno_path:
            cmd.insert(1, "--js-runtimes")
            cmd.insert(2, f"deno:{deno_path}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return None

        actual_path = None
        if output_path.exists():
            actual_path = output_path
        else:
            for f in output_dir.iterdir():
                if f.stem == safe_name and f.suffix in {".mp3", ".m4a", ".opus", ".webm", ".ogg"}:
                    actual_path = f
                    break

        if actual_path:
            from ..bpm_analyzer import get_bpm, write_bpm
            bpm = get_bpm(actual_path)
            if bpm is not None:
                write_bpm(actual_path, bpm)

        return actual_path
