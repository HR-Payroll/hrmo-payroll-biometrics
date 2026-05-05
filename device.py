import logging
import queue
import threading

from zk import ZK
from zk.exception import ZKError, ZKErrorConnection, ZKNetworkError

from config import LIVE_TIMEOUT, RECONNECT_BASE_DELAY
from database import update_device_status

logger = logging.getLogger(__name__)

# Per-device sync coordination: pause signals the worker to disconnect;
# idle is set by the worker once it is disconnected and waiting.
_sync_state: dict = {}


def get_sync_state(device_id: str) -> dict:
    if device_id not in _sync_state:
        _sync_state[device_id] = {
            "pause": threading.Event(),
            "idle":  threading.Event(),
        }
    return _sync_state[device_id]


def device_worker(cfg: dict, db_queue: queue.Queue, shutdown_event: threading.Event):
    """
    Runs in its own thread. Connects to a ZKTeco device, captures live attendance
    events, and pushes them onto db_queue. Reconnects with exponential backoff on
    any failure until shutdown_event is set.
    """
    device_id = cfg["id"]
    ip        = cfg["ip"]
    port      = cfg["port"]
    password  = cfg["password"]
    timeout   = cfg["timeout"]

    backoff = RECONNECT_BASE_DELAY
    sync = get_sync_state(device_id)

    logger.info("Device worker started: %s (%s:%s)", device_id, ip, port)

    while not shutdown_event.is_set():
        # Pause for sync if requested — signal idle and wait until cleared
        if sync["pause"].is_set():
            logger.info("Device %s paused for sync", device_id)
            sync["idle"].set()
            while sync["pause"].is_set() and not shutdown_event.is_set():
                shutdown_event.wait(timeout=0.5)
            sync["idle"].clear()
            logger.info("Device %s resuming after sync", device_id)
            continue

        conn = None
        try:
            zk = ZK(ip, port=port, timeout=timeout, password=password, ommit_ping=False)
            conn = zk.connect()

            update_device_status(device_id, "connected")
            backoff = RECONNECT_BASE_DELAY  # reset on successful connect
            logger.info("Connected to %s (%s:%s)", device_id, ip, port)

            for att in conn.live_capture(new_timeout=LIVE_TIMEOUT):
                if shutdown_event.is_set() or sync["pause"].is_set():
                    conn.end_live_capture = True
                    break
                if att is None:
                    # timeout tick — no event, keep looping
                    continue

                event = {
                    "device_id": device_id,
                    "user_id":   str(att.user_id),
                    "timestamp": att.timestamp.isoformat() if att.timestamp else None,
                    "status":    att.status,
                    "punch":     att.punch,
                }
                db_queue.put(event)
                logger.debug("Event queued: %s", event)

        except (ZKNetworkError, ZKErrorConnection, ZKError) as e:
            logger.warning("ZK error on %s: %s", device_id, e)
            update_device_status(device_id, "error")
        except Exception as e:
            logger.warning("Unexpected error on %s: %s", device_id, e)
            update_device_status(device_id, "error")
        finally:
            if conn is not None:
                try:
                    conn.disconnect()
                except Exception:
                    pass
            if not shutdown_event.is_set():
                update_device_status(device_id, "disconnected")

        if shutdown_event.is_set():
            break

        # Fast path: if sync was requested, skip backoff and let the pause
        # check at the top of the loop handle the idle signalling
        if sync["pause"].is_set():
            continue

        logger.info("Reconnecting %s in %ds…", device_id, backoff)
        shutdown_event.wait(timeout=backoff)
        backoff = min(backoff * 2, 60)

    logger.info("Device worker exiting: %s", device_id)
