# fripon-db
A small proof-of-concept project for building a local research archive from the public FRIPON web database.

## Current scope

The code currently:

- queries FRIPON's public station DataTables endpoint;
- retrieves the complete current station catalogue;
- parses station ID, code, city, latitude, longitude, elevation, status,
    camera and radio fields;
- stores the catalogue in SQLite;
- can be run repeatedly to update the local catalogue;
- reports station records whose metadata changed;
- reports duplicate station IDs/codes;
- flags `(0, 0)` coordinates for manual inspection.

A station **code is not treated as unique**. During development FRIPON returned
two station records using the code `FRRA11`, so the numeric FRIPON station ID
is the SQLite primary key.

## Layout

```text
fripon_database_poc/
├── README.md
├── .gitignore
├── requirements.txt
├── db.py
├── stations.py
├── build_db.py
└── data/
    └── fripon.sqlite
```

*   `db.py` - SQLite schema and database helper functions.
*   `stations.py` - FRIPON station catalogue acquisition, parsing, consistency checks and update
    logic.
*   `build_db.py` -Command-line entry point that creates the database if needed and updates the
    station catalogue.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Build or update the station database

```bash
python build_db.py
```

Default database:

```text
data/fripon.sqlite
```

A custom path can be used:

```bash
python build_db.py --db /path/to/fripon.sqlite
```

Running the same command again updates existing records and reports changes.

Typical output:

```text
Station update report
---------------------
FRIPON records:        377
Parsed records:        377
Inserted:              377
Changed:               0
Unchanged:             0
SQLite station rows:   377
Duplicate IDs:         []
Duplicate codes:       ['FRRA11']
```

## Data source

```text
https://fireball.fripon.org/list_station.php
https://fireball.fripon.org/ajax/liste_station.ajax.php
```

The collector should remain conservative about request frequency and avoid
placing unnecessary load on FRIPON infrastructure.

## Next step

The next module will handle historical captures separately:

1. resolve capture metadata from `displaycapture.php?id=...`;
2. locate captures near a requested UTC time;
3. download and validate full-resolution JPEGs;
4. insert capture metadata into SQLite;
5. link captures to geographic station metadata where the relation is
    unambiguous.

Image analysis will remain separate from archive ingestion.
