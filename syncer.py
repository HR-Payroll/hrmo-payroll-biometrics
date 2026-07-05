import json
import logging
import threading
import urllib.request
import urllib.error
import ssl

from config import (
    REMOTE_API_KEY,
    REMOTE_SYNC_BATCH,
    REMOTE_SYNC_ENABLED,
    REMOTE_SYNC_INTERVAL,
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
    }

    req = urllib.request.Request(REMOTE_SYNC_URL, data=payload, headers=headers, method="POST")

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        resp = urllib.request.urlopen(req, timeout=REMOTE_SYNC_TIMEOUT, context=ctx)
        if resp.status == 200:
            body = json.loads(resp.read().decode())
            logger.info(
                "Sync batch sent (last_id=%d): inserted=%d skipped=%d",
                last_id, body.get("inserted", 0), body.get("skipped", 0),
            )
            return True
        elif resp.status == 401:
            logger.critical("Remote sync auth failed (401) — disabling sync")
            return False
        else:
            logger.warning("Remote sync returned %d — will retry", resp.status)
            return False
    except urllib.error.HTTPError as e:
        if e.code == 401:
            logger.critical("Remote sync auth failed (401) — disabling sync")
            return False
        logger.warning("Remote sync HTTP error %d: %s", e.code, e)
        return False
    except (urllib.error.URLError, OSError) as e:
        logger.warning("Remote sync network error: %s", e)
        return False


def sync_sender(shutdown_event: threading.Event):
    if not REMOTE_SYNC_ENABLED:
        logger.info("Remote sync is disabled")
        return

    logger.info("Sync sender started — url=%s interval=%ds batch=%d",
                REMOTE_SYNC_URL, REMOTE_SYNC_INTERVAL, REMOTE_SYNC_BATCH)

    backoff = _BACKOFF_BASE

    while not shutdown_event.is_set():
        raw_cursor = get_sync_meta(_SYNC_CURSOR_KEY)
        cursor = int(raw_cursor) if raw_cursor else 0

        events = query_unsynced_events(cursor, REMOTE_SYNC_BATCH)
        if not events:
            shutdown_event.wait(timeout=REMOTE_SYNC_INTERVAL)
            backoff = _BACKOFF_BASE
            continue

        last_id = events[-1]["id"]
        device_status = query_device_status()

        ok = _send_batch(events, device_status, last_id)
        if ok:
            set_sync_meta(_SYNC_CURSOR_KEY, str(last_id))
            backoff = _BACKOFF_BASE
        elif not ok:
            if shutdown_event.is_set():
                break
            logger.info("Sync backoff %ds…", backoff)
            shutdown_event.wait(timeout=backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)
            continue

        shutdown_event.wait(timeout=REMOTE_SYNC_INTERVAL)

    logger.info("Sync sender exiting")
