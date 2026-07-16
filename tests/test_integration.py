"""Tests de integración REALES contra los servicios (sin mocks).

Estos tests tocan la red y/o binarios externos (yt-dlp, ffmpeg), por lo que
están marcados como `integration` y NO se ejecutan por defecto. Para lanzarlos:

    pytest -m integration

Requisitos:
- YouTube: `yt-dlp` instalado y en el PATH.
- Spotify (scraping): acceso a internet.
- Deezer: variable de entorno DEEZER_ARL válida (si no, se omiten).
- Descargas: además `ffmpeg` en el PATH.

Los tests usan playlists públicas estables y aceptan cierta variabilidad
(los servicios cambian contenido), verificando estructura más que valores exactos.
"""

import os
import shutil

import pytest

from gestor_listas.model import Playlist, Track
from gestor_listas.providers.spotify import SpotifyProvider
from gestor_listas.providers.youtube import YouTubeProvider

pytestmark = pytest.mark.integration


def _has(binary: str) -> bool:
    return shutil.which(binary) is not None


# ── YouTube (yt-dlp) ─────────────────────────────────────────────

@pytest.mark.skipif(not _has("yt-dlp"), reason="yt-dlp no está instalado")
class TestYouTubeReal:
    # Playlist pública estable de Google ("Google Search Stories").
    PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLBCF2DAC6FFB574DE"

    def test_read_public_playlist(self) -> None:
        yt = YouTubeProvider()
        pl = yt.get_playlist_by_url(self.PLAYLIST_URL)
        assert isinstance(pl, Playlist)
        assert pl.name
        assert pl.track_count > 0
        assert pl.source == "youtube"
        first = pl.tracks[0]
        assert first.id
        assert first.title
        assert first.uri and "youtube.com/watch" in first.uri

    def test_search_track(self) -> None:
        yt = YouTubeProvider()
        track = yt.search_track("Bohemian Rhapsody", "Queen")
        assert track is not None
        assert isinstance(track, Track)
        assert track.id
        assert track.uri and "youtube.com/watch" in track.uri


# ── Spotify (scraping, sin credenciales) ─────────────────────────

class TestSpotifyScrapingReal:
    # "Today's Top Hits": playlist pública muy estable de Spotify.
    PLAYLIST_URL = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"

    def test_read_public_playlist(self) -> None:
        sp = SpotifyProvider(use_scraping=True)
        pl = sp.get_playlist_by_url(self.PLAYLIST_URL)
        assert isinstance(pl, Playlist)
        assert pl.name
        assert pl.track_count > 0
        assert pl.source == "spotify"
        first = pl.tracks[0]
        assert first.id
        assert first.title
        assert first.artist


# ── Deezer (requiere ARL) ────────────────────────────────────────

@pytest.mark.skipif(not os.getenv("DEEZER_ARL"), reason="DEEZER_ARL no configurado")
class TestDeezerReal:
    def test_read_own_playlists(self) -> None:
        from gestor_listas.providers.deezer import DeezerProvider

        dz = DeezerProvider()
        playlists = dz.get_playlists()
        assert isinstance(playlists, list)
        # Puede estar vacío si la cuenta no tiene playlists; solo validamos tipos.
        for pl in playlists:
            assert isinstance(pl, Playlist)
            assert pl.source == "deezer"


# ── Descarga end-to-end (YouTube, requiere ffmpeg) ───────────────

@pytest.mark.skipif(
    not (_has("yt-dlp") and _has("ffmpeg")),
    reason="yt-dlp y/o ffmpeg no están instalados",
)
class TestDownloadReal:
    def test_download_track_from_youtube(self, tmp_path) -> None:
        from gestor_listas.downloaders.youtube import YouTubeDownloader

        # Vídeo corto y estable (Creative Commons / dominio público recomendado).
        track = Track(
            id="aqz-KE-bpKQ",
            title="Big Buck Bunny",
            artist="Blender Foundation",
            uri="https://www.youtube.com/watch?v=aqz-KE-bpKQ",
        )
        dl = YouTubeDownloader(output_format="mp3")
        path = dl.download(track, tmp_path)
        assert path is not None
        assert path.exists()
        assert path.stat().st_size > 0
