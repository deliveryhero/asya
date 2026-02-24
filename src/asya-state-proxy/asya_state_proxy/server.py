"""HTTP server on Unix socket that routes requests to StateProxyConnector methods."""

import json
import logging
import os
import signal
import socket
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from asya_state_proxy.interface import StateProxyConnector


logger = logging.getLogger("asya.state-proxy")

_ERROR_MAP = {
    FileNotFoundError: (404, "key_not_found"),
    FileExistsError: (409, "conflict"),
    ValueError: (400, "bad_request"),
    PermissionError: (403, "permission_denied"),
    ConnectionError: (503, "unavailable"),
    TimeoutError: (504, "timeout"),
}


def _json_error(handler: BaseHTTPRequestHandler, status: int, error: str, message: str | None = None) -> None:
    body: dict = {"error": error}
    if message:
        body["message"] = message
    encoded = json.dumps(body).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def _json_ok(handler: BaseHTTPRequestHandler, data: dict) -> None:
    encoded = json.dumps(data).encode()
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def _handle_connector_error(handler: BaseHTTPRequestHandler, exc: Exception) -> None:
    for exc_type, (status, error_code) in _ERROR_MAP.items():
        if isinstance(exc, exc_type):
            _json_error(handler, status, error_code, str(exc))
            return
    logger.exception("Unhandled connector error")
    _json_error(handler, 500, "internal_error", str(exc))


def _make_handler(connector: StateProxyConnector) -> type:
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            logger.debug(fmt, *args)

        def _key_from_path(self) -> str:
            # Path is /keys/{key} — strip leading /keys/
            path = self.path
            if "?" in path:
                path = path.split("?", 1)[0]
            # Remove /keys/ prefix
            return path[len("/keys/") :]

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path

            if path == "/healthz":
                _json_ok(self, {"status": "ready"})
                return

            if path.startswith("/keys/") and len(path) > len("/keys/"):
                key = path[len("/keys/") :]
                try:
                    stream = connector.read(key)
                    data = stream.read()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except Exception as exc:
                    _handle_connector_error(self, exc)
                return

            if path == "/keys/" or path == "/keys":
                qs = urllib.parse.parse_qs(parsed.query)
                prefix = qs.get("prefix", [""])[0]
                delimiter = qs.get("delimiter", ["/"])[0]
                try:
                    result = connector.list(prefix, delimiter)
                    _json_ok(self, {"keys": result.keys, "prefixes": result.prefixes})
                except Exception as exc:
                    _handle_connector_error(self, exc)
                return

            _json_error(self, 404, "not_found")

        def do_PUT(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            if not path.startswith("/keys/") or len(path) <= len("/keys/"):
                _json_error(self, 404, "not_found")
                return

            key = path[len("/keys/") :]

            # Handle both Content-Length and chunked transfer encoding
            transfer_encoding = self.headers.get("Transfer-Encoding", "")
            content_length = self.headers.get("Content-Length")

            if "chunked" in transfer_encoding.lower():
                # Read chunked body
                chunks = []
                while True:
                    line = self.rfile.readline().strip()
                    chunk_size = int(line, 16)
                    if chunk_size == 0:
                        self.rfile.readline()  # trailing CRLF
                        break
                    chunk_data = self.rfile.read(chunk_size)
                    self.rfile.readline()  # trailing CRLF after chunk
                    chunks.append(chunk_data)
                body = b"".join(chunks)
            elif content_length:
                body = self.rfile.read(int(content_length))
            else:
                body = b""

            import io

            try:
                connector.write(key, io.BytesIO(body), size=len(body))
                self.send_response(204)
                self.end_headers()
            except Exception as exc:
                _handle_connector_error(self, exc)

        def do_HEAD(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            if not path.startswith("/keys/") or len(path) <= len("/keys/"):
                _json_error(self, 404, "not_found")
                return

            key = path[len("/keys/") :]
            try:
                meta = connector.stat(key)
                if meta is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(204)
                self.send_header("Content-Length", str(meta.size))
                self.send_header("X-Is-File", "true" if meta.is_file else "false")
                self.end_headers()
            except Exception as exc:
                _handle_connector_error(self, exc)

        def do_DELETE(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            if not path.startswith("/keys/") or len(path) <= len("/keys/"):
                _json_error(self, 404, "not_found")
                return

            key = path[len("/keys/") :]
            try:
                connector.delete(key)
                self.send_response(204)
                self.end_headers()
            except Exception as exc:
                _handle_connector_error(self, exc)

    return _Handler


class ConnectorServer(HTTPServer):
    address_family = socket.AF_UNIX

    def __init__(self, socket_path: str, connector: StateProxyConnector) -> None:
        self._socket_path = socket_path
        handler_class = _make_handler(connector)
        # Remove stale socket file if present
        if os.path.exists(socket_path):
            os.unlink(socket_path)
        super().__init__(socket_path, handler_class)  # type: ignore[arg-type]
        logger.info("ConnectorServer listening on %s", socket_path)

    def server_close(self) -> None:
        super().server_close()
        if os.path.exists(self._socket_path):
            os.unlink(self._socket_path)
            logger.info("Removed socket %s", self._socket_path)


def run_connector(connector: StateProxyConnector) -> None:
    """Entry point: reads CONNECTOR_SOCKET env var, runs server with graceful shutdown."""
    socket_path = os.environ.get("CONNECTOR_SOCKET")
    if not socket_path:
        raise RuntimeError("CONNECTOR_SOCKET environment variable is required")

    server = ConnectorServer(socket_path, connector)

    def _shutdown(signum: int, frame: object) -> None:
        logger.info("Received signal %d, shutting down", signum)
        server.shutdown()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("Starting connector server")
    try:
        server.serve_forever()
    finally:
        server.server_close()
        logger.info("Connector server stopped")
