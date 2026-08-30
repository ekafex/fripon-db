from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

import requests

from db import get_station, upsert_station
from http_utils import get, make_session


BASE_URL = "https://fireball.fripon.org"
STATION_ENDPOINT = f"{BASE_URL}/ajax/liste_station.ajax.php"
STATION_PAGE = f"{BASE_URL}/list_station.php"


@dataclass
class StationUpdateReport:
    remote_records: int
    parsed_records: int
    inserted: int
    changed: int
    unchanged: int
    duplicate_ids: list[int]
    duplicate_codes: list[str]
    suspicious_coordinates: list[str]


def _datatable_params(length: int = 500) -> dict[str, str]:
    p = {
        "draw": "1",
        "order[0][column]": "2",
        "order[0][dir]": "desc",
        "start": "0",
        "length": str(length),
        "search[value]": "",
        "search[regex]": "false",
    }

    for i in range(9):
        p[f"columns[{i}][data]"] = str(i)
        p[f"columns[{i}][name]"] = ""
        p[f"columns[{i}][searchable]"] = "true"
        p[f"columns[{i}][orderable]"] = "true"
        p[f"columns[{i}][search][value]"] = ""
        p[f"columns[{i}][search][regex]"] = "false"

    return p


def _parse_number(value: str, unit: str = "") -> float:
    return float(value.replace(unit, "").strip())


def parse_station_row(row: list[Any]) -> dict[str, Any]:
    if len(row) != 9:
        raise ValueError(f"Expected 9 station fields, got {len(row)}: {row!r}")

    (
        station_id,
        code,
        city,
        latitude,
        longitude,
        elevation,
        status,
        camera,
        radio,
    ) = row

    return {
        "id": int(station_id),
        "code": str(code).strip(),
        "city": str(city).strip(),
        "latitude": _parse_number(str(latitude), "°"),
        "longitude": _parse_number(str(longitude), "°"),
        "elevation_m": _parse_number(str(elevation), "m"),
        "status": str(status).strip(),
        "camera": str(camera).strip(),
        "radio": str(radio).strip(),
    }


def fetch_stations(
    session: requests.Session | None = None,
    timeout: int = 30,
) -> tuple[list[dict[str, Any]], int]:
    own_session = session is None
    if session is None:
        session = make_session(referer=STATION_PAGE)

    get(session, STATION_PAGE, timeout=timeout)

    r = get(
        session,
        STATION_ENDPOINT,
        params=_datatable_params(),
        timeout=timeout,
    )

    payload = r.json()
    rows = payload.get("data", [])
    total = int(payload.get("recordsTotal", len(rows)))

    stations = [parse_station_row(row) for row in rows]

    if own_session:
        session.close()

    return stations, total


def check_station_consistency(
    stations: list[dict[str, Any]],
) -> tuple[list[int], list[str], list[str]]:
    ids = [s["id"] for s in stations]
    codes = [s["code"] for s in stations]

    duplicate_ids = sorted(
        key for key, count in Counter(ids).items()
        if count > 1
    )

    duplicate_codes = sorted(
        key for key, count in Counter(codes).items()
        if count > 1
    )

    suspicious_coordinates = sorted(
        s["code"]
        for s in stations
        if s["latitude"] == 0.0 and s["longitude"] == 0.0
    )

    return duplicate_ids, duplicate_codes, suspicious_coordinates


def _comparable_station(station: dict[str, Any]) -> tuple[Any, ...]:
    fields = (
        "code",
        "city",
        "latitude",
        "longitude",
        "elevation_m",
        "status",
        "camera",
        "radio",
    )
    return tuple(station[field] for field in fields)


def update_stations(conn) -> StationUpdateReport:
    stations, remote_total = fetch_stations()

    duplicate_ids, duplicate_codes, suspicious_coordinates = (
        check_station_consistency(stations)
    )

    if remote_total != len(stations):
        raise RuntimeError(
            f"FRIPON reports {remote_total} stations but returned "
            f"{len(stations)} rows."
        )

    if duplicate_ids:
        raise RuntimeError(
            f"Duplicate FRIPON numeric station IDs found: {duplicate_ids}"
        )

    inserted = 0
    changed = 0
    unchanged = 0

    for station in stations:
        old = get_station(conn, station["id"])

        if old is None:
            inserted += 1
        else:
            old_dict = dict(old)
            if _comparable_station(old_dict) == _comparable_station(station):
                unchanged += 1
            else:
                changed += 1
                print(
                    f"CHANGED: id={station['id']} "
                    f"{old_dict['code']} / {old_dict['city']} "
                    f"-> {station['code']} / {station['city']}"
                )

        upsert_station(conn, station)

    conn.commit()

    return StationUpdateReport(
        remote_records=remote_total,
        parsed_records=len(stations),
        inserted=inserted,
        changed=changed,
        unchanged=unchanged,
        duplicate_ids=duplicate_ids,
        duplicate_codes=duplicate_codes,
        suspicious_coordinates=suspicious_coordinates,
    )
