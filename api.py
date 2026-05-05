import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from config import API_PORT, DEVICES
from database import insert_attendance_bulk, query_device_status, query_events
from device import get_sync_state

logger = logging.getLogger(__name__)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Route access logs through Python logger instead of stderr
        logger.debug("API %s - %s", self.address_string(), format % args)

    def _send_json(self, data, status=200):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        qs     = parse_qs(parsed.query)

        if parsed.path == "/events":
            limit   = int(qs.get("limit", ["50"])[0])
            user_id = qs.get("user_id", [None])[0]
            from_dt = qs.get("dateFrom", qs.get("from", [None]))[0]
            to_dt   = qs.get("dateTo", [None])[0]
            rows = query_events(limit=limit, user_id=user_id, from_date=from_dt, to_date=to_dt)
            self._send_json(rows)

        elif parsed.path == "/devices":
            status_map = {d["device_id"]: d for d in query_device_status()}
            result = []
            for dev in DEVICES:
                s = status_map.get(dev["id"], {})
                result.append({
                    "id":        dev["id"],
                    "ip":        dev["ip"],
                    "port":      dev["port"],
                    "status":    s.get("status", "unknown"),
                    "last_seen": s.get("last_seen"),
                })
            self._send_json(result)

        elif parsed.path == "/status":
            self._send_json(query_device_status())

        elif parsed.path == "/sync":
            from zk import ZK
            from zk.exception import ZKError, ZKErrorConnection, ZKNetworkError

            device_id = qs.get("device_id", [None])[0]
            from_dt   = qs.get("dateFrom", [None])[0]
            to_dt     = qs.get("dateTo",   [None])[0]

            if not device_id:
                self._send_json({"error": "device_id is required"}, status=400)
                return

            cfg = next((d for d in DEVICES if d["id"] == device_id), None)
            if cfg is None:
                self._send_json({"error": f"unknown device_id: {device_id}"}, status=404)
                return

            sync = get_sync_state(device_id)
            sync["pause"].set()
            idle_reached = sync["idle"].wait(timeout=20)
            if not idle_reached:
                sync["pause"].clear()
                self._send_json({"error": "device did not release connection in time"}, status=503)
                return

            try:
                zk   = ZK(cfg["ip"], port=cfg["port"], timeout=cfg["timeout"],
                          password=cfg["password"], ommit_ping=False)
                conn = zk.connect()
                try:
                    attendances = conn.get_attendance()
                finally:
                    conn.disconnect()

                records = []
                for att in attendances:
                    ts = att.timestamp.isoformat() if att.timestamp else None
                    if ts is None:
                        continue
                    if from_dt and ts < from_dt:
                        continue
                    if to_dt and ts > to_dt:
                        continue
                    records.append({
                        "device_id": device_id,
                        "user_id":   str(att.user_id),
                        "timestamp": ts,
                        "status":    att.status,
                        "punch":     att.punch,
                    })

                inserted, skipped = insert_attendance_bulk(records)
                self._send_json({
                    "device_id": device_id,
                    "fetched":   len(attendances),
                    "matched":   len(records),
                    "synced":    inserted,
                    "skipped":   skipped,
                })

            except (ZKNetworkError, ZKErrorConnection) as e:
                self._send_json({"error": f"device connection failed: {e}"}, status=503)
            except ZKError as e:
                self._send_json({"error": f"device error: {e}"}, status=500)
            finally:
                sync["pause"].clear()
                sync["idle"].clear()

        else:
            self._send_json({"error": "not found"}, status=404)


def start_api_server(shutdown_event: threading.Event):
    """Starts the HTTP API server in a daemon thread."""
    server = HTTPServer(("127.0.0.1", API_PORT), _Handler)

    def _serve():
        logger.info("API server listening on port %d", API_PORT)
        while not shutdown_event.is_set():
            server.handle_request()
        server.server_close()
        logger.info("API server stopped")

    t = threading.Thread(target=_serve, name="api-server", daemon=True)
    t.start()
    return t
