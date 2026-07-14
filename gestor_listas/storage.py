from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from .model import Playlist, Track


def get_default_db_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "gestor.db"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS playlists (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    owner       TEXT,
    public      INTEGER NOT NULL DEFAULT 0,
    source      TEXT,
    source_url  TEXT,
    created_at  TEXT,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS tracks (
    id          TEXT NOT NULL,
    playlist_id TEXT NOT NULL,
    title       TEXT NOT NULL,
    artist      TEXT NOT NULL,
    album       TEXT,
    duration_ms INTEGER,
    isrc        TEXT,
    uri         TEXT,
    position    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (playlist_id, id),
    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tracks_playlist ON tracks(playlist_id);

CREATE TABLE IF NOT EXISTS track_mappings (
    spotify_id  TEXT,
    deezer_id   TEXT,
    isrc        TEXT,
    confidence  REAL NOT NULL DEFAULT 1.0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (spotify_id, deezer_id)
);
"""


class Storage:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else get_default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ── Save ────────────────────────────────────────────────────

    def save_playlist(self, playlist: Playlist) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO playlists
               (id, name, description, owner, public, source, source_url, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                playlist.id,
                playlist.name,
                playlist.description,
                playlist.owner,
                int(playlist.public),
                playlist.source,
                playlist.source_url,
                playlist.created_at.isoformat() if playlist.created_at else None,
                playlist.updated_at.isoformat() if playlist.updated_at else None,
            ),
        )
        self._conn.execute("DELETE FROM tracks WHERE playlist_id = ?", (playlist.id,))
        for pos, track in enumerate(playlist.tracks):
            self._conn.execute(
                """INSERT INTO tracks
                   (id, playlist_id, title, artist, album, duration_ms, isrc, uri, position)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    track.id,
                    playlist.id,
                    track.title,
                    track.artist,
                    track.album,
                    track.duration_ms,
                    track.isrc,
                    track.uri,
                    pos,
                ),
            )
        self._conn.commit()

    # ── Load ────────────────────────────────────────────────────

    def load_playlist(self, playlist_id: str) -> Optional[Playlist]:
        row = self._conn.execute(
            "SELECT * FROM playlists WHERE id = ?", (playlist_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_playlist(row)

    def load_all_playlists(self) -> list[Playlist]:
        rows = self._conn.execute(
            "SELECT * FROM playlists ORDER BY name"
        ).fetchall()
        return [self._row_to_playlist(r) for r in rows]

    def load_playlists_by_source(self, source: str) -> list[Playlist]:
        rows = self._conn.execute(
            "SELECT * FROM playlists WHERE source = ? ORDER BY name", (source,)
        ).fetchall()
        return [self._row_to_playlist(r) for r in rows]

    # ── Delete ──────────────────────────────────────────────────

    def delete_playlist(self, playlist_id: str) -> None:
        self._conn.execute("DELETE FROM tracks WHERE playlist_id = ?", (playlist_id,))
        self._conn.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
        self._conn.commit()

    # ── Query ──────────────────────────────────────────────────

    def playlist_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM playlists").fetchone()[0]

    def track_count(self, playlist_id: Optional[str] = None) -> int:
        if playlist_id:
            return self._conn.execute(
                "SELECT COUNT(*) FROM tracks WHERE playlist_id = ?", (playlist_id,)
            ).fetchone()[0]
        return self._conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]

    # ── Internal helpers ────────────────────────────────────────

    def _row_to_playlist(self, row: sqlite3.Row) -> Playlist:
        track_rows = self._conn.execute(
            "SELECT * FROM tracks WHERE playlist_id = ? ORDER BY position",
            (row["id"],),
        ).fetchall()
        tracks = [
            Track(
                id=t["id"],
                title=t["title"],
                artist=t["artist"],
                album=t["album"],
                duration_ms=t["duration_ms"],
                isrc=t["isrc"],
                uri=t["uri"],
            )
            for t in track_rows
        ]
        from datetime import datetime
        created = datetime.fromisoformat(row["created_at"]) if row["created_at"] else None
        updated = datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None
        return Playlist(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            owner=row["owner"],
            public=bool(row["public"]),
            source=row["source"],
            source_url=row["source_url"],
            created_at=created,
            updated_at=updated,
            tracks=tracks,
        )
