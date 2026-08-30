# FRIPON Local Database / Archive PoC

A small, robust proof-of-concept for building a **local mirror of the public
FRIPON capture archive**.

The primary ingestion key is the FRIPON numeric capture ID. The mirror does
not depend on capture IDs being chronological: station and UTC metadata are
extracted from each valid capture page and stored locally.

## Project layout

```text
fripon_database_poc_v4/
├── README.md
├── .gitignore
├── requirements.txt
├── db.py
├── http_utils.py
├── stations.py
├── captures.py
├── download.py
├── build_db.py
├── harvest_ids.py
└── collect_snapshot.py
```

`collect_snapshot.py` remains useful for targeted historical tests, but
`harvest_ids.py` is the main archive-building tool.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 1. Build/update station metadata

```bash
python build_db.py
```

This creates/updates the `stations` table in:

```text
data/fripon.sqlite
```

FRIPON's numeric station ID is the primary key. Station code is deliberately
not unique because the public catalogue currently contains a duplicated code.

## 2. Harvest a capture-ID range

Example:

```bash
python harvest_ids.py 42080000 42080500
```

The range is inclusive.

For every ID, the harvester:

1. skips it if it is already safely mirrored;
2. requests `displaycapture.php?id=...`;
3. records IDs that do not correspond to a valid capture;
4. extracts station, city, UTC timestamp and full-resolution JPEG URL;
5. downloads and validates the JPEG;
6. calculates file size, dimensions and SHA-256;
7. inserts/upserts the metadata in SQLite;
8. records harvest status and failures for reliable resumption.

Images are organized independently of numeric capture ID:

```text
data/images/
└── FRPL01/
    └── 2019/
        └── 02/
            └── FRPL01_20190227T144323_UT-0.jpg
```

The SQLite database can later sort/query by timestamp, station or geography.

## Resumability and idempotency

Rerunning the same command is safe:

```bash
python harvest_ids.py 42080000 42080500
```

- valid images already present locally are skipped;
- IDs already confirmed invalid are skipped;
- failed IDs are retried;
- a `downloaded` database record whose file is missing is processed again.

This makes interruption by power loss, network loss or Ctrl-C non-destructive.

## Polite request rate

Defaults are deliberately conservative:

```text
workers = 2
minimum request-start interval = 0.25 s
```

Change them only after observing FRIPON/server/network behaviour:

```bash
python harvest_ids.py 42080000 42080500 \
    --workers 3 \
    --request-interval 0.20
```

Retries with exponential backoff are handled centrally by `http_utils.py` for
transient connection/DNS errors and HTTP 429/500/502/503/504 responses.

## Database tables

### `stations`

Current FRIPON station metadata.

### `captures`

Metadata and local-file information for valid captures.

### `harvest_status`

One row per attempted capture ID:

- `downloaded`
- `invalid`
- `failed`

It also records attempt count and the last error. This is what makes arbitrary
ID ranges resumable without repeatedly probing known gaps.

## Targeted snapshot utility

The earlier experimental time-search utility remains available:

```bash
python collect_snapshot.py "2023-04-27 05:30:00"
```

It is useful for validation and targeted science, but is not required for a
complete archive mirror.

## Important operational note

FRIPON is a scientific public service, not a bulk-storage API. Large mirroring
jobs should be divided into reasonable ID ranges and run conservatively. The
project therefore favors reliability, resumption and low request pressure over
maximum download speed.
