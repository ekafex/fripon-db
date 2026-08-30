from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from http_utils import get, make_session as make_http_session


BASE_URL = "https://fireball.fripon.org"
CAPTURE_PAGE = f"{BASE_URL}/displaycapture.php"
CAPTURE_LIST_PAGE = f"{BASE_URL}/list_capture.php"
CAPTURE_ENDPOINT = f"{BASE_URL}/ajax/liste_capture.ajax.php"
CHRONOLOGICAL_LOW_ID = 16_000_000


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    return session


def get_capture(capture_id: int, session: requests.Session | None = None, timeout: int = 30) -> dict | None:
    own_session = session is None
    if session is None:
        session = make_session()

    r = session.get(CAPTURE_PAGE, params={"id": capture_id}, timeout=timeout)
    r.raise_for_status()
    r.encoding = "utf-8"

    soup = BeautifulSoup(r.text, "html.parser")
    img = next((x for x in soup.find_all("img", src=True) if "/fripon_stations/" in x["src"]), None)

    if img is None:
        if own_session:
            session.close()
        return None

    src = img["src"]
    match = re.search(
        r"/fripon_stations/([A-Z0-9]+)/(\d{6})/\1_(\d{8}T\d{6})_UT-0\.jpg$",
        src,
    )
    if not match:
        if own_session:
            session.close()
        return None

    station_code = match.group(1)
    raw_time = match.group(3)
    timestamp = datetime.strptime(raw_time, "%Y%m%dT%H%M%S").strftime("%Y-%m-%d %H:%M:%S")

    alt = img.get("alt", "")
    city_match = re.search(r"detection\s+(.+?)\s+\(", alt, flags=re.IGNORECASE)
    city = city_match.group(1).strip() if city_match else None

    result = {
        "id": int(capture_id),
        "station_code": station_code,
        "city": city,
        "timestamp_utc": timestamp,
        "image_url": urljoin(BASE_URL, src),
    }

    if own_session:
        session.close()
    return result


def _capture_datatable_params(start: int = 0, length: int = 1) -> dict[str, str]:
    p = {
        "draw": "1",
        "order[0][column]": "3",
        "order[0][dir]": "desc",
        "start": str(start),
        "length": str(length),
        "search[value]": "",
        "search[regex]": "false",
    }
    for i in range(5):
        p[f"columns[{i}][data]"] = str(i)
        p[f"columns[{i}][name]"] = ""
        p[f"columns[{i}][searchable]"] = "true"
        p[f"columns[{i}][orderable]"] = "false" if i == 4 else "true"
        p[f"columns[{i}][search][value]"] = ""
        p[f"columns[{i}][search][regex]"] = "false"
    return p


def latest_capture_id(session: requests.Session | None = None, timeout: int = 30) -> int:
    own_session = session is None
    if session is None:
        session = make_session()

    session.get(CAPTURE_LIST_PAGE, timeout=timeout).raise_for_status()
    r = session.get(
        CAPTURE_ENDPOINT,
        params=_capture_datatable_params(0, 1),
        headers={"Referer": CAPTURE_LIST_PAGE},
        timeout=timeout,
    )
    r.raise_for_status()
    rows = r.json().get("data", [])
    if not rows:
        raise RuntimeError("FRIPON current capture catalogue returned no rows.")

    capture_id = int(rows[0][0])
    if own_session:
        session.close()
    return capture_id


def _valid_capture_near_id(capture_id: int, low: int, high: int, session: requests.Session, search_radius: int = 100):
    result = get_capture(capture_id, session=session)
    if result is not None:
        return capture_id, result

    for offset in range(1, search_radius + 1):
        left = capture_id - offset
        right = capture_id + offset
        if left >= low:
            result = get_capture(left, session=session)
            if result is not None:
                return left, result
        if right <= high:
            result = get_capture(right, session=session)
            if result is not None:
                return right, result
    return None, None


def find_capture_near_date(target_date: str, low_id: int = CHRONOLOGICAL_LOW_ID, high_id: int | None = None, request_delay: float = 0.02) -> dict:
    target = datetime.strptime(target_date, "%Y-%m-%d %H:%M:%S")
    session = make_session()
    try:
        if high_id is None:
            high_id = latest_capture_id(session=session)

        low, high = low_id, high_id
        best_capture = None
        best_difference = None

        while low <= high:
            mid = (low + high) // 2
            valid_id, capture = _valid_capture_near_id(mid, low, high, session)
            if capture is None or valid_id is None:
                raise RuntimeError(f"Could not find a valid capture near ID {mid}.")

            capture_time = datetime.strptime(capture["timestamp_utc"], "%Y-%m-%d %H:%M:%S")
            difference = abs((capture_time - target).total_seconds())
            if best_difference is None or difference < best_difference:
                best_difference = difference
                best_capture = capture

            if capture_time < target:
                low = valid_id + 1
            elif capture_time > target:
                high = valid_id - 1
            else:
                break
            time.sleep(request_delay)

        if best_capture is None:
            raise RuntimeError("No capture found near requested date.")
        return best_capture
    finally:
        session.close()


def captures_near_time(anchor_id: int, target_time: str, id_radius: int = 600, window_seconds: int = 90, request_delay: float = 0.02) -> list[dict]:
    target = datetime.strptime(target_time, "%Y-%m-%d %H:%M:%S")
    tmin = target - timedelta(seconds=window_seconds)
    tmax = target + timedelta(seconds=window_seconds)
    session = make_session()
    matches = []

    try:
        for capture_id in range(max(1, anchor_id - id_radius), anchor_id + id_radius + 1):
            capture = get_capture(capture_id, session=session)
            if capture is None:
                continue
            capture_time = datetime.strptime(capture["timestamp_utc"], "%Y-%m-%d %H:%M:%S")
            if tmin <= capture_time <= tmax:
                matches.append(capture)
            time.sleep(request_delay)
    finally:
        session.close()

    by_id = {capture["id"]: capture for capture in matches}
    return sorted(by_id.values(), key=lambda c: (c["timestamp_utc"], c["station_code"], c["id"]))
