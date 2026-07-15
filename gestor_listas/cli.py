from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .bpm_analyzer import analyze_directory
from .downloaders import DownloadManager
from .providers.youtube import YouTubeProvider
from .storage import Storage
from .sync import load_sources, import_spotify_urls, import_deezer_urls, import_deezer_all, import_youtube_urls


def cmd_sync(args: argparse.Namespace) -> None:
    sources = load_sources()
    storage = Storage()
    total = 0

    spotify_urls = sources.get("spotify", [])
    if spotify_urls:
        pls = import_spotify_urls(spotify_urls, storage)
        print(f"Spotify: {len(pls)} playlists importadas")
        total += len(pls)

    deezer_urls = sources.get("deezer", [])
    if deezer_urls:
        pls = import_deezer_urls(deezer_urls, storage)
        print(f"Deezer: {len(pls)} playlists importadas")
        total += len(pls)
    else:
        pls = import_deezer_all(storage)
        print(f"Deezer: {len(pls)} playlists importadas (todas)")
        total += len(pls)

    youtube_urls = sources.get("youtube", [])
    if youtube_urls:
        pls = import_youtube_urls(youtube_urls, storage)
        print(f"YouTube: {len(pls)} playlists importadas")
        total += len(pls)

    storage.close()
    print(f"Total: {total} playlists")


def cmd_list(args: argparse.Namespace) -> None:
    storage = Storage()
    if args.source:
        playlists = storage.load_playlists_by_source(args.source)
    else:
        playlists = storage.load_all_playlists()

    if not playlists:
        print("No hay playlists almacenadas. Ejecuta 'gestor-listas sync' primero.")
        storage.close()
        return

    for pl in playlists:
        src = f"[{pl.source}]" if pl.source else ""
        print(f"  {pl.id:<24} {src:<10} {pl.track_count:>4} temas  {pl.name}")
    print(f"\nTotal: {len(playlists)} playlists")
    storage.close()


def cmd_download(args: argparse.Namespace) -> None:
    manager = DownloadManager(
        output_dir=args.output,
        prefer=args.prefer,
        audio_format=args.format,
    )

    results = manager.download_from_storage(
        playlist_id=args.playlist_id,
        source=args.source,
        use_subfolder=not args.no_subfolder,
        limit=args.limit,
    )

    ok = sum(1 for r in results if r.path)
    err = sum(1 for r in results if r.error)
    print(f"\nDescargados: {ok}  |  Errores: {err}")


def cmd_bpm(args: argparse.Namespace) -> None:
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"Error: '{root}' no es un directorio")
        sys.exit(1)

    exts = None
    if args.extensions:
        exts = set(f".{e.strip().lstrip('.')}" for e in args.extensions.split(","))

    print(f"Analizando {root} (recursivo={args.recursive})")
    stats = analyze_directory(root, recursive=args.recursive, force=args.force, extensions=exts)
    print()
    print(f"  Escaneados: {stats['scanned']}")
    print(f"  Saltados (ya tenían BPM): {stats['skipped']}")
    print(f"  Analizados: {stats['analyzed']}")
    print(f"  Etiquetados: {stats['tagged']}")
    print(f"  Errores: {stats['errors']}")


def app() -> None:
    parser = argparse.ArgumentParser(
        prog="gestor-listas",
        description="Gestor de listas de reproducción entre servicios de streaming",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # sync
    p_sync = sub.add_parser("sync", help="Importar playlists desde sources.json")
    p_sync.set_defaults(func=cmd_sync)

    # list
    p_list = sub.add_parser("list", help="Listar playlists almacenadas")
    p_list.add_argument("-s", "--source", choices=["spotify", "deezer", "youtube"], help="Filtrar por fuente")
    p_list.set_defaults(func=cmd_list)

    # download
    p_dl = sub.add_parser("download", help="Descargar canciones de playlists almacenadas")
    p_dl.add_argument("-p", "--playlist-id", help="ID de playlist específica")
    p_dl.add_argument("-s", "--source", choices=["spotify", "deezer", "youtube"], help="Filtrar por fuente")
    p_dl.add_argument("-o", "--output", default="downloads", help="Directorio de salida (default: downloads)")
    p_dl.add_argument("--prefer", choices=["deezer", "youtube"], default="deezer", help="Fuente preferida (default: deezer)")
    p_dl.add_argument("--no-subfolder", action="store_true", help="No crear subcarpeta por playlist")
    p_dl.add_argument("--limit", type=int, default=0, help="Descargar solo los primeros N temas (0 = todos)")
    p_dl.add_argument("-f", "--format", choices=["best", "opus", "mp3", "m4a"], default="best",
                      help="Formato de audio (default: best = nativo, sin recodificar)")
    p_dl.set_defaults(func=cmd_download)

    # bpm
    p_bpm = sub.add_parser("bpm", help="Analizar BPM de archivos de audio")
    p_bpm.add_argument("path", nargs="?", default=".", help="Directorio a analizar (default: actual)")
    p_bpm.add_argument("-r", "--recursive", action="store_true", default=True, help="Buscar en subcarpetas")
    p_bpm.add_argument("--no-recursive", action="store_false", dest="recursive", help="Solo carpeta actual")
    p_bpm.add_argument("-f", "--force", action="store_true", help="Re-analizar aunque ya tenga BPM")
    p_bpm.add_argument("-e", "--extensions", default="", help="Extensiones separadas por coma (ej: mp3,flac)")
    p_bpm.set_defaults(func=cmd_bpm)

    # Parse and dispatch
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    app()
