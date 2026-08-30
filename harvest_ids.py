from __future__ import annotations

import argparse
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from captures import get_capture
from db import (
    connect,
    get_harvest_states,
    initialize_database,
    mark_harvest_status,
    resolve_station_id,
    upsert_capture,
)
from download import download_capture_image
from http_utils import make_session


DEFAULT_DB = Path("data/fripon.sqlite")
DEFAULT_IMAGES = Path("data/images")

_thread_local = threading.local()


class RateLimiter:
    """Global start-rate limiter shared by all worker threads."""

    def __init__(self, min_interval: float):
        self.min_interval = max(0.0, min_interval)
        self.lock = threading.Lock()
        self.next_allowed = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return

        with self.lock:
            now = time.monotonic()
            delay = max(0.0, self.next_allowed - now)
            self.next_allowed = max(now, self.next_allowed) + self.min_interval

        if delay:
            time.sleep(delay)


def worker_session():
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = make_session(referer="https://fireball.fripon.org/")
        _thread_local.session = session
    return session


def metadata_record(capture: dict, station_id: int | None) -> dict:
    """Capture row suitable for SQLite before/without a successful download."""
    row = dict(capture)
    row.update({
        "station_id": station_id,
        "local_path": None,
        "file_size_bytes": None,
        "sha256": None,
        "width": None,
        "height": None,
        "download_status": "metadata_only",
    })
    return row


def process_id(
    capture_id: int,
    images_root: Path,
    limiter: RateLimiter,
) -> dict:
    session = worker_session()

    try:
        limiter.wait()
        capture = get_capture(capture_id, session=session)

        if capture is None:
            return {"id": capture_id, "status": "invalid"}

        dt = datetime.strptime(capture["timestamp_utc"], "%Y-%m-%d %H:%M:%S")
        output_dir = (
            images_root
            / capture["station_code"]
            / dt.strftime("%Y")
            / dt.strftime("%m")
        )

        try:
            limiter.wait()
            downloaded = download_capture_image(
                capture,
                output_dir=output_dir,
                session=session,
            )
            return {
                "id": capture_id,
                "status": "downloaded",
                "capture": downloaded,
            }

        except Exception as exc:
            return {
                "id": capture_id,
                "status": "failed",
                "capture": capture,
                "error": f"image download: {exc}",
            }

    except Exception as exc:
        return {
            "id": capture_id,
            "status": "failed",
            "error": f"metadata request: {exc}",
        }


def should_skip(state, retry_invalid: bool) -> bool:
    if state is None:
        return False

    if state["status"] == "invalid" and not retry_invalid:
        return True

    if state["status"] == "downloaded":
        path = state["local_path"]
        if path and Path(path).is_file():
            return True

    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Harvest an inclusive FRIPON capture-ID range into SQLite and local JPEG storage."
    )
    parser.add_argument("start_id", type=int)
    parser.add_argument("end_id", type=int)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--images", type=Path, default=DEFAULT_IMAGES)
    parser.add_argument(
        "--workers", type=int, default=2,
        help="Maximum concurrent workers (default: 2).",
    )
    parser.add_argument(
        "--request-interval", type=float, default=0.25,
        help="Minimum seconds between request starts across all workers (default: 0.25).",
    )
    parser.add_argument(
        "--batch-size", type=int, default=500,
        help="IDs considered per local batch (default: 500).",
    )
    parser.add_argument(
        "--retry-invalid", action="store_true",
        help="Probe IDs previously confirmed invalid.",
    )
    args = parser.parse_args()

    if args.start_id < 1 or args.end_id < args.start_id:
        parser.error("Require 1 <= start_id <= end_id")
    if args.workers < 1:
        parser.error("--workers must be >= 1")
    if args.batch_size < 1:
        parser.error("--batch-size must be >= 1")

    conn = connect(args.db)
    initialize_database(conn)

    limiter = RateLimiter(args.request_interval)

    counters = {
        "range": args.end_id - args.start_id + 1,
        "submitted": 0,
        "skipped": 0,
        "downloaded": 0,
        "already_present": 0,
        "invalid": 0,
        "failed": 0,
        "unresolved_station_ids": 0,
    }

    started = time.monotonic()
    writes_since_commit = 0

    print(f"ID range: {args.start_id}..{args.end_id} (inclusive)")
    print(f"Workers: {args.workers}")
    print(f"Minimum request interval: {args.request_interval:.3f} s")
    print(f"Database: {args.db.resolve()}")
    print(f"Images: {args.images.resolve()}")
    print()

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            batch_start = args.start_id

            while batch_start <= args.end_id:
                batch_end = min(batch_start + args.batch_size - 1, args.end_id)
                states = get_harvest_states(conn, batch_start, batch_end)

                ids_to_process = []
                for capture_id in range(batch_start, batch_end + 1):
                    state = states.get(capture_id)
                    if should_skip(state, args.retry_invalid):
                        counters["skipped"] += 1
                    else:
                        ids_to_process.append(capture_id)

                counters["submitted"] += len(ids_to_process)

                futures = {
                    executor.submit(
                        process_id,
                        capture_id,
                        args.images,
                        limiter,
                    ): capture_id
                    for capture_id in ids_to_process
                }

                for future in as_completed(futures):
                    result = future.result()
                    capture_id = result["id"]
                    status = result["status"]

                    if status == "invalid":
                        mark_harvest_status(conn, capture_id, "invalid")
                        counters["invalid"] += 1

                    elif status == "downloaded":
                        capture = result["capture"]
                        station_id = resolve_station_id(
                            conn,
                            capture["station_code"],
                            capture.get("city"),
                        )
                        if station_id is None:
                            counters["unresolved_station_ids"] += 1
                        capture["station_id"] = station_id
                        upsert_capture(conn, capture)
                        mark_harvest_status(conn, capture_id, "downloaded")

                        if capture["download_status"] == "downloaded":
                            counters["downloaded"] += 1
                        else:
                            counters["already_present"] += 1

                    else:
                        capture = result.get("capture")
                        if capture is not None:
                            station_id = resolve_station_id(
                                conn,
                                capture["station_code"],
                                capture.get("city"),
                            )
                            if station_id is None:
                                counters["unresolved_station_ids"] += 1
                            upsert_capture(conn, metadata_record(capture, station_id))

                        mark_harvest_status(
                            conn,
                            capture_id,
                            "failed",
                            result.get("error"),
                        )
                        counters["failed"] += 1

                    writes_since_commit += 1
                    if writes_since_commit >= 25:
                        conn.commit()
                        writes_since_commit = 0

                conn.commit()

                done = batch_end - args.start_id + 1
                elapsed = time.monotonic() - started
                rate = done / elapsed if elapsed else 0.0
                print(
                    f"Through ID {batch_end}: "
                    f"downloaded={counters['downloaded']}, "
                    f"invalid={counters['invalid']}, "
                    f"failed={counters['failed']}, "
                    f"skipped={counters['skipped']} "
                    f"({rate:.2f} IDs/s scanned)"
                )

                batch_start = batch_end + 1

    except KeyboardInterrupt:
        print("\nInterrupted. Committing completed work...")
        conn.commit()

    finally:
        conn.commit()
        conn.close()

    elapsed = time.monotonic() - started
    print()
    print("Harvest summary")
    print("---------------")
    print(f"Requested IDs:          {counters['range']}")
    print(f"Submitted this run:     {counters['submitted']}")
    print(f"Skipped as complete:    {counters['skipped']}")
    print(f"Downloaded:             {counters['downloaded']}")
    print(f"Already present:        {counters['already_present']}")
    print(f"Invalid IDs:            {counters['invalid']}")
    print(f"Failed:                 {counters['failed']}")
    print(f"Unresolved station IDs: {counters['unresolved_station_ids']}")
    print(f"Elapsed:                {elapsed / 60:.1f} min")


if __name__ == "__main__":
    main()
