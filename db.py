from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Mapping, Any


STATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS stations (
    id              INTEGER PRIMARY KEY,
    code            TEXT NOT NULL,
    city            TEXT,
    latitude        REAL,
    longitude       REAL,
    elevation_m     REAL,
    status          TEXT,
    camera          TEXT,
    radio           TEXT,
    first_seen_utc  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_utc   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CAPTURE_SCHEMA = """
CREATE TABLE IF NOT EXISTS captures (
    id                  INTEGER PRIMARY KEY,
    station_code        TEXT NOT NULL,
    station_id          INTEGER,
    city                TEXT,
    timestamp_utc       TEXT NOT NULL,
    image_url           TEXT NOT NULL,
    local_path          TEXT,
    file_size_bytes     INTEGER,
    sha256              TEXT,
    width               INTEGER,
    height              INTEGER,
    download_status     TEXT NOT NULL DEFAULT 'metadata_only',
    first_seen_utc      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_utc    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (station_id) REFERENCES stations(id)
);
"""

HARVEST_SCHEMA = """
CREATE TABLE IF NOT EXISTS harvest_status (
    capture_id          INTEGER PRIMARY KEY,
    status              TEXT NOT NULL,
    attempts            INTEGER NOT NULL DEFAULT 0,
    last_error          TEXT,
    first_attempt_utc   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_attempt_utc    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_stations_code
ON stations(code);

CREATE INDEX IF NOT EXISTS idx_stations_status
ON stations(status);

CREATE INDEX IF NOT EXISTS idx_captures_station_code
ON captures(station_code);

CREATE INDEX IF NOT EXISTS idx_captures_station_id
ON captures(station_id);

CREATE INDEX IF NOT EXISTS idx_captures_timestamp
ON captures(timestamp_utc);

CREATE INDEX IF NOT EXISTS idx_harvest_status
ON harvest_status(status);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


def initialize_database(conn: sqlite3.Connection) -> None:
    conn.execute(STATION_SCHEMA)
    conn.execute(CAPTURE_SCHEMA)
    conn.execute(HARVEST_SCHEMA)
    conn.executescript(INDEX_SCHEMA)
    conn.commit()


def get_station(conn: sqlite3.Connection, station_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM stations WHERE id = ?",
        (station_id,),
    ).fetchone()


def resolve_station_id(
    conn: sqlite3.Connection,
    station_code: str,
    city: str | None = None,
) -> int | None:
    rows = conn.execute(
        "SELECT id, city FROM stations WHERE code = ?",
        (station_code,),
    ).fetchall()

    if len(rows) == 1:
        return int(rows[0]["id"])

    if city is not None:
        matches = [row for row in rows if row["city"] == city]
        if len(matches) == 1:
            return int(matches[0]["id"])

    return None


def upsert_station(conn: sqlite3.Connection, station: Mapping[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO stations (
            id, code, city, latitude, longitude, elevation_m,
            status, camera, radio, first_seen_utc, last_seen_utc
        )
        VALUES (
            :id, :code, :city, :latitude, :longitude, :elevation_m,
            :status, :camera, :radio, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        ON CONFLICT(id) DO UPDATE SET
            code          = excluded.code,
            city          = excluded.city,
            latitude      = excluded.latitude,
            longitude     = excluded.longitude,
            elevation_m   = excluded.elevation_m,
            status        = excluded.status,
            camera        = excluded.camera,
            radio         = excluded.radio,
            last_seen_utc = CURRENT_TIMESTAMP
        """,
        station,
    )


def upsert_capture(conn: sqlite3.Connection, capture: Mapping[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO captures (
            id, station_code, station_id, city, timestamp_utc, image_url,
            local_path, file_size_bytes, sha256, width, height,
            download_status, first_seen_utc, last_updated_utc
        )
        VALUES (
            :id, :station_code, :station_id, :city, :timestamp_utc, :image_url,
            :local_path, :file_size_bytes, :sha256, :width, :height,
            :download_status, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        ON CONFLICT(id) DO UPDATE SET
            station_code     = excluded.station_code,
            station_id       = excluded.station_id,
            city             = excluded.city,
            timestamp_utc    = excluded.timestamp_utc,
            image_url        = excluded.image_url,
            local_path       = excluded.local_path,
            file_size_bytes  = excluded.file_size_bytes,
            sha256           = excluded.sha256,
            width            = excluded.width,
            height           = excluded.height,
            download_status  = excluded.download_status,
            last_updated_utc = CURRENT_TIMESTAMP
        """,
        capture,
    )


def get_capture_row(conn: sqlite3.Connection, capture_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM captures WHERE id = ?",
        (capture_id,),
    ).fetchone()


def mark_harvest_status(
    conn: sqlite3.Connection,
    capture_id: int,
    status: str,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO harvest_status (
            capture_id, status, attempts, last_error,
            first_attempt_utc, last_attempt_utc
        )
        VALUES (?, ?, 1, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(capture_id) DO UPDATE SET
            status           = excluded.status,
            attempts         = harvest_status.attempts + 1,
            last_error       = excluded.last_error,
            last_attempt_utc = CURRENT_TIMESTAMP
        """,
        (capture_id, status, error),
    )


def get_harvest_states(
    conn: sqlite3.Connection,
    start_id: int,
    end_id: int,
) -> dict[int, sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT h.capture_id, h.status, h.attempts, h.last_error,
               c.local_path
        FROM harvest_status h
        LEFT JOIN captures c ON c.id = h.capture_id
        WHERE h.capture_id BETWEEN ? AND ?
        """,
        (start_id, end_id),
    ).fetchall()
    return {int(row["capture_id"]): row for row in rows}


def station_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM stations").fetchone()[0]


def capture_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0]
