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

INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_stations_code
ON stations(code);

CREATE INDEX IF NOT EXISTS idx_stations_status
ON stations(status);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def initialize_database(conn: sqlite3.Connection) -> None:
    conn.execute(STATION_SCHEMA)
    conn.executescript(INDEX_SCHEMA)
    conn.commit()


def get_station(conn: sqlite3.Connection, station_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM stations WHERE id = ?",
        (station_id,),
    ).fetchone()


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


def station_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM stations").fetchone()[0]
