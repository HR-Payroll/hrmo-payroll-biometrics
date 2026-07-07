import json
import logging
import threading
import urllib.request
import urllib.error

from config import (
    REMOTE_API_KEY,
    REMOTE_SYNC_BATCH,
    REMOTE_SYNC_ENABLED,
    REMOTE_SYNC_TIMEOUT,
    REMOTE_SYNC_URL,
)
from database import (
    get_sync_meta,
    query_device_status,
    query_unsynced_events,
    set_sync_meta,
)

logger = logging.getLogger(__name__)

_BACKOFF_BASE  = 30
_BACKOFF_MAX   = 300
_SYNC_CURSOR_KEY = "last_synced_id"


def _send_batch(events: list, device_status: list, last_id: int) -> bool:
    payload = json.dumps({
        "events": events,
        "device_status": device_status,
        "last_id": last_id,
    }).encode()

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {REMOTE_API_KEY}",
        "User-Agent": "BiometricSync/1.0",
    }

    req = urllib.request.Request(REMOTE_SYNC_URL, data=payload, headers=headers, method="POST")

    try:
        resp = urllib.request.urlopen(req, timeout=REMOTE_SYNC_TIMEOUT)
        body = json.loads(resp.read().decode())
        logger.info(
            "Sync batch sent (last_id=%d): inserted=%d skipped=%d",
            last_id, body.get("inserted", 0), body.get("skipped", 0),
        )
        return True
    except urllib.error.HTTPError as e:
        if e.code == 401:
            logger.critical("Remote sync auth failed (401) — disabling sync")
            return False
        logger.warning("Remote sync HTTP error %d: %s", e.code, e)
        return False
    except (urllib.error.URLError, OSError) as e:
        logger.warning("Remote sync network error: %s", e)
        return False


def sync_sender(shutdown_event: threading.Event,
                sync_notify: threading.Event | None = None):
    if not REMOTE_SYNC_ENABLED:
        logger.info("Remote sync is disabled")
        return

    logger.info("Sync sender started — url=%s batch=%d",
                REMOTE_SYNC_URL, REMOTE_SYNC_BATCH)

    backoff = _BACKOFF_BASE

    while not shutdown_event.is_set():
        raw_cursor = get_sync_meta(_SYNC_CURSOR_KEY)
        cursor = int(raw_cursor) if raw_cursor else 0

        events = query_unsynced_events(cursor, REMOTE_SYNC_BATCH)

        if not events:
            backoff = _BACKOFF_BASE
            if sync_notify is not None:
                sync_notify.wait()
                sync_notify.clear()
            else:
                shutdown_event.wait(timeout=10)
            continue

        last_id = events[-1]["id"]
        device_status = query_device_status()

        ok = _send_batch(events, device_status, last_id)
        if ok:
            set_sync_meta(_SYNC_CURSOR_KEY, str(last_id))
            backoff = _BACKOFF_BASE
        else:
            if shutdown_event.is_set():
                break
            logger.info("Sync backoff %ds…", backoff)
            shutdown_event.wait(timeout=backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)

    logger.info("Sync sender exiting")
