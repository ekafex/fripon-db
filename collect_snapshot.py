from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import requests

from http_utils import make_session
from captures import find_capture_near_date, captures_near_time
from db import connect, initialize_database, resolve_station_id, upsert_capture
from download import download_capture_image


DEFAULT_DB = Path("data/fripon.sqlite")
DEFAULT_IMAGES = Path("data/images")


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect a historical FRIPON network snapshot.")
    parser.add_argument("timestamp", help='UTC timestamp, e.g. "2023-04-27 05:30:00"')
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--images", type=Path, default=DEFAULT_IMAGES)
    parser.add_argument("--window", type=int, default=90)
    parser.add_argument("--id-radius", type=int, default=600)
    args = parser.parse_args()

    target = datetime.strptime(args.timestamp, "%Y-%m-%d %H:%M:%S")
    output_dir = args.images / target.strftime("%Y%m%d_%H%M%S")

    print(f"Target UTC: {args.timestamp}")
    print("Finding nearby capture ID...")
    anchor = find_capture_near_date(args.timestamp)
    print(f"Anchor: id={anchor['id']} {anchor['station_code']} {anchor['timestamp_utc']}")

    captures = captures_near_time(
        anchor_id=anchor["id"],
        target_time=args.timestamp,
        id_radius=args.id_radius,
        window_seconds=args.window,
    )

    print(f"Captures found: {len(captures)}")
    print(f"Unique stations: {len({c['station_code'] for c in captures})}")

    conn = connect(args.db)
    initialize_database(conn)

    download_session = make_session(
        referer="https://fireball.fripon.org/"
    )

    downloaded = reused = failed = unresolved = 0

    try:
        for i, capture in enumerate(captures, 1):
            try:
                station_id = resolve_station_id(conn, capture["station_code"], capture.get("city"))
                if station_id is None:
                    unresolved += 1

                item = download_capture_image(capture, output_dir, session=download_session)
                item["station_id"] = station_id
                upsert_capture(conn, item)
                conn.commit()

                if item["download_status"] == "downloaded":
                    downloaded += 1
                else:
                    reused += 1

                print(f"[{i:03d}/{len(captures):03d}] {capture['station_code']} {capture['timestamp_utc']} {item['download_status']}")
            except Exception as exc:
                failed += 1
                print(f"[{i:03d}/{len(captures):03d}] {capture['station_code']} FAILED: {exc}")
    finally:
        download_session.close()
        conn.close()

    print("\nSnapshot complete")
    print("-----------------")
    print(f"Captures:               {len(captures)}")
    print(f"Downloaded:             {downloaded}")
    print(f"Already present:        {reused}")
    print(f"Failed:                 {failed}")
    print(f"Unresolved station IDs: {unresolved}")
    print(f"Images:                 {output_dir.resolve()}")
    print(f"Database:               {args.db.resolve()}")


if __name__ == "__main__":
    main()
