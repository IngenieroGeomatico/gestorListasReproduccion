from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from ..model import Track


class YouTubeDownloader:
    def __init__(self, output_format: str = "best") -> None:
        self.output_format = output_format

    def _get_url(self, track: Track) -> str:
        if track.uri and "youtube.com/watch?v=" in track.uri:
            return track.uri
        return f"ytsearch:{track.artist} - {track.title}"

    def download(self, track: Track, output_dir: str | Path) -> Optional[Path]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        safe_name = f"{track.artist} - {track.title}".replace("/", "_").replace("\0", "")

        fmt = self.output_format

        if fmt in ("best", "opus"):
            cmd = [
                "yt-dlp",
                "-f", "bestaudio[ext=webm]/bestaudio",
                "--extract-audio",
                "--audio-format", "opus",
                "--audio-quality", "0",
                "--embed-thumbnail",
                "--embed-metadata",
                "-o", str(output_dir / f"{safe_name}.%(ext)s"),
                "--no-playlist",
                self._get_url(track),
            ]
        else:
            cmd = [
                "yt-dlp",
                "-f", "bestaudio/best",
                "--extract-audio",
                "--audio-format", fmt,
                "--audio-quality", "0",
                "--embed-thumbnail",
                "--embed-metadata",
                "-o", str(output_dir / f"{safe_name}.%(ext)s"),
                "--no-playlist",
                self._get_url(track),
            ]

        import shutil
        deno_path = shutil.which("deno")
        if deno_path:
            cmd.insert(1, "--js-runtimes")
            cmd.insert(2, f"deno:{deno_path}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            return None

        output_path = None
        for f in output_dir.iterdir():
            if f.stem == safe_name and f.suffix in {".mp3", ".m4a", ".opus", ".webm", ".ogg"}:
                output_path = f
                break

        if not output_path:
            for f in output_dir.iterdir():
                if f.stem.startswith(safe_name[:30]):
                    output_path = f
                    break

        if output_path and output_path.suffix.lower() in (".webp", ".png", ".jpg"):
            output_path = None

        if output_path:
            from ..bpm_analyzer import get_bpm, write_bpm
            bpm = get_bpm(output_path)
            if bpm is not None:
                write_bpm(output_path, bpm)

        return output_path
