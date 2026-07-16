from __future__ import annotations

import argparse

from .bpm_analyzer import run_analysis
from .downloaders import DownloadManager
from .storage import Storage
from .sync import run as sync_run


def cmd_sync(args: argparse.Namespace) -> None:
    result = sync_run()
    labels = {"spotify": "Spotify", "deezer": "Deezer", "youtube": "YouTube"}
    total = 0
    for source, playlists in result.items():
        count = len(playlists)
        total += count
        print(f"{labels.get(source, source)}: {count} playlists importadas")
    print(f"Total: {total} playlists")


def cmd_list(args: argparse.Namespace) -> None:
    with Storage() as storage:
        if args.source:
            playlists = storage.load_playlists_by_source(args.source)
        else:
            playlists = storage.load_all_playlists()

    if not playlists:
        print("No hay playlists almacenadas. Ejecuta 'gestor-listas sync' primero.")
        return

    for pl in playlists:
        src = f"[{pl.source}]" if pl.source else ""
        print(f"  {pl.id:<24} {src:<10} {pl.track_count:>4} temas  {pl.name}")
    print(f"\nTotal: {len(playlists)} playlists")


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
    run_analysis(args.path, recursive=args.recursive, force=args.force, extensions=args.extensions)


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
