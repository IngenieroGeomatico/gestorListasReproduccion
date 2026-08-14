"""Reclasifica la carpeta Remember/ usando resultados ya obtenidos en preview.

Reutiliza log/reclassify_preview.log para no re-consultar MusicBrainz:
- Los temas con género real (Dance, House, Trance...) de MB/keyword se mueven
  a ese género.
- Los que quedaron en 'Sin género' se reparten por regla del usuario:
  título con 'instrumental'/'dub' -> Melodías; el resto -> Cantaditas
  (los remember/eurodance de los 90 casi siempre traen vocal).
Se escribe el género en los tags al mover.
"""

import argparse
import re
import shutil
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.id3 import ID3, TCON
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
from gestor_listas.audio import write_genre
from gestor_listas.renamer import resolve_library_target, TrackInfo

UNKNOWN_GENRE = "Sin género"
INSTRUMENTAL_PATTERN = re.compile(
    r"\b(instrumental|inst\.?|dub mix|dub ?version|karaoke|acapella\s-?\s?backing|"
    r"\bdub\b)(\b|\s|-|$)", re.IGNORECASE
)


def parse_preview(log: Path) -> dict[str, str]:
    """Parsea el log del preview: nombre de archivo -> género (MB/keyword)."""
    result: dict[str, str] = {}
    current = None
    for line in log.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\[(.+?)\]$", line)
        if m and line.endswith("]"):
            current = m.group(1)
            result[current] = UNKNOWN_GENRE
            continue
        if "Género" in line and current:
            g = re.search(r"Género (?:\((?:MusicBrainz|por palabras clave)\))?: (.+)$", line)
            if g and g.group(1).strip():
                result[current] = g.group(1).strip()
    return result


def decide(genre: str, title: str) -> str:
    if genre != UNKNOWN_GENRE:
        return genre
    if INSTRUMENTAL_PATTERN.search(title):
        return "Melodías"
    return "Cantaditas"


def move(source: Path, dest_root: Path, genre: str) -> Path | None:
    track = TrackInfo(title=source.stem, artist="")
    directory = dest_root / genre
    target = resolve_library_target(directory, track, source.suffix)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        try:
            source.rename(target)
        except OSError:
            shutil.move(str(source), str(target))
    except OSError as exc:
        print(f"    No se pudo mover {source.name}: {exc}")
        return None
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--log", type=Path, default=Path("log/reclassify_preview.log"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    genres = parse_preview(args.log)
    files = sorted(p for p in args.folder.glob("*.mp3") if p.is_file())
    print(f"Reclasificando {len(files)} archivos de {args.folder}")

    stats: dict[str, int] = {}
    missing = 0
    for path in files:
        genre = decide(genres.get(path.name, UNKNOWN_GENRE), path.stem)
        stats[genre] = stats.get(genre, 0) + 1
        if path.name not in genres:
            missing += 1

        if not args.apply:
            print(f"  [preview] {path.name[:50]:50s} -> {genre}")
            continue

        target = move(path, args.dest, genre)
        if target is None:
            continue
        write_genre(str(target), genre)
        print(f"  {genre:12s} {path.name[:45]}")

    if missing:
        print(f"\n  Aviso: {missing} archivos sin entrada en el log (buscar género en vuelo)")
    print("\n=== Resumen ===")
    for genre, count in sorted(stats.items(), key=lambda kv: -kv[1]):
        print(f"  {count:4d}  {genre}")
    print(f"  Total: {len(files)}")


if __name__ == "__main__":
    main()