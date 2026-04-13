import logging
import queue
import signal
import threading
from logging.handlers import RotatingFileHandler

from api import start_api_server
from config import DEVICES, LOG_BACKUPS, LOG_MAX_MB, LOG_PATH
from database import init_db, writer_thread
from device import device_worker


def setup_logging():
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    fh = RotatingFileHandler(
        LOG_PATH,
        maxBytes=LOG_MAX_MB * 1024 * 1024,
        backupCount=LOG_BACKUPS,
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)


def main():
    setup_logging()
    logger = logging.getLogger("main")
    logger.info("Biometric Event Server starting")

    init_db()

    shutdown_event = threading.Event()
    db_queue       = queue.Queue()

    def handle_shutdown(sig, frame):
        logger.info("Shutdown signal received (sig=%d)", sig)
        shutdown_event.set()

    signal.signal(signal.SIGINT,  handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # DB writer — not a daemon so it drains the queue before the process exits
    db_thread = threading.Thread(
        target=writer_thread,
        args=(db_queue, shutdown_event),
        name="db-writer",
        daemon=False,
    )
    db_thread.start()

    # One device thread per config entry
    device_threads = []
    for cfg in DEVICES:
        t = threading.Thread(
            target=device_worker,
            args=(cfg, db_queue, shutdown_event),
            name=f"device-{cfg['id']}",
            daemon=True,
        )
        t.start()
        device_threads.append(t)

    start_api_server(shutdown_event)

    logger.info("All threads started — server is running")

    for t in device_threads:
        t.join()

    logger.info("Device threads exited; waiting for DB writer to drain…")
    db_thread.join()
    logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
