import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from config import API_PORT
from database import query_device_status, query_events

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
            from_dt = qs.get("from", [None])[0]
            rows = query_events(limit=limit, user_id=user_id, from_date=from_dt)
            self._send_json(rows)

        elif parsed.path == "/status":
            self._send_json(query_device_status())

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
