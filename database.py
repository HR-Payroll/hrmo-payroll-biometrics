import logging
import queue
import sqlite3
import threading

from config import DB_PATH

logger = logging.getLogger(__name__)

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id  TEXT    NOT NULL,
    user_id    TEXT    NOT NULL,
    timestamp  DATETIME NOT NULL,
    status     INTEGER,
    punch      INTEGER,
    created_at DATETIME DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_user_id   ON events(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_unique ON events(device_id, user_id, timestamp);

CREATE TABLE IF NOT EXISTS device_status (
    device_id  TEXT PRIMARY KEY,
    last_seen  DATETIME,
    status     TEXT
);
"""


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()


def writer_thread(db_queue: queue.Queue, shutdown_event: threading.Event):
    """Single writer thread — drains db_queue and persists to SQLite."""
    conn = sqlite3.connect(DB_PATH)
    try:
        while not (shutdown_event.is_set() and db_queue.empty()):
            try:
                event = db_queue.get(timeout=1)
            except queue.Empty:
                continue

            try:
                conn.execute(
                    """
                    INSERT INTO events (device_id, user_id, timestamp, status, punch)
                    VALUES (:device_id, :user_id, :timestamp, :status, :punch)
                    """,
                    event,
                )
                conn.execute(
                    """
                    INSERT INTO device_status (device_id, last_seen, status)
                    VALUES (:device_id, :timestamp, 'connected')
                    ON CONFLICT(device_id) DO UPDATE SET
                        last_seen = excluded.last_seen,
                        status    = excluded.status
                    """,
                    event,
                )
                conn.commit()
                logger.debug(
                    "Event saved: device=%s user=%s ts=%s",
                    event["device_id"],
                    event["user_id"],
                    event["timestamp"],
                )
            except sqlite3.Error as e:
                logger.error("DB write error: %s — event dropped: %s", e, event)
            finally:
                db_queue.task_done()
    finally:
        conn.close()
        logger.info("DB writer thread exiting")


def update_device_status(device_id: str, status: str):
    """Called from device threads to update connection status."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """
            INSERT INTO device_status (device_id, last_seen, status)
            VALUES (?, datetime('now'), ?)
            ON CONFLICT(device_id) DO UPDATE SET
                last_seen = excluded.last_seen,
                status    = excluded.status
            """,
            (device_id, status),
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error("Failed to update device_status for %s: %s", device_id, e)


def query_events(limit=50, user_id=None, from_date=None, to_date=None):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    params = []
    clauses = []

    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    if from_date:
        clauses.append("timestamp >= ?")
        params.append(from_date)
    if to_date:
        clauses.append("timestamp <= ?")
        params.append(to_date)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    rows = conn.execute(
        f"SELECT * FROM events {where} ORDER BY timestamp DESC LIMIT ?", params
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def insert_attendance_bulk(records: list) -> tuple:
    """Inserts records with INSERT OR IGNORE (deduplicates by device_id+user_id+timestamp).
    Returns (inserted, skipped)."""
    conn = sqlite3.connect(DB_PATH)
    inserted = 0
    skipped = 0
    try:
        for r in records:
            cur = conn.execute(
                "INSERT OR IGNORE INTO events (device_id, user_id, timestamp, status, punch) "
                "VALUES (:device_id, :user_id, :timestamp, :status, :punch)",
                r,
            )
            if cur.rowcount:
                inserted += 1
            else:
                skipped += 1
        conn.commit()
    finally:
        conn.close()
    return inserted, skipped


def query_device_status():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM device_status").fetchall()
    conn.close()
    return [dict(r) for r in rows]
