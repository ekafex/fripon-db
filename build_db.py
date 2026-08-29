from __future__ import annotations

import argparse
from pathlib import Path

from db import connect, initialize_database, station_count
from stations import update_stations


DEFAULT_DB = Path("data/fripon.sqlite")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create/update the local FRIPON PoC SQLite database."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"SQLite database path (default: {DEFAULT_DB})",
    )
    args = parser.parse_args()

    conn = connect(args.db)

    try:
        initialize_database(conn)

        print(f"Database: {args.db.resolve()}")
        print("Updating FRIPON station catalogue...")

        report = update_stations(conn)

        print()
        print("Station update report")
        print("---------------------")
        print(f"FRIPON records:        {report.remote_records}")
        print(f"Parsed records:        {report.parsed_records}")
        print(f"Inserted:              {report.inserted}")
        print(f"Changed:               {report.changed}")
        print(f"Unchanged:             {report.unchanged}")
        print(f"SQLite station rows:   {station_count(conn)}")
        print(f"Duplicate IDs:         {report.duplicate_ids}")
        print(f"Duplicate codes:       {report.duplicate_codes}")
        print(
            "Suspicious coordinates: "
            f"{report.suspicious_coordinates}"
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
