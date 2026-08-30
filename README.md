# fripon-db
Proof-of-concept for building a local research archive from the public FRIPON web database.

The code separates station ingestion, historical capture discovery, JPEG downloading/validation, and SQLite persistence. Image analysis is intentionally outside this layer.

## Main commands

Build/update the station catalogue:

```bash
python build_db.py
```

Collect a historical network snapshot:

```bash
python collect_snapshot.py "2023-04-27 05:30:00"
```

By default the snapshot collector searches within ±90 s and scans ±600 capture IDs around the binary-search anchor. Images are stored in:

```text
data/images/YYYYMMDD_HHMMSS/
```

The `captures` table stores capture ID, station code, resolved numeric station ID when unambiguous, city, UTC timestamp, full-resolution image URL, local path, file size, SHA-256, dimensions, and download status.

## Important assumption

Capture IDs are not globally chronological over the complete FRIPON archive. Empirical tests showed that IDs become approximately chronological around ID 16,000,000 (about September 2019 onward). The binary-search helper targets that region for efficient historical sampling.

This assumption is only for efficient lookup. A future full archive mirror can ingest IDs independently and sort locally by timestamp.

## Request policy

**Keep request rates conservative. FRIPON is a scientific public service rather than a bulk archive API.**

## Network resilience

All HTTP access uses the shared http.py session with automatic retry and exponential backoff. Transient connection/DNS problems and HTTP 429/500/502/503/504 responses are retried automatically.

Persistent failures still raise an exception so they remain visible rather than being silently ignored.

