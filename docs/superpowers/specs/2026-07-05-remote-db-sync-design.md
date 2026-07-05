# Remote Database Sync — Biometric Events to Next.js/Postgres

## Overview

One-way sync from the local SQLite DB (Orange Pi) to a remote Postgres DB via
a Next.js API route. The biometric server pushes new events in batches to
`POST /api/biometric/sync` on the Next.js server. Dedup is handled by a
`UNIQUE INDEX` on `(device_id, user_id, timestamp)` in Postgres.

## Components

### Biometric Server — `syncer.py` (new)

- Runs in its own daemon thread (`sync-sender`).
- Reads unsynced events from SQLite using a high-water-mark cursor (`last_synced_id`).
- Batches events and sends via HTTPS POST to the Next.js endpoint.
- On 200 OK: advances cursor and writes `last_synced_id` + `last_synced_at` to `sync_meta` table.
- On non-200 / network failure: exponential backoff (30s → 60s → 120s → cap 300s).

### Biometric Server — schema addition (`database.py`)

New table `sync_meta`:
```sql
CREATE TABLE IF NOT EXISTS sync_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
```

### Biometric Server — `config.py` additions

| Constant | Purpose |
|----------|---------|
| `REMOTE_SYNC_ENABLED` | Toggle (default `False`) |
| `REMOTE_SYNC_URL` | Full URL to Next.js endpoint |
| `REMOTE_SYNC_INTERVAL` | Seconds between poll cycles (default 30) |
| `REMOTE_SYNC_BATCH` | Max events per POST (default 100) |
| `REMOTE_API_KEY` | Shared secret for Authorization header |
| `REMOTE_SYNC_TIMEOUT` | HTTP request timeout (default 10s) |

### Next.js — `POST /api/biometric/sync`

**Headers:** `Authorization: Bearer <REMOTE_API_KEY>`

**Request body (JSON):**
```json
{
  "events": [
    {
      "device_id": "device_1",
      "user_id": "12345",
      "timestamp": "2026-07-05T08:30:00",
      "status": 1,
      "punch": 1
    }
  ],
  "device_status": [
    {
      "device_id": "device_1",
      "last_seen": "2026-07-05T08:30:00",
      "status": "connected"
    }
  ],
  "last_id": 4500
}
```

**Response 200:**
```json
{
  "ok": true,
  "inserted": 95,
  "skipped": 5,
  "last_id": 4595
}
```

**Response 401:** if API key mismatch (biometric server logs critical, stops).

**Response 5xx:** biometric server retries same batch on next cycle.

### Postgres Schema (on Next.js side)

```sql
CREATE TABLE biometric_events (
    id         BIGSERIAL PRIMARY KEY,
    device_id  TEXT        NOT NULL,
    user_id    TEXT        NOT NULL,
    timestamp  TIMESTAMPTZ NOT NULL,
    status     INTEGER,
    punch      INTEGER,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE UNIQUE INDEX idx_biometric_events_unique
    ON biometric_events(device_id, user_id, timestamp);

CREATE INDEX idx_biometric_events_timestamp
    ON biometric_events(timestamp DESC);

CREATE INDEX idx_biometric_events_user_id
    ON biometric_events(user_id);

CREATE TABLE biometric_device_status (
    device_id  TEXT PRIMARY KEY,
    last_seen  TIMESTAMPTZ,
    status     TEXT
);
```

The Next.js handler should use `INSERT ... ON CONFLICT DO NOTHING` for events
and `INSERT ... ON CONFLICT (device_id) DO UPDATE` for device status.

## Files Changed

| File | Change |
|------|--------|
| `config.py` | Add sync-related constants |
| `database.py` | Add `sync_meta` table to schema, add `get_sync_meta()` / `set_sync_meta()` / `query_unsynced_events()` helpers |
| `syncer.py` | New — `sync_sender` thread function |
| `main.py` | Import and start sync thread if enabled |
