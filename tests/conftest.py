import os
from datetime import datetime

import pytest

from gestor_listas.model import Playlist, Track


@pytest.fixture(autouse=True)
def _clear_spotify_bearer() -> None:
    os.environ.pop("SPOTIFY_BEARER_TOKEN", None)


@pytest.fixture
def sample_track_1() -> Track:
    return Track(
        id="tr1",
        title="Bohemian Rhapsody",
        artist="Queen",
        album="A Night at the Opera",
        duration_ms=354000,
        isrc="GBUM71029604",
        uri="spotify:track:tr1",
    )


@pytest.fixture
def sample_track_2() -> Track:
    return Track(
        id="tr2",
        title="Stairway to Heaven",
        artist="Led Zeppelin",
        album="Led Zeppelin IV",
        duration_ms=482000,
    )


@pytest.fixture
def sample_playlist(sample_track_1: Track, sample_track_2: Track) -> Playlist:
    return Playlist(
        id="pl1",
        name="Classic Rock",
        description="Best classic rock songs",
        tracks=[sample_track_1, sample_track_2],
        owner="user123",
        public=True,
        source="manual",
        source_url="https://open.spotify.com/playlist/pl1",
        created_at=datetime(2025, 1, 1),
        updated_at=datetime(2025, 6, 1),
    )
