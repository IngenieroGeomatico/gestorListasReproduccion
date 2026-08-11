#!/usr/bin/env python3
"""Importa todas las playlists de SQLite a YouTube con reanudación.

La cuota diaria de la YouTube Data API (10.000 unidades) no permite volcar todas
las playlists en un solo día. Este script:

- Si la playlist ya existe en YouTube (por nombre exacto) NO la recrea: la
  reutiliza y compara sus vídeos para añadir solo los temas que falten.
- La búsqueda de vídeos se hace con yt-dlp (gratis e ilimitado): la API de
  YouTube limita search.list a 100 consultas/día. El resultado se cachea
  (título+artista → video_id) para no repetir entre playlists.
- Guarda el progreso en `data/youtube_import_state.json` (playlists creadas,
  pistas añadidas, búsquedas cacheadas) y se puede reanudar cualquier día.
- Para cuando se consume el presupuesto de unidades (`--budget`, por defecto
  9.000) dejando la cuota del día intacta y el estado listo para retomar.
- Por último trae a SQLite las playlists de YouTube que no existan localmente
  (importadas con yt-dlp, sin gastar cuota); se puede desactivar con --no-pull.

Uso:
    python scripts/import_all_to_youtube.py                  # Todo, ~9.000 unidades
    python scripts/import_all_to_youtube.py --budget 3000    # Solo un trozo de la cuota
    python scripts/import_all_to_youtube.py --dry-run        # Simula sin tocar la API
    python scripts/import_all_to_youtube.py --reset          # Borra el estado previo
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

from gestor_listas.errors import ProviderError
from gestor_listas.importers.youtube import YouTubeImporter
from gestor_listas.providers.youtube import YouTubeProvider
from gestor_listas.storage import Storage

# Unidades que consume cada operación de la YouTube Data API v3.
UNITS_CREATE_PLAYLIST = 50
UNITS_ADD_VIDEO = 50
# Lectura: playlists.list / playlistItems.list cuestan 1 unidad por página.
UNITS_LIST_ITEM = 1
# NOTA: la búsqueda de vídeos NO usa la API (tiene un límite duro de 100
# consultas/día); se hace con yt-dlp, que es gratuito e ilimitado.

STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "youtube_import_state.json"


def _normalize(text: str) -> str:
    return " ".join(text.split()).lower()


def _search_key(title: str, artist: str) -> str:
    return f"{_normalize(artist)}\u0001{_normalize(title)}"


def _search_video_ytdlp(provider: YouTubeProvider, title: str, artist: str) -> Optional[str]:
    """Busca un vídeo con yt-dlp (gratis, sin cuota de la API)."""
    track = provider.search_track(title, artist)
    if track and track.uri and "youtube.com/watch?v=" in track.uri:
        return track.uri.split("v=", 1)[1].split("&", 1)[0]
    return None


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"playlists": {}, "search_cache": {}}


def save_state(state: dict, dry_run: bool = False) -> None:
    if dry_run:
        return
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def playlist_done(state: dict, playlist_id: str, track_ids: list) -> bool:
    pl = state["playlists"].get(playlist_id)
    if not pl or not pl.get("youtube_id"):
        return False
    handled = set(pl.get("added_track_ids", [])) | set(pl.get("missing_track_ids", []))
    return handled == set(track_ids)


def estimate_total_units(playlists: list, state: dict) -> int:
    total = 0
    for pl in playlists:
        if playlist_done(state, pl.id, [t.id for t in pl.tracks]):
            continue
        total += UNITS_CREATE_PLAYLIST
        st = state["playlists"].get(pl.id, {})
        handled = set(st.get("added_track_ids", [])) | set(st.get("missing_track_ids", []))
        for track in pl.tracks:
            if track.id not in handled:
                total += UNITS_ADD_VIDEO
    return total


def _push_playlists(playlists: list, state: dict, importer: YouTubeImporter,
                    yt_provider: Optional[YouTubeProvider], units: int, args: argparse.Namespace) -> int:
    """Empuja cada playlist local a YouTube, añadiendo solo los temas que falten.

    Modifica `state` y `yt_provider` in place y devuelve las unidades consumidas.
    """
    for pl in sorted(playlists, key=lambda p: p.track_count):
        track_ids = [t.id for t in pl.tracks]
        if playlist_done(state, pl.id, track_ids):
            continue

        pl_state = state["playlists"].setdefault(pl.id, {})

        if not pl_state.get("youtube_id"):
            if units + UNITS_LIST_ITEM + UNITS_CREATE_PLAYLIST > args.budget:
                print(f"\nPresupuesto consumido ({units} unidades). "
                      f"Ejecuta de nuevo mañana para continuar (antes de {pl.name}).")
                break

            if args.dry_run:
                pl_state["youtube_id"] = f"PL_DRYRUN_{pl.id}"
                pl_state["youtube_url"] = "https://www.youtube.com/playlist?list=DRYRUN"
                print(f"[dry-run] Crearía playlist: {pl.name!r}")
                units += UNITS_CREATE_PLAYLIST
            else:
                existing_pl = importer.find_playlist_by_name(pl.name)
                units += UNITS_LIST_ITEM
                if existing_pl:
                    pl_state["youtube_id"] = existing_pl
                    pl_state["youtube_url"] = f"https://www.youtube.com/playlist?list={existing_pl}"
                    print(f"Playlist ya existente (no se recrea): {pl.name} → {pl_state['youtube_url']}")
                else:
                    created = importer.create_playlist(pl.name, pl.description or "", public=pl.public)
                    pl_state["youtube_id"] = created.id
                    pl_state["youtube_url"] = created.source_url
                    print(f"Playlist creada: {pl.name} → {created.source_url}")
                    units += UNITS_CREATE_PLAYLIST
            save_state(state, args.dry_run)

        # Vídeos ya presentes en la playlist de YouTube: solo se añaden los que falten.
        existing = Counter()
        if not args.dry_run and pl_state.get("youtube_id"):
            if units + UNITS_LIST_ITEM > args.budget:
                print(f"\nPresupuesto consumido ({units} unidades). "
                      f"Ejecuta de nuevo mañana para continuar ({pl.name}).")
                break
            existing = Counter(importer.get_playlist_video_ids(pl_state["youtube_id"]))
            units += UNITS_LIST_ITEM

        added = pl_state.setdefault("added_track_ids", [])
        missing = pl_state.setdefault("missing_track_ids", [])
        handled = set(added) | set(missing)

        for track in pl.tracks:
            if track.id in handled:
                continue

            if units + UNITS_ADD_VIDEO > args.budget:
                print(f"\nPresupuesto consumido ({units} unidades). "
                      f"Ejecuta de nuevo mañana para continuar ({pl.name} a medias).")
                break

            video_id = None
            if track.uri and "youtube.com/watch?v=" in track.uri:
                video_id = track.uri.split("v=", 1)[1].split("&", 1)[0]

            if not video_id:
                key = _search_key(track.title, track.artist)
                if key in state["search_cache"]:
                    video_id = state["search_cache"][key]
                else:
                    if args.dry_run:
                        video_id = "DRYRUN_VIDEO"
                    else:
                        if yt_provider is None:
                            yt_provider = YouTubeProvider()
                        video_id = _search_video_ytdlp(yt_provider, track.title, track.artist)
                    state["search_cache"][key] = video_id or None
                    save_state(state, args.dry_run)

            if not video_id:
                missing.append(track.id)
                print(f"  X No encontrado: {track.artist} - {track.title}")
                save_state(state, args.dry_run)
                continue

            if existing.get(video_id, 0) > 0:
                # Ya está en la playlist de YouTube: no se vuelve a añadir.
                existing[video_id] -= 1
                pl_state["added_track_ids"].append(track.id)
                print(f"  = Ya estaba: {track.artist} - {track.title}")
                save_state(state, args.dry_run)
                continue

            if args.dry_run:
                pl_state.setdefault("added_track_ids", []).append(track.id)
                print(f"  [dry-run] + {track.artist} - {track.title}")
            else:
                importer.add_video_to_playlist(pl_state["youtube_id"], video_id)
                pl_state["added_track_ids"].append(track.id)
                print(f"  + {track.artist} - {track.title} ({track.id[:8]}…)")
            units += UNITS_ADD_VIDEO
            save_state(state, args.dry_run)

        done = len(added) + len(missing)
        print(f"[{done}/{len(track_ids)}] {pl.name}")

    return units


def pull_missing_from_youtube(importer: YouTubeImporter, state: dict, units: int, budget: int,
                              dry_run: bool, yt_provider: Optional[YouTubeProvider] = None) -> int:
    """Trae a SQLite las playlists de YouTube que no existen localmente (por nombre).

    La importación se hace con yt-dlp (gratis, sin consumir cuota de la API);
    solo el listado de playlists del usuario cuesta 1 unidad por página.
    """
    if units + UNITS_LIST_ITEM > budget:
        print(f"\nPresupuesto consumido ({units} unidades). "
              "No se traen playlists de YouTube en esta ejecución.")
        return units

    if dry_run:
        print("\n[dry-run] Se importarían desde YouTube las playlists no presentes en SQLite.")
        return units

    yt_playlists = importer.get_my_playlists()
    units += UNITS_LIST_ITEM

    with Storage() as storage:
        local_names = {_normalize(p.name) for p in storage.load_all_playlists()}
        pulled = set(state.get("pulled_from_youtube", []))

        for ypl in yt_playlists:
            if ypl.id in pulled or _normalize(ypl.name) in local_names:
                continue
            if yt_provider is None:
                yt_provider = YouTubeProvider()
            imported = yt_provider.get_playlist_by_url(ypl.source_url)
            storage.save_playlist(imported)
            state.setdefault("pulled_from_youtube", []).append(ypl.id)
            save_state(state, False)
            print(f"Importada desde YouTube: {imported.name} ({len(imported.tracks)} temas)")

    return units


def main() -> int:
    parser = argparse.ArgumentParser(description="Importa todas las playlists a YouTube con reanudación")
    parser.add_argument("--budget", type=int, default=9000,
                        help="Máximo de unidades de API a consumir en esta ejecución (default: 9000)")
    parser.add_argument("--dry-run", action="store_true", help="Simular sin llamar a la API")
    parser.add_argument("--reset", action="store_true", help="Borrar el estado previo y empezar de cero")
    parser.add_argument("--no-pull", action="store_true",
                        help="No traer playlists de YouTube ausentes en SQLite")
    args = parser.parse_args()

    if args.reset and STATE_FILE.exists():
        STATE_FILE.unlink()

    state = load_state()
    importer = YouTubeImporter()
    yt_provider: Optional[YouTubeProvider] = None
    units = 0

    with Storage() as storage:
        playlists = storage.load_all_playlists()

    if not playlists:
        print("No hay playlists almacenadas. Ejecuta primero 'gestor-listas sync'.")
        return 1

    remaining = estimate_total_units(playlists, state)
    print(f"{len(playlists)} playlists | {sum(p.track_count for p in playlists)} pistas "
          f"| quedan ~{remaining} unidades por consumir | presupuesto: {args.budget}")

    try:
        units = _push_playlists(playlists, state, importer, yt_provider, units, args)
    except ProviderError as exc:
        if "Cuota" not in str(exc):
            raise
        print(f"\nCuota diaria de la API agotada ({units} unidades consumidas). "
              "El progreso está guardado; ejecuta de nuevo mañana.")

    if not args.no_pull:
        units = pull_missing_from_youtube(importer, state, units, args.budget, args.dry_run, yt_provider)

    print(f"\nCompletado: {units} unidades consumidas en esta ejecución.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
