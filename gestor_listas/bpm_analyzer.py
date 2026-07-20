from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from mutagen import File as MutagenFile
from mutagen.id3 import ID3, TBPM
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus

from .audio import detect_bpm

AUDIO_EXTENSIONS = {".mp3", ".flac", ".ogg", ".m4a", ".wav", ".opus", ".wma"}


def get_bpm(filepath: Path) -> Optional[float]:
    try:
        return detect_bpm(filepath)
    except Exception:
        return None


BPM_TAG_KEYS = {
    ".mp3": "TBPM",
    ".flac": "BPM",
    ".ogg": "BPM",
    ".opus": "BPM",
    ".m4a": "----:com.apple.iTunes:BPM",
    ".aac": "----:com.apple.iTunes:BPM",
    ".wav": None,
    ".wma": None,
}


def _bpm_tag_key(ext: str) -> str | None:
    for key, tag in BPM_TAG_KEYS.items():
        if ext.endswith(key) or ext == key:
            return tag
    return None


def read_existing_bpm(filepath: Path) -> Optional[float]:
    ext = filepath.suffix.lower()
    try:
        if ext == ".mp3":
            tags = ID3(str(filepath))
            tbpm = tags.get("TBPM")
            if tbpm and tbpm.text:
                return float(tbpm.text[0])
        elif ext == ".flac":
            tags = FLAC(str(filepath))
            bpm = tags.get("BPM")
            if bpm:
                return float(bpm[0])
        elif ext == ".opus":
            tags = OggOpus(str(filepath))
            bpm = tags.get("BPM")
            if bpm:
                return float(bpm[0])
        elif ext == ".ogg":
            tags = OggVorbis(str(filepath))
            bpm = tags.get("BPM")
            if bpm:
                return float(bpm[0])
        elif ext in (".m4a", ".aac"):
            tags = MP4(str(filepath))
            key = "----:com.apple.iTunes:BPM"
            if key in tags:
                return float(tags[key][0].decode().strip())
            if "\xa9BPM" in tags:
                return float(tags["\xa9BPM"][0])
        else:
            tags = MutagenFile(str(filepath))
            if tags:
                for k in ("TBPM", "BPM", "bpm", "\xa9BPM"):
                    if k in tags:
                        val = tags[k]
                        if isinstance(val, list):
                            return float(val[0])
                        return float(val)
    except Exception:
        pass
    return None


def write_bpm(filepath: Path, bpm: float) -> bool:
    ext = filepath.suffix.lower()
    bpm_str = str(round(bpm))
    try:
        if ext == ".mp3":
            try:
                tags = ID3(str(filepath))
            except Exception:
                tags = ID3()
            tags["TBPM"] = TBPM(encoding=3, text=bpm_str)
            tags.save(str(filepath))
            return True
        elif ext == ".flac":
            tags = FLAC(str(filepath))
            tags["BPM"] = [bpm_str]
            tags.save()
            return True
        elif ext == ".ogg":
            tags = OggVorbis(str(filepath))
            tags["BPM"] = [bpm_str]
            tags.save()
            return True
        elif ext == ".opus":
            tags = OggOpus(str(filepath))
            tags["BPM"] = [bpm_str]
            tags.save()
            return True
        elif ext in (".m4a", ".aac"):
            tags = MP4(str(filepath))
            tags["----:com.apple.iTunes:BPM"] = [bpm_str.encode()]
            tags.save()
            return True
        else:
            tags = MutagenFile(str(filepath), easy=True)
            if tags is not None:
                tags["BPM"] = [bpm_str]
                tags.save()
                return True
    except Exception:
        pass
    return False


def analyze_directory(
    root: Path,
    recursive: bool = True,
    force: bool = False,
    extensions: set[str] | None = None,
) -> dict[str, int]:
    exts = extensions or AUDIO_EXTENSIONS
    stats: dict[str, int] = {"scanned": 0, "analyzed": 0, "tagged": 0, "skipped": 0, "errors": 0}

    files = sorted(root.rglob("*") if recursive else root.glob("*"))
    audio_files = [f for f in files if f.is_file() and f.suffix.lower() in exts]

    for filepath in audio_files:
        stats["scanned"] += 1

        if not force:
            existing = read_existing_bpm(filepath)
            if existing is not None:
                stats["skipped"] += 1
                continue

        sys.stdout.write(f"  {filepath.relative_to(root)} ... ")
        sys.stdout.flush()

        bpm = get_bpm(filepath)
        if bpm is None:
            stats["errors"] += 1
            print("ERROR")
            continue

        stats["analyzed"] += 1
        if write_bpm(filepath, bpm):
            stats["tagged"] += 1
            print(f"{bpm} BPM")
        else:
            stats["errors"] += 1
            print("ERROR al escribir tag")

    return stats


def parse_extensions(raw: str) -> set[str] | None:
    """Convierte 'mp3,flac' en {'.mp3', '.flac'}; None si está vacío."""
    if not raw:
        return None
    return {f".{e.strip().lstrip('.')}" for e in raw.split(",")}


def print_stats(stats: dict[str, int]) -> None:
    print()
    print(f"  Escaneados: {stats['scanned']}")
    print(f"  Saltados (ya tenían BPM): {stats['skipped']}")
    print(f"  Analizados: {stats['analyzed']}")
    print(f"  Etiquetados: {stats['tagged']}")
    print(f"  Errores: {stats['errors']}")


def run_analysis(path: str, recursive: bool, force: bool, extensions: str = "") -> dict[str, int]:
    """Lógica compartida entre el CLI principal y el main() de este módulo."""
    root = Path(path).resolve()
    if not root.is_dir():
        print(f"Error: '{root}' no es un directorio")
        sys.exit(1)

    print(f"Analizando {root} (recursivo={recursive})")
    stats = analyze_directory(root, recursive=recursive, force=force, extensions=parse_extensions(extensions))
    print_stats(stats)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Analiza BPM de canciones en un directorio")
    parser.add_argument("path", type=str, nargs="?", default=".", help="Directorio a analizar")
    parser.add_argument("-r", "--recursive", action="store_true", default=True, help="Buscar en subcarpetas (por defecto)")
    parser.add_argument("--no-recursive", action="store_false", dest="recursive", help="Solo carpeta actual")
    parser.add_argument("-f", "--force", action="store_true", help="Re-analizar aunque ya tenga BPM")
    parser.add_argument("-e", "--extensions", type=str, default="", help="Extensiones separadas por coma (ej: mp3,flac)")
    args = parser.parse_args()

    run_analysis(args.path, recursive=args.recursive, force=args.force, extensions=args.extensions)


if __name__ == "__main__":
    main()
