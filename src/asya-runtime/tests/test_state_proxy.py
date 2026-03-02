#!/usr/bin/env python3
"""Unit tests for the state proxy interception layer in asya_runtime.py.

Tests cover:
- _parse_state_proxy_mounts
- _UnixHTTPClient
- _raise_for_status
- _resolve_mount
- _StateFile
- _BufferedWriteFile
- _PassthroughWriteFile
- _open_read / _open_write
- _install_state_proxy_hooks
"""

import builtins
import errno
import json
import os
import socket
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).parent.parent))

import asya_runtime


# ---------------------------------------------------------------------------
# Mock Unix-socket HTTP server for state connector simulation
# ---------------------------------------------------------------------------


class _MockConnectorHandler(BaseHTTPRequestHandler):
    """HTTP request handler that operates on an in-memory key-value store."""

    def log_message(self, format, *args):  # noqa: A002
        pass  # suppress server-side output during tests

    def _send_json(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _parse_key(self):
        path = self.path
        # strip leading /keys/
        if path.startswith("/keys/"):
            return path[len("/keys/") :]
        # strip leading /keys (no trailing /)
        if path == "/keys":
            return ""
        return None

    def do_HEAD(self):  # noqa: N802
        key = self._parse_key()
        store = self.server.store
        if key not in store:
            self.send_response(404)
            self.end_headers()
            return
        data = store[key]
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Is-File", "true")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        # Handle /meta/ routes for xattr
        if self.path.startswith("/meta/"):
            parsed = urllib.parse.urlparse(self.path)
            path_part = parsed.path[len("/meta/") :]
            qs = urllib.parse.parse_qs(parsed.query)
            if qs.get("attr"):
                key_part = path_part
                attr = qs["attr"][0]
                if key_part not in self.server.store:
                    self._send_json(404, {"message": "key not found"})
                    return
                if attr == "url":
                    self._send_json(200, {"attr": "url", "value": "stub://" + key_part})
                elif attr == "content_type":
                    self._send_json(200, {"attr": "content_type", "value": "application/octet-stream"})
                else:
                    self._send_json(400, {"error": "unsupported_attribute", "message": f"unsupported: {attr}"})
            else:
                if path_part not in self.server.store:
                    self._send_json(404, {"message": "key not found"})
                    return
                self._send_json(200, {"attrs": ["url", "content_type"]})
            return

        # listing: /keys/?prefix=...&delimiter=/
        if "?" in self.path:
            base, qs = self.path.split("?", 1)
            params = {}
            for part in qs.split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    params[k] = v
            prefix = params.get("prefix", "")
            delimiter = params.get("delimiter", "")
            store = self.server.store
            keys = []
            prefixes = set()
            for k in store:
                if not k.startswith(prefix):
                    continue
                rest = k[len(prefix) :]
                if delimiter and delimiter in rest:
                    sub = rest.split(delimiter)[0] + delimiter
                    prefixes.add(prefix + sub)
                else:
                    keys.append(k)
            self._send_json(200, {"keys": keys, "prefixes": sorted(prefixes)})
            return

        key = self._parse_key()
        store = self.server.store
        if key is None or key not in store:
            self._send_json(404, {"message": f"key not found: {key}"})
            return
        data = store[key]
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_PUT(self):  # noqa: N802
        if self.path.startswith("/meta/"):
            parsed = urllib.parse.urlparse(self.path)
            path_part = parsed.path[len("/meta/") :]
            qs = urllib.parse.parse_qs(parsed.query)
            if qs.get("attr"):
                key_part = path_part
                attr = qs["attr"][0]
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                if key_part not in self.server.store:
                    self._send_json(404, {"message": "key not found"})
                    return
                if attr == "content_type":
                    self.send_response(204)
                    self.end_headers()
                elif attr == "url":
                    self._send_json(403, {"error": "permission_denied", "message": "read-only"})
                else:
                    self._send_json(400, {"error": "unsupported_attribute", "message": f"unsupported: {attr}"})
            else:
                self._send_json(400, {"error": "bad_request", "message": "attr required"})
            return

        key = self._parse_key()
        transfer_encoding = self.headers.get("Transfer-Encoding", "")
        if "chunked" in transfer_encoding.lower():
            # read chunked body
            chunks = []
            while True:
                size_line = self.rfile.readline().strip()
                chunk_size = int(size_line, 16)
                if chunk_size == 0:
                    self.rfile.readline()  # trailing CRLF
                    break
                chunk = self.rfile.read(chunk_size)
                self.rfile.readline()  # CRLF after chunk
                chunks.append(chunk)
            body = b"".join(chunks)
        else:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
        # Record the request headers so tests can inspect them
        if not hasattr(self.server, "last_put_headers"):
            self.server.last_put_headers = {}
        self.server.last_put_headers[key] = dict(self.headers)
        # If-None-Match: * means create-only; reject with 412 if key exists
        if_none_match = self.headers.get("If-None-Match", "")
        if if_none_match == "*" and key in self.server.store:
            self._send_json(412, {"message": f"key already exists: {key}"})
            return
        self.server.store[key] = body
        self._send_json(200, {"ok": True})

    def do_DELETE(self):  # noqa: N802
        key = self._parse_key()
        store = self.server.store
        if key not in store:
            self._send_json(404, {"message": "key not found"})
            return
        del store[key]
        self._send_json(200, {"ok": True})


class _MockUnixHTTPServer(HTTPServer):
    """HTTPServer that listens on a Unix domain socket."""

    address_family = socket.AF_UNIX

    def server_bind(self):
        self.socket.bind(self.server_address)

    def server_close(self):
        super().server_close()
        try:
            os.unlink(self.server_address)
        except OSError:
            pass


class _MockConnectorServer:
    """Simple HTTP server on Unix socket for testing state proxy interception."""

    def __init__(self, socket_path):
        self.socket_path = socket_path
        self.store = {}
        self._server = _MockUnixHTTPServer(socket_path, _MockConnectorHandler)
        self._server.store = self.store
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self):
        self._server.shutdown()
        self._thread.join(timeout=5)
        self._server.server_close()


@pytest.fixture
def tmp_sock(tmp_path):
    """Yield a temporary socket path that does not yet exist."""
    return str(tmp_path / "test.sock")


@pytest.fixture
def mock_server(tmp_path):
    """Start a mock connector server on a temp Unix socket. Yields the server."""
    sock_path = str(tmp_path / "connector.sock")
    srv = _MockConnectorServer(sock_path)
    yield srv
    srv.close()


# ---------------------------------------------------------------------------
# Fixture: save/restore builtins and os functions around patching tests
# ---------------------------------------------------------------------------


@pytest.fixture
def saved_builtins():
    """Save and restore builtins.open and os.* functions to avoid test pollution."""
    original_open = builtins.open
    original_stat = os.stat
    original_listdir = os.listdir
    original_unlink = os.unlink
    original_remove = os.remove
    original_makedirs = os.makedirs
    original_getxattr = getattr(os, "getxattr", None)
    original_listxattr = getattr(os, "listxattr", None)
    original_setxattr = getattr(os, "setxattr", None)
    yield
    builtins.open = original_open
    os.stat = original_stat
    os.listdir = original_listdir
    os.unlink = original_unlink
    os.remove = original_remove
    os.makedirs = original_makedirs
    if original_getxattr is not None:
        os.getxattr = original_getxattr
    elif hasattr(os, "getxattr"):
        delattr(os, "getxattr")
    if original_listxattr is not None:
        os.listxattr = original_listxattr
    elif hasattr(os, "listxattr"):
        delattr(os, "listxattr")
    if original_setxattr is not None:
        os.setxattr = original_setxattr
    elif hasattr(os, "setxattr"):
        delattr(os, "setxattr")


# ---------------------------------------------------------------------------
# 1. Mount Parser Tests
# ---------------------------------------------------------------------------


class TestParseMounts:
    def test_single_mount_basic(self):
        result = asya_runtime._parse_state_proxy_mounts("meta:/state/meta:write=buffered")
        assert len(result) == 1
        m = result[0]
        assert m["name"] == "meta"
        assert m["path"] == "/state/meta/"
        assert m["write_mode"] == "buffered"

    def test_single_mount_passthrough(self):
        result = asya_runtime._parse_state_proxy_mounts("media:/state/media:write=passthrough")
        assert len(result) == 1
        assert result[0]["write_mode"] == "passthrough"

    def test_multiple_mounts(self):
        result = asya_runtime._parse_state_proxy_mounts(
            "meta:/state/meta:write=buffered;media:/state/media:write=passthrough"
        )
        assert len(result) == 2
        assert result[0]["name"] == "meta"
        assert result[1]["name"] == "media"

    def test_socket_path_convention(self):
        result = asya_runtime._parse_state_proxy_mounts("meta:/state/meta:write=buffered")
        assert result[0]["socket"] == "/var/run/asya/state/meta.sock"

    def test_socket_path_uses_name(self):
        result = asya_runtime._parse_state_proxy_mounts("mystore:/data/mystore:write=buffered")
        assert result[0]["socket"] == "/var/run/asya/state/mystore.sock"

    def test_path_normalization_no_trailing_slash(self):
        # Paths without trailing slash get one appended
        result = asya_runtime._parse_state_proxy_mounts("meta:/state/meta:write=buffered")
        assert result[0]["path"].endswith("/")

    def test_path_normalization_already_has_slash(self):
        # Paths already ending with slash remain unchanged
        result = asya_runtime._parse_state_proxy_mounts("meta:/state/meta/:write=buffered")
        assert result[0]["path"] == "/state/meta/"

    def test_write_mode_parsed_from_options(self):
        result = asya_runtime._parse_state_proxy_mounts("meta:/state/meta:write=buffered")
        assert result[0]["write_mode"] == "buffered"

    def test_write_mode_default_when_option_missing(self):
        # When write= option is missing the default is "buffered" (opts.get("write", "buffered"))
        result = asya_runtime._parse_state_proxy_mounts("meta:/state/meta:someotheroption=val")
        assert result[0]["write_mode"] == "buffered"

    def test_invalid_format_missing_parts_raises(self):
        with pytest.raises(ValueError):
            asya_runtime._parse_state_proxy_mounts("meta:/state/meta")

    def test_invalid_format_only_name_raises(self):
        with pytest.raises(ValueError):
            asya_runtime._parse_state_proxy_mounts("meta")

    def test_empty_string_returns_empty(self):
        result = asya_runtime._parse_state_proxy_mounts("")
        assert result == []

    def test_semicolons_only_returns_empty(self):
        result = asya_runtime._parse_state_proxy_mounts(";;;")
        assert result == []

    def test_trailing_semicolon_ignored(self):
        result = asya_runtime._parse_state_proxy_mounts("meta:/state/meta:write=buffered;")
        assert len(result) == 1

    def test_whitespace_stripped_in_options(self):
        result = asya_runtime._parse_state_proxy_mounts("meta:/state/meta:write = buffered")
        assert result[0]["write_mode"] == "buffered"

    def test_multiple_options_comma_separated(self):
        # extra options beyond write= should parse without error
        result = asya_runtime._parse_state_proxy_mounts("meta:/state/meta:write=buffered,cache=no")
        assert result[0]["write_mode"] == "buffered"


# ---------------------------------------------------------------------------
# 2. Path Resolution Tests
# ---------------------------------------------------------------------------


class TestResolveMount:
    def _make_mounts(self, *paths):
        """Build a list of mount dicts from plain paths for testing."""
        mounts = []
        for p in paths:
            if not p.endswith("/"):
                p = p + "/"
            mounts.append({"name": "test", "path": p, "socket": "/tmp/test.sock", "write_mode": "buffered"})  # nosec B108
        return mounts

    def test_path_under_mount(self):
        mounts = self._make_mounts("/state/meta")
        mount, key = asya_runtime._resolve_mount("/state/meta/users/123", mounts)
        assert mount is not None
        assert key == "users/123"

    def test_path_not_under_any_mount(self):
        mounts = self._make_mounts("/state/meta")
        mount, key = asya_runtime._resolve_mount("/tmp/regular-file", mounts)  # nosec B108
        assert mount is None
        assert key is None

    def test_exact_mount_path_gives_empty_key(self):
        mounts = self._make_mounts("/state/meta")
        mount, key = asya_runtime._resolve_mount("/state/meta", mounts)
        assert mount is not None
        assert key == ""

    def test_exact_mount_path_with_slash_gives_empty_key(self):
        mounts = self._make_mounts("/state/meta")
        mount, key = asya_runtime._resolve_mount("/state/meta/", mounts)
        assert mount is not None
        assert key == ""

    def test_longer_prefix_wins(self):
        # More specific mount should match over shorter prefix
        mount_specific = {
            "name": "specific",
            "path": "/state/meta/",
            "socket": "/tmp/specific.sock",  # nosec B108
            "write_mode": "buffered",
        }
        mount_general = {
            "name": "general",
            "path": "/state/",
            "socket": "/tmp/general.sock",  # nosec B108
            "write_mode": "buffered",
        }
        mounts = [mount_specific, mount_general]
        mount, key = asya_runtime._resolve_mount("/state/meta/foo", mounts)
        assert mount["name"] == "specific"
        assert key == "foo"

    def test_longer_prefix_wins_general_listed_first(self):
        # Order should not matter; whichever matches first in list wins
        # (the real implementation iterates in order, so first match wins)
        mount_general = {
            "name": "general",
            "path": "/state/",
            "socket": "/tmp/general.sock",  # nosec B108
            "write_mode": "buffered",
        }
        mount_specific = {
            "name": "specific",
            "path": "/state/meta/",
            "socket": "/tmp/specific.sock",  # nosec B108
            "write_mode": "buffered",
        }
        mounts = [mount_general, mount_specific]
        # When general is listed first it matches first
        mount, key = asya_runtime._resolve_mount("/state/meta/foo", mounts)
        assert mount["name"] == "general"

    def test_relative_path_not_matched(self):
        mounts = self._make_mounts("/state/meta")
        mount, key = asya_runtime._resolve_mount("./foo", mounts)
        assert mount is None
        assert key is None

    def test_bytes_path_decoded(self):
        mounts = self._make_mounts("/state/meta")
        mount, key = asya_runtime._resolve_mount(b"/state/meta/item", mounts)
        assert mount is not None
        assert key == "item"

    def test_partial_prefix_not_matched(self):
        # /state/metadata should NOT match a mount at /state/meta/
        mounts = self._make_mounts("/state/meta")
        mount, key = asya_runtime._resolve_mount("/state/metadata/foo", mounts)
        assert mount is None

    def test_nested_key_multiple_segments(self):
        mounts = self._make_mounts("/state/meta")
        mount, key = asya_runtime._resolve_mount("/state/meta/a/b/c", mounts)
        assert mount is not None
        assert key == "a/b/c"


# ---------------------------------------------------------------------------
# 3. Error Mapping Tests (_raise_for_status)
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal fake HTTP response for _raise_for_status testing."""

    def __init__(self, status, body=None):
        self.status = status
        self._body = body if body is not None else json.dumps({"message": "State proxy error"}).encode()

    def read(self):
        return self._body


class TestRaiseForStatus:
    def test_200_no_exception(self):
        resp = _FakeResponse(200)
        # Should not raise
        asya_runtime._raise_for_status(resp, "some/key")

    def test_201_no_exception(self):
        resp = _FakeResponse(201)
        asya_runtime._raise_for_status(resp, "some/key")

    def test_404_raises_file_not_found(self):
        resp = _FakeResponse(404)
        with pytest.raises(FileNotFoundError):
            asya_runtime._raise_for_status(resp, "some/key")

    def test_409_raises_file_exists(self):
        resp = _FakeResponse(409)
        with pytest.raises(FileExistsError):
            asya_runtime._raise_for_status(resp, "some/key")

    def test_400_raises_value_error(self):
        resp = _FakeResponse(400)
        with pytest.raises(ValueError):
            asya_runtime._raise_for_status(resp, "some/key")

    def test_403_raises_permission_error(self):
        resp = _FakeResponse(403)
        with pytest.raises(PermissionError):
            asya_runtime._raise_for_status(resp, "some/key")

    def test_500_raises_os_error(self):
        resp = _FakeResponse(500)
        with pytest.raises(OSError):
            asya_runtime._raise_for_status(resp, "some/key")

    def test_503_raises_connection_error(self):
        resp = _FakeResponse(503)
        with pytest.raises(ConnectionError):
            asya_runtime._raise_for_status(resp, "some/key")

    def test_504_raises_timeout_error(self):
        resp = _FakeResponse(504)
        with pytest.raises(TimeoutError):
            asya_runtime._raise_for_status(resp, "some/key")

    def test_413_raises_os_error_with_efbig(self):
        resp = _FakeResponse(413)
        with pytest.raises(OSError) as exc_info:
            asya_runtime._raise_for_status(resp, "some/key")
        assert exc_info.value.args[0] == errno.EFBIG

    def test_unknown_4xx_raises_os_error(self):
        resp = _FakeResponse(422)
        with pytest.raises(OSError):
            asya_runtime._raise_for_status(resp, "some/key")

    def test_error_message_from_json_body_preserved(self):
        body = json.dumps({"message": "custom error message"}).encode()
        resp = _FakeResponse(404, body)
        with pytest.raises(FileNotFoundError, match="custom error message"):
            asya_runtime._raise_for_status(resp, "some/key")

    def test_error_message_fallback_when_json_invalid(self):
        resp = _FakeResponse(404, b"not json")
        with pytest.raises(FileNotFoundError):
            asya_runtime._raise_for_status(resp, "some/key")

    def test_503_message_preserved(self):
        body = json.dumps({"message": "service unavailable"}).encode()
        resp = _FakeResponse(503, body)
        with pytest.raises(ConnectionError, match="service unavailable"):
            asya_runtime._raise_for_status(resp, "some/key")


# ---------------------------------------------------------------------------
# 4. File Wrapper Tests (using mock server)
# ---------------------------------------------------------------------------


class TestStateFileRead:
    """Tests for _StateFile (read wrapper)."""

    def test_read_buffered_content(self):
        content = b"hello world"
        buf = tempfile.SpooledTemporaryFile(max_size=4096)  # noqa: SIM115
        buf.write(content)
        buf.seek(0)
        f = asya_runtime._StateFile(buf, seekable=True)
        assert f.read() == content

    def test_seek_works_on_buffered(self):
        buf = tempfile.SpooledTemporaryFile(max_size=4096)  # noqa: SIM115
        buf.write(b"abcdefgh")
        buf.seek(0)
        f = asya_runtime._StateFile(buf, seekable=True)
        f.seek(3)
        assert f.read() == b"defgh"

    def test_seek_raises_on_non_seekable(self):
        buf = tempfile.SpooledTemporaryFile(max_size=4096)  # noqa: SIM115
        buf.seek(0)
        f = asya_runtime._StateFile(buf, seekable=False)
        with pytest.raises(IOError):
            f.seek(0)

    def test_tell_raises_on_non_seekable(self):
        buf = tempfile.SpooledTemporaryFile(max_size=4096)  # noqa: SIM115
        buf.seek(0)
        f = asya_runtime._StateFile(buf, seekable=False)
        with pytest.raises(IOError):
            f.tell()

    def test_tell_works_on_seekable(self):
        buf = tempfile.SpooledTemporaryFile(max_size=4096)  # noqa: SIM115
        buf.write(b"abc")
        buf.seek(0)
        f = asya_runtime._StateFile(buf, seekable=True)
        f.read(1)
        assert f.tell() == 1

    def test_text_mode_decoding(self):
        content = "hello text"
        buf = tempfile.SpooledTemporaryFile(max_size=4096)  # noqa: SIM115
        buf.write(content.encode("utf-8"))
        buf.seek(0)
        f = asya_runtime._StateFile(buf, seekable=True, text_mode=True)
        result = f.read()
        assert result == content
        assert isinstance(result, str)

    def test_binary_mode_returns_bytes(self):
        buf = tempfile.SpooledTemporaryFile(max_size=4096)  # noqa: SIM115
        buf.write(b"raw bytes")
        buf.seek(0)
        f = asya_runtime._StateFile(buf, seekable=True, text_mode=False)
        result = f.read()
        assert isinstance(result, bytes)

    def test_context_manager_closes(self):
        buf = tempfile.SpooledTemporaryFile(max_size=4096)  # noqa: SIM115
        buf.seek(0)
        f = asya_runtime._StateFile(buf, seekable=True)
        with f:
            pass
        assert f.closed

    def test_closed_property_starts_false(self):
        buf = tempfile.SpooledTemporaryFile(max_size=4096)  # noqa: SIM115
        buf.seek(0)
        f = asya_runtime._StateFile(buf, seekable=True)
        assert not f.closed

    def test_readline_bytes(self):
        buf = tempfile.SpooledTemporaryFile(max_size=4096)  # noqa: SIM115
        buf.write(b"line1\nline2\n")
        buf.seek(0)
        f = asya_runtime._StateFile(buf, seekable=True)
        assert f.readline() == b"line1\n"
        assert f.readline() == b"line2\n"

    def test_readline_text_mode(self):
        buf = tempfile.SpooledTemporaryFile(max_size=4096)  # noqa: SIM115
        buf.write(b"line1\nline2\n")
        buf.seek(0)
        f = asya_runtime._StateFile(buf, seekable=True, text_mode=True)
        assert f.readline() == "line1\n"

    def test_readlines_returns_list(self):
        buf = tempfile.SpooledTemporaryFile(max_size=4096)  # noqa: SIM115
        buf.write(b"a\nb\nc\n")
        buf.seek(0)
        f = asya_runtime._StateFile(buf, seekable=True)
        lines = f.readlines()
        assert len(lines) == 3

    def test_readable_true(self):
        buf = tempfile.SpooledTemporaryFile(max_size=4096)  # noqa: SIM115
        buf.seek(0)
        f = asya_runtime._StateFile(buf, seekable=True)
        assert f.readable()

    def test_writable_false(self):
        buf = tempfile.SpooledTemporaryFile(max_size=4096)  # noqa: SIM115
        buf.seek(0)
        f = asya_runtime._StateFile(buf, seekable=True)
        assert not f.writable()

    def test_iteration(self):
        buf = tempfile.SpooledTemporaryFile(max_size=4096)  # noqa: SIM115
        buf.write(b"x\ny\n")
        buf.seek(0)
        f = asya_runtime._StateFile(buf, seekable=True)
        lines = list(f)
        assert len(lines) == 2

    def test_close_idempotent(self):
        buf = tempfile.SpooledTemporaryFile(max_size=4096)  # noqa: SIM115
        buf.seek(0)
        f = asya_runtime._StateFile(buf, seekable=True)
        f.close()
        f.close()  # should not raise
        assert f.closed


class TestBufferedWriteFile:
    """Tests for _BufferedWriteFile via mock server."""

    def test_write_and_close_sends_put(self, mock_server):
        f = asya_runtime._BufferedWriteFile(mock_server.socket_path, "mykey")
        f.write(b"hello")
        f.close()
        assert mock_server.store.get("mykey") == b"hello"

    def test_context_manager_flushes_on_exit(self, mock_server):
        with asya_runtime._BufferedWriteFile(mock_server.socket_path, "ctxkey") as f:
            f.write(b"context data")
        assert mock_server.store.get("ctxkey") == b"context data"

    def test_multiple_writes_accumulate(self, mock_server):
        f = asya_runtime._BufferedWriteFile(mock_server.socket_path, "multikey")
        f.write(b"part1")
        f.write(b"part2")
        f.write(b"part3")
        f.close()
        assert mock_server.store.get("multikey") == b"part1part2part3"

    def test_text_mode_encodes_string(self, mock_server):
        f = asya_runtime._BufferedWriteFile(mock_server.socket_path, "textkey", text_mode=True)
        f.write("hello text")
        f.close()
        assert mock_server.store.get("textkey") == b"hello text"

    def test_close_idempotent(self, mock_server):
        f = asya_runtime._BufferedWriteFile(mock_server.socket_path, "idempkey")
        f.write(b"data")
        f.close()
        f.close()  # should not send second PUT

    def test_closed_property(self, mock_server):
        f = asya_runtime._BufferedWriteFile(mock_server.socket_path, "closedpropkey")
        assert not f.closed
        f.close()
        assert f.closed

    def test_writable_true(self, mock_server):
        f = asya_runtime._BufferedWriteFile(mock_server.socket_path, "wkey")
        assert f.writable()
        f.close()

    def test_readable_false(self, mock_server):
        f = asya_runtime._BufferedWriteFile(mock_server.socket_path, "rkey")
        assert not f.readable()
        f.close()

    def test_seek_and_tell_work(self, mock_server):
        f = asya_runtime._BufferedWriteFile(mock_server.socket_path, "seekkey")
        f.write(b"abcde")
        f.seek(0)
        assert f.tell() == 0
        f.close()


class TestPassthroughWriteFile:
    """Tests for _PassthroughWriteFile via mock server."""

    def test_write_and_close_sends_data(self, mock_server):
        f = asya_runtime._PassthroughWriteFile(mock_server.socket_path, "ptkey")
        f.write(b"streamed data")
        f.close()
        assert mock_server.store.get("ptkey") == b"streamed data"

    def test_context_manager(self, mock_server):
        with asya_runtime._PassthroughWriteFile(mock_server.socket_path, "ptctxkey") as f:
            f.write(b"ctx stream")
        assert mock_server.store.get("ptctxkey") == b"ctx stream"

    def test_text_mode_encodes(self, mock_server):
        with asya_runtime._PassthroughWriteFile(mock_server.socket_path, "pttextkey", text_mode=True) as f:
            f.write("text streamed")
        assert mock_server.store.get("pttextkey") == b"text streamed"

    def test_seek_raises(self, mock_server):
        f = asya_runtime._PassthroughWriteFile(mock_server.socket_path, "ptseekkey")
        with pytest.raises(IOError):
            f.seek(0)
        f.close()

    def test_tell_raises(self, mock_server):
        f = asya_runtime._PassthroughWriteFile(mock_server.socket_path, "pttellkey")
        with pytest.raises(IOError):
            f.tell()
        f.close()

    def test_close_idempotent(self, mock_server):
        f = asya_runtime._PassthroughWriteFile(mock_server.socket_path, "ptidemkey")
        f.write(b"x")
        f.close()
        f.close()  # should not raise

    def test_writable_true(self, mock_server):
        f = asya_runtime._PassthroughWriteFile(mock_server.socket_path, "ptwkey")
        assert f.writable()
        f.close()

    def test_readable_false(self, mock_server):
        f = asya_runtime._PassthroughWriteFile(mock_server.socket_path, "ptrkey")
        assert not f.readable()
        f.close()

    def test_closed_property(self, mock_server):
        f = asya_runtime._PassthroughWriteFile(mock_server.socket_path, "ptclosedkey")
        assert not f.closed
        f.close()
        assert f.closed


class TestOpenRead:
    """Tests for _open_read via mock server."""

    def test_open_read_returns_state_file(self, mock_server):
        mock_server.store["readkey"] = b"test content"
        f = asya_runtime._open_read(mock_server.socket_path, "readkey", False)
        assert f.read() == b"test content"
        f.close()

    def test_open_read_seekable_with_content_length(self, mock_server):
        mock_server.store["seekread"] = b"seekable data"
        f = asya_runtime._open_read(mock_server.socket_path, "seekread", False)
        # Our mock server sends Content-Length, so file should be seekable
        f.seek(0)
        data = f.read()
        assert data == b"seekable data"
        f.close()

    def test_open_read_text_mode_decodes(self, mock_server):
        mock_server.store["textread"] = b"hello text"
        f = asya_runtime._open_read(mock_server.socket_path, "textread", True)
        result = f.read()
        assert isinstance(result, str)
        assert result == "hello text"
        f.close()

    def test_open_read_missing_key_raises(self, mock_server):
        with pytest.raises(FileNotFoundError):
            asya_runtime._open_read(mock_server.socket_path, "nonexistent", False)

    def test_open_read_empty_content(self, mock_server):
        mock_server.store["emptykey"] = b""
        f = asya_runtime._open_read(mock_server.socket_path, "emptykey", False)
        assert f.read() == b""
        f.close()


class TestOpenWrite:
    """Tests for _open_write via mock server."""

    def test_open_write_buffered_returns_buffered(self, mock_server):
        f = asya_runtime._open_write(mock_server.socket_path, "wbuf", "buffered", False)
        assert isinstance(f, asya_runtime._BufferedWriteFile)
        f.write(b"data")
        f.close()

    def test_open_write_passthrough_returns_passthrough(self, mock_server):
        f = asya_runtime._open_write(mock_server.socket_path, "wpass", "passthrough", False)
        assert isinstance(f, asya_runtime._PassthroughWriteFile)
        f.write(b"data")
        f.close()

    def test_open_write_buffered_stores_data(self, mock_server):
        with asya_runtime._open_write(mock_server.socket_path, "wbufdata", "buffered", False) as f:
            f.write(b"stored")
        assert mock_server.store.get("wbufdata") == b"stored"

    def test_open_write_passthrough_stores_data(self, mock_server):
        with asya_runtime._open_write(mock_server.socket_path, "wpassdata", "passthrough", False) as f:
            f.write(b"streamed")
        assert mock_server.store.get("wpassdata") == b"streamed"


# ---------------------------------------------------------------------------
# 5. Patching Tests (_install_state_proxy_hooks)
# ---------------------------------------------------------------------------


def _install_hooks_with_server(mock_server, mounts_str, monkeypatch):
    """Install state proxy hooks redirecting all mount sockets to mock_server."""
    _orig_parse = asya_runtime._parse_state_proxy_mounts

    def _override(s):
        r = _orig_parse(s)
        for m in r:
            m["socket"] = mock_server.socket_path
        return r

    monkeypatch.setattr(asya_runtime, "_parse_state_proxy_mounts", _override)
    asya_runtime._install_state_proxy_hooks(mounts_str)


def _install_hooks_no_server(mounts_str, monkeypatch):
    """Install state proxy hooks with a dummy socket path (server not needed)."""
    _orig_parse = asya_runtime._parse_state_proxy_mounts

    def _override(s):
        r = _orig_parse(s)
        for m in r:
            m["socket"] = "/nonexistent/path.sock"
        return r

    monkeypatch.setattr(asya_runtime, "_parse_state_proxy_mounts", _override)
    asya_runtime._install_state_proxy_hooks(mounts_str)


@pytest.mark.usefixtures("saved_builtins")
class TestInstallStateProxyHooks:
    """Tests for _install_state_proxy_hooks using a real Unix socket server."""

    def test_open_state_path_reads_from_server(self, mock_server, monkeypatch):
        mock_server.store["users/123"] = b"user data"
        _install_hooks_with_server(mock_server, "meta:/state/meta:write=buffered", monkeypatch)

        with builtins.open("/state/meta/users/123") as f:
            content = f.read()
        assert content == "user data"

    def test_open_state_path_writes_to_server(self, mock_server, monkeypatch):
        _install_hooks_with_server(mock_server, "meta:/state/meta:write=buffered", monkeypatch)

        with builtins.open("/state/meta/newfile", "w") as f:
            f.write("written content")

        assert mock_server.store.get("newfile") == b"written content"

    def test_open_non_state_path_falls_through(self, monkeypatch, tmp_path):
        """open() for non-state path should use original open."""
        real_file = tmp_path / "regular.txt"
        real_file.write_bytes(b"real file content")

        _install_hooks_no_server("meta:/state/meta:write=buffered", monkeypatch)

        # This should NOT go through state proxy
        with builtins.open(str(real_file)) as f:
            content = f.read()
        assert content == "real file content"

    def test_os_path_exists_true_for_existing_key(self, mock_server, monkeypatch):
        mock_server.store["item"] = b"value"
        _install_hooks_with_server(mock_server, "meta:/state/meta:write=buffered", monkeypatch)

        assert os.path.exists("/state/meta/item")

    def test_os_path_exists_false_for_missing_key(self, mock_server, monkeypatch):
        _install_hooks_with_server(mock_server, "meta:/state/meta:write=buffered", monkeypatch)

        assert not os.path.exists("/state/meta/missing_item")

    def test_os_listdir_returns_entries(self, mock_server, monkeypatch):
        mock_server.store["dir/file1.txt"] = b"a"
        mock_server.store["dir/file2.txt"] = b"b"
        _install_hooks_with_server(mock_server, "meta:/state/meta:write=buffered", monkeypatch)

        entries = os.listdir("/state/meta/dir")
        assert "file1.txt" in entries
        assert "file2.txt" in entries

    def test_os_remove_deletes_key(self, mock_server, monkeypatch):
        mock_server.store["delme"] = b"data"
        _install_hooks_with_server(mock_server, "meta:/state/meta:write=buffered", monkeypatch)

        os.remove("/state/meta/delme")
        assert "delme" not in mock_server.store

    def test_os_makedirs_noop_for_state_paths(self, mock_server, monkeypatch):
        """os.makedirs for state paths is a no-op."""
        _install_hooks_with_server(mock_server, "meta:/state/meta:write=buffered", monkeypatch)

        # Should not raise, should not create anything
        os.makedirs("/state/meta/somedir", exist_ok=True)

    def test_os_makedirs_works_normally_for_non_state_paths(self, monkeypatch, tmp_path):
        """os.makedirs for non-state paths uses the real implementation."""
        _install_hooks_no_server("meta:/state/meta:write=buffered", monkeypatch)

        new_dir = str(tmp_path / "new" / "nested" / "dir")
        os.makedirs(new_dir, exist_ok=True)
        assert os.path.isdir(new_dir)

    def test_os_unlink_deletes_key(self, mock_server, monkeypatch):
        mock_server.store["unlinkme"] = b"data"
        _install_hooks_with_server(mock_server, "meta:/state/meta:write=buffered", monkeypatch)

        os.unlink("/state/meta/unlinkme")
        assert "unlinkme" not in mock_server.store

    def test_os_remove_nonexistent_raises_file_not_found(self, mock_server, monkeypatch):
        _install_hooks_with_server(mock_server, "meta:/state/meta:write=buffered", monkeypatch)

        with pytest.raises(FileNotFoundError):
            os.remove("/state/meta/nonexistent_key")

    def test_os_makedirs_exist_ok_false_state_path(self, mock_server, monkeypatch):
        _install_hooks_with_server(mock_server, "meta:/state/meta:write=buffered", monkeypatch)

        os.makedirs("/state/meta/somedir", exist_ok=False)

    def test_open_write_then_read_roundtrip(self, mock_server, monkeypatch):
        _install_hooks_with_server(mock_server, "meta:/state/meta:write=buffered", monkeypatch)

        with builtins.open("/state/meta/roundtrip.txt", "w") as f:
            f.write("roundtrip content")

        with builtins.open("/state/meta/roundtrip.txt") as f:
            result = f.read()

        assert result == "roundtrip content"

    def test_os_stat_nonexistent_raises_file_not_found(self, mock_server, monkeypatch):
        _install_hooks_with_server(mock_server, "meta:/state/meta:write=buffered", monkeypatch)

        with pytest.raises(FileNotFoundError):
            os.stat("/state/meta/nonexistent_key")

    def test_open_state_path_exclusive_create_succeeds(self, mock_server, monkeypatch):
        """open(path, 'x') through the patched builtins succeeds when key does not exist."""
        _install_hooks_with_server(mock_server, "meta:/state/meta:write=buffered", monkeypatch)

        with builtins.open("/state/meta/new_exclusive_file", "x") as f:
            f.write("new content")

        assert mock_server.store.get("new_exclusive_file") == b"new content"

    def test_open_state_path_exclusive_create_fails_if_exists(self, mock_server, monkeypatch):
        """open(path, 'x') through the patched builtins raises FileExistsError when key exists."""
        mock_server.store["existing_file"] = b"old content"
        _install_hooks_with_server(mock_server, "meta:/state/meta:write=buffered", monkeypatch)

        with pytest.raises(FileExistsError):
            with builtins.open("/state/meta/existing_file", "x") as f:
                f.write("should not overwrite")


# ---------------------------------------------------------------------------
# 6. Local Dev Parity - no patching when env var not set
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("saved_builtins")
class TestNoPatchingWithoutEnvVar:
    """When ASYA_STATE_PROXY_MOUNTS is not set, builtins remain original."""

    def test_open_unchanged_without_env_var(self):
        original_open = builtins.open
        # Call _install_state_proxy_hooks with empty string (no mounts)
        asya_runtime._install_state_proxy_hooks("")
        assert builtins.open is original_open

    def test_os_stat_unchanged_without_env_var(self):
        original_stat = os.stat
        asya_runtime._install_state_proxy_hooks("")
        assert os.stat is original_stat

    def test_os_listdir_unchanged_without_env_var(self):
        original_listdir = os.listdir
        asya_runtime._install_state_proxy_hooks("")
        assert os.listdir is original_listdir

    def test_os_unlink_unchanged_without_env_var(self):
        original_unlink = os.unlink
        asya_runtime._install_state_proxy_hooks("")
        assert os.unlink is original_unlink

    def test_os_makedirs_unchanged_without_env_var(self):
        original_makedirs = os.makedirs
        asya_runtime._install_state_proxy_hooks("")
        assert os.makedirs is original_makedirs

    def test_semicolons_only_no_patching(self):
        original_open = builtins.open
        asya_runtime._install_state_proxy_hooks(";;;")
        assert builtins.open is original_open


# ---------------------------------------------------------------------------
# 7. Exclusive Create Mode Tests (open(path, "x") / "xb" / "xt")
# ---------------------------------------------------------------------------


class TestExclusiveCreateMode:
    """Tests for open(path, "x") exclusive create semantics in _BufferedWriteFile and _open_write."""

    def test_open_x_mode_succeeds_when_key_absent(self, mock_server):
        """open(path, "x") succeeds and stores data when the key does not exist."""
        f = asya_runtime._BufferedWriteFile(mock_server.socket_path, "newkey", exclusive=True)
        f.write(b"exclusive data")
        f.close()
        assert mock_server.store.get("newkey") == b"exclusive data"

    def test_open_x_mode_raises_file_exists_on_412(self, mock_server):
        """open(path, "x") raises FileExistsError when server returns 412 (key already exists)."""
        mock_server.store["existing"] = b"already here"
        f = asya_runtime._BufferedWriteFile(mock_server.socket_path, "existing", exclusive=True)
        f.write(b"should not overwrite")
        with pytest.raises(FileExistsError):
            f.close()

    def test_open_xb_mode_binary_raises_file_exists_on_412(self, mock_server):
        """open(path, "xb") binary exclusive mode raises FileExistsError on 412."""
        mock_server.store["binkey"] = b"original"
        f = asya_runtime._BufferedWriteFile(mock_server.socket_path, "binkey", text_mode=False, exclusive=True)
        f.write(b"conflict")
        with pytest.raises(FileExistsError):
            f.close()

    def test_open_xt_mode_text_raises_file_exists_on_412(self, mock_server):
        """open(path, "xt") text exclusive mode raises FileExistsError on 412."""
        mock_server.store["txtkey"] = b"original"
        f = asya_runtime._BufferedWriteFile(mock_server.socket_path, "txtkey", text_mode=True, exclusive=True)
        f.write("conflict text")
        with pytest.raises(FileExistsError):
            f.close()

    def test_open_x_mode_sends_if_none_match_header(self, mock_server):
        """open(path, "x") sends If-None-Match: * header in the PUT request."""
        f = asya_runtime._BufferedWriteFile(mock_server.socket_path, "sentinel", exclusive=True)
        f.write(b"sentinel value")
        f.close()
        put_headers = mock_server._server.last_put_headers.get("sentinel", {})
        assert put_headers.get("If-None-Match") == "*"

    def test_open_w_mode_does_not_send_if_none_match_header(self, mock_server):
        """Normal write mode ("w") does NOT include If-None-Match header."""
        f = asya_runtime._BufferedWriteFile(mock_server.socket_path, "normalkey", exclusive=False)
        f.write(b"normal write")
        f.close()
        put_headers = mock_server._server.last_put_headers.get("normalkey", {})
        assert "If-None-Match" not in put_headers


# ---------------------------------------------------------------------------
# 8. xattr patching tests
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("saved_builtins")
class TestXattrPatching:
    """Tests for patched os.getxattr, os.listxattr, os.setxattr."""

    def test_listxattr_returns_prefixed_attrs(self, mock_server, monkeypatch):
        mock_server.store["xkey"] = b"data"
        _install_hooks_with_server(mock_server, "meta:/state/meta:write=buffered", monkeypatch)

        attrs = os.listxattr("/state/meta/xkey")
        assert "user.asya.url" in attrs
        assert "user.asya.content_type" in attrs

    def test_getxattr_returns_bytes(self, mock_server, monkeypatch):
        mock_server.store["xkey"] = b"data"
        _install_hooks_with_server(mock_server, "meta:/state/meta:write=buffered", monkeypatch)

        value = os.getxattr("/state/meta/xkey", "user.asya.url")
        assert isinstance(value, bytes)
        assert b"stub://xkey" in value

    def test_getxattr_unsupported_raises_oserror(self, mock_server, monkeypatch):
        mock_server.store["xkey"] = b"data"
        _install_hooks_with_server(mock_server, "meta:/state/meta:write=buffered", monkeypatch)

        with pytest.raises(OSError) as exc_info:
            os.getxattr("/state/meta/xkey", "user.asya.nosuch")
        assert exc_info.value.errno == errno.ENODATA

    def test_setxattr_succeeds(self, mock_server, monkeypatch):
        mock_server.store["xkey"] = b"data"
        _install_hooks_with_server(mock_server, "meta:/state/meta:write=buffered", monkeypatch)

        os.setxattr("/state/meta/xkey", "user.asya.content_type", b"text/plain")

    def test_setxattr_readonly_raises_permission_error(self, mock_server, monkeypatch):
        mock_server.store["xkey"] = b"data"
        _install_hooks_with_server(mock_server, "meta:/state/meta:write=buffered", monkeypatch)

        with pytest.raises(PermissionError):
            os.setxattr("/state/meta/xkey", "user.asya.url", b"x")

    def test_getxattr_non_asya_prefix_falls_through(self, monkeypatch, tmp_path):
        _install_hooks_no_server("meta:/state/meta:write=buffered", monkeypatch)
        # Non user.asya.* attrs should fall through (or raise ENOTSUP/ENODATA)
        with pytest.raises(OSError):
            os.getxattr(str(tmp_path), "user.other.attr")

    def test_listxattr_non_state_path_falls_through(self, monkeypatch, tmp_path):
        _install_hooks_no_server("meta:/state/meta:write=buffered", monkeypatch)
        # Non-state paths should fall through to native
        result = os.listxattr(str(tmp_path))
        assert isinstance(result, list)
