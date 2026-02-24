#!/usr/bin/env python3
"""Tests for asya_runtime.py HTTP-over-Unix-socket server."""

import http.client as http_client
import importlib
import json
import os
import socket
import stat
import sys
import tempfile
import textwrap
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest


# Add parent directory to path to import asya_runtime functions
sys.path.insert(0, str(Path(__file__).parent.parent))

import asya_runtime


class _UnixHTTPConnection(http_client.HTTPConnection):
    """HTTP connection over Unix socket for testing."""

    def __init__(self, socket_path):
        super().__init__("localhost")
        self._socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self._socket_path)


@pytest.fixture
def mock_env():
    """
    Fixture factory for setting environment variables and reloading asya_runtime.

    This provides the most realistic testing by using actual environment variables
    and module reloading, matching production behavior exactly.

    Usage:
        def test_something(mock_env):
            with mock_env(ASYA_SOCKET_CHMOD="0o600"):
                # asya_runtime module is reloaded with new env vars
                assert asya_runtime.ASYA_SOCKET_CHMOD == "0o600"

    Yields:
        Callable: Context manager that accepts env var overrides as kwargs
    """

    @contextmanager
    def _mock_env(**env_vars):
        original_env = {}
        try:
            # Save and set environment variables
            for key, value in env_vars.items():
                original_env[key] = os.environ.get(key)
                os.environ[key] = str(value)

            # Reload module to pick up new env vars
            importlib.reload(asya_runtime)
            yield asya_runtime

        finally:
            # Restore original environment
            for key, original_value in original_env.items():
                if original_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = original_value

            # Reload module to restore original config
            importlib.reload(asya_runtime)

    return _mock_env


def call_invoke(message: dict, user_func) -> list[dict]:
    """Call _handle_invoke with a message dict and return response frames.

    Returns a list of frames:
    - On 200: returns parsed frames list from {"frames": [...]}
    - On 204: returns []
    - On 400/500: returns [{"error": "...", ...}] (single error frame)
    """
    data = json.dumps(message).encode("utf-8")
    status_code, body = asya_runtime._handle_invoke(data, user_func)

    if status_code == 204:
        return []

    parsed = json.loads(body.decode("utf-8"))

    if status_code == 200:
        return parsed["frames"]

    # 400 or 500: error response is a single frame
    return [parsed]


@pytest.fixture
def runtime_invoke(tmp_path):
    """Invoke a handler via HTTP runtime server and return (frames_or_error, status_code).

    Returns:
        For 200: (list[dict], 200) -- list of response frames
        For 204: ([], 204) -- abort (handler returned None)
        For 4xx/5xx: (dict, status) -- error response body
    """
    call_count = [0]

    def _invoke(user_func, message):
        call_count[0] += 1
        socket_path = str(tmp_path / f"rt-{call_count[0]}.sock")
        server = asya_runtime._UnixHTTPServer(socket_path, asya_runtime._InvokeHandler)
        server.user_func = user_func

        thread = threading.Thread(target=server.handle_request)
        thread.start()

        conn = _UnixHTTPConnection(socket_path)
        body = json.dumps(message).encode("utf-8")
        conn.request(
            "POST",
            "/invoke",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        status = resp.status
        raw = resp.read()
        conn.close()
        thread.join(timeout=5)
        server.server_close()

        if status == 204:
            return [], status
        if not raw:
            return {}, status
        data = json.loads(raw)
        if status == 200:
            return data["frames"], status
        return data, status

    return _invoke


class TestHandlerReturnTypeValidation:
    """Test handler return type validation in payload mode."""

    def test_handler_returns_string_payload_mode(self):
        """Test handler returning string instead of dict in payload mode."""

        def string_handler(payload):
            return "this is a string, not a dict"

        message = {
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "a", "next": []},
        }

        responses = call_invoke(message, string_handler)

        # String is a valid payload type
        assert len(responses) == 1
        assert responses[0]["payload"] == "this is a string, not a dict"

    def test_handler_returns_number_payload_mode(self):
        """Test handler returning number in payload mode."""

        def number_handler(payload):
            return 42

        message = {
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "a", "next": []},
        }

        responses = call_invoke(message, number_handler)

        assert len(responses) == 1
        assert responses[0]["payload"] == 42

    def test_handler_returns_none_payload_mode(self):
        """Test handler returning None in payload mode (abort execution)."""

        def none_handler(payload):
            return None

        message = {
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "a", "next": []},
        }

        responses = call_invoke(message, none_handler)

        assert len(responses) == 0

    def test_handler_returns_empty_list(self):
        """Test handler returning empty list (returns list as single payload)."""

        def empty_list_handler(payload):
            return []

        message = {
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "a", "next": []},
        }

        responses = call_invoke(message, empty_list_handler)

        assert len(responses) == 1
        assert responses[0]["payload"] == []


class TestRouteValidation:
    """Test route validation edge cases."""

    def test_parse_msg_route_not_dict(self):
        """Test route as string instead of dict - should fail validation."""
        with pytest.raises(ValueError, match="Field 'route' must be a dict"):
            data = json.dumps({"payload": {"test": "data"}, "route": "not a dict"}).encode("utf-8")
            msg = asya_runtime._parse_message_json(data)
            asya_runtime._validate_message(msg)

    def test_parse_msg_route_missing_prev(self):
        """Test route without prev field - should fail validation."""
        with pytest.raises(ValueError, match="Missing required field 'prev' in route"):
            data = json.dumps({"payload": {"test": "data"}, "route": {"curr": "a", "next": []}}).encode("utf-8")
            msg = asya_runtime._parse_message_json(data)
            asya_runtime._validate_message(msg)

    def test_parse_msg_route_missing_curr(self):
        """Test route without curr field - should fail validation."""
        with pytest.raises(ValueError, match="Missing required field 'curr' in route"):
            data = json.dumps({"payload": {"test": "data"}, "route": {"prev": [], "next": []}}).encode("utf-8")
            msg = asya_runtime._parse_message_json(data)
            asya_runtime._validate_message(msg)

    def test_parse_msg_route_missing_next(self):
        """Test route without next field - should fail validation."""
        with pytest.raises(ValueError, match="Missing required field 'next' in route"):
            data = json.dumps({"payload": {"test": "data"}, "route": {"prev": [], "curr": "a"}}).encode("utf-8")
            msg = asya_runtime._parse_message_json(data)
            asya_runtime._validate_message(msg)

    def test_parse_msg_route_prev_not_list(self):
        """Test route with prev as non-list - should fail validation."""
        with pytest.raises(ValueError, match="Field 'route.prev' must be a list"):
            data = json.dumps(
                {"payload": {"test": "data"}, "route": {"prev": "not a list", "curr": "a", "next": []}}
            ).encode("utf-8")
            msg = asya_runtime._parse_message_json(data)
            asya_runtime._validate_message(msg)

    def test_parse_msg_route_curr_not_string(self):
        """Test route with curr as non-string - should fail validation."""
        with pytest.raises(ValueError, match="Field 'route.curr' must be a string"):
            data = json.dumps({"payload": {"test": "data"}, "route": {"prev": [], "curr": 42, "next": []}}).encode(
                "utf-8"
            )
            msg = asya_runtime._parse_message_json(data)
            asya_runtime._validate_message(msg)

    def test_parse_msg_route_next_not_list(self):
        """Test route with next as non-list - should fail validation."""
        with pytest.raises(ValueError, match="Field 'route.next' must be a list"):
            data = json.dumps(
                {"payload": {"test": "data"}, "route": {"prev": [], "curr": "a", "next": "not a list"}}
            ).encode("utf-8")
            msg = asya_runtime._parse_message_json(data)
            asya_runtime._validate_message(msg)

    def test_parse_msg_route_valid_single_actor(self):
        """Test valid route with single actor."""
        data = json.dumps({"payload": {"test": "data"}, "route": {"prev": [], "curr": "a", "next": []}}).encode("utf-8")
        msg = asya_runtime._parse_message_json(data)
        validated = asya_runtime._validate_message(msg)

        assert validated["route"]["prev"] == []
        assert validated["route"]["curr"] == "a"
        assert validated["route"]["next"] == []

    def test_parse_msg_route_valid_multi_actor(self):
        """Test valid route with multiple actors."""
        data = json.dumps(
            {"payload": {"test": "data"}, "route": {"prev": ["x"], "curr": "a", "next": ["b", "c"]}}
        ).encode("utf-8")
        msg = asya_runtime._parse_message_json(data)
        validated = asya_runtime._validate_message(msg)

        assert validated["route"]["prev"] == ["x"]
        assert validated["route"]["curr"] == "a"
        assert validated["route"]["next"] == ["b", "c"]

    def test_parse_msg_route_end_of_route(self):
        """Test valid end-of-route marker (curr='', next=[])."""
        data = json.dumps({"payload": {"test": "data"}, "route": {"prev": ["a", "b"], "curr": "", "next": []}}).encode(
            "utf-8"
        )
        msg = asya_runtime._parse_message_json(data)
        validated = asya_runtime._validate_message(msg)

        assert validated["route"]["prev"] == ["a", "b"]
        assert validated["route"]["curr"] == ""
        assert validated["route"]["next"] == []


class TestMessageFieldPreservation:
    """Test that message fields are properly preserved through validation."""

    def test_validate_message_preserves_id_field(self):
        """Test that id field is preserved through validation."""
        message = {
            "id": "envelope-123",
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "a", "next": []},
        }
        validated = asya_runtime._validate_message(message)

        assert validated["id"] == "envelope-123"
        assert validated["payload"] == {"test": "data"}
        assert validated["route"] == {"prev": [], "curr": "a", "next": []}

    def test_validate_message_preserves_parent_id_field(self):
        """Test that parent_id field is preserved through validation."""
        message = {
            "id": "envelope-456",
            "parent_id": "parent-envelope-123",
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "a", "next": []},
        }
        validated = asya_runtime._validate_message(message)

        assert validated["id"] == "envelope-456"
        assert validated["parent_id"] == "parent-envelope-123"
        assert validated["payload"] == {"test": "data"}

    def test_validate_message_preserves_all_fields(self):
        """Test that all message fields are preserved together."""
        message = {
            "id": "envelope-789",
            "parent_id": "parent-envelope-456",
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "a", "next": ["b"]},
            "headers": {"trace_id": "trace-123", "priority": "high"},
        }
        validated = asya_runtime._validate_message(message)

        assert validated["id"] == "envelope-789"
        assert validated["parent_id"] == "parent-envelope-456"
        assert validated["payload"] == {"test": "data"}
        assert validated["route"] == {"prev": [], "curr": "a", "next": ["b"]}
        assert validated["headers"] == {"trace_id": "trace-123", "priority": "high"}

    def test_validate_message_preserves_status(self):
        """Test that status field is preserved through validation."""
        status = {
            "phase": "processing",
            "actor": "actor-a",
            "attempt": 1,
            "max_attempts": 1,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:01:00Z",
        }
        message = {
            "id": "status-msg-1",
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "a", "next": ["b"]},
            "status": status,
        }
        validated = asya_runtime._validate_message(message)

        assert validated["status"] == status
        assert validated["status"]["phase"] == "processing"
        assert validated["status"]["actor"] == "actor-a"

    def test_validate_message_without_status(self):
        """Test that messages without status field still validate (backward compat)."""
        message = {
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "a", "next": []},
        }
        validated = asya_runtime._validate_message(message)

        assert "status" not in validated

    def test_validate_message_without_id_field(self):
        """Test that message without id field still validates (id is optional)."""
        message = {
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "a", "next": []},
        }
        validated = asya_runtime._validate_message(message)

        assert "id" not in validated
        assert validated["payload"] == {"test": "data"}

    def test_validate_message_id_field_invalid_type(self):
        """Test that id field with non-string type fails validation."""
        message = {
            "id": 12345,
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "a", "next": []},
        }
        with pytest.raises(ValueError, match="Field 'id' must be a string"):
            asya_runtime._validate_message(message)

    def test_vfs_handler_accesses_id_field(self):
        """Test that handlers can access message id field via VFS."""

        def vfs_handler(payload):
            message_id = asya_runtime._msg_vfs.read("id")
            return {"message_id": message_id, "data": payload}

        message = {
            "id": "test-vfs-123",
            "payload": {"value": 42},
            "route": {"prev": [], "curr": "a", "next": []},
        }

        responses = call_invoke(message, vfs_handler)

        assert len(responses) == 1
        assert responses[0]["payload"]["message_id"] == "test-vfs-123"


class TestVFSRouteModification:
    """Test VFS-based route modification from handlers."""

    def test_vfs_handler_modifies_next_allowed(self):
        """Test that handler CAN modify route.next via VFS."""

        def next_modifying_handler(payload):
            # Write new next list to VFS - this is allowed
            asya_runtime._msg_vfs.write("route/next", "x\ny\nz")
            return payload

        message = {
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "a", "next": ["b", "c"]},
        }

        responses = call_invoke(message, next_modifying_handler)

        # Should succeed - handler replaced next via VFS.
        # Runtime shifts: "a" -> prev, curr becomes "x" (VFS-modified next[0])
        assert len(responses) == 1
        assert responses[0]["route"]["prev"] == ["a"]
        assert responses[0]["route"]["curr"] == "x"
        assert responses[0]["route"]["next"] == ["y", "z"]

    def test_vfs_handler_cannot_write_route_curr(self):
        """Test that handler cannot write route.curr via VFS (read-only)."""

        def curr_writer(payload):
            asya_runtime._msg_vfs.write("route/curr", "evil")
            return payload

        message = {
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "a", "next": []},
        }

        responses = call_invoke(message, curr_writer)

        # Should fail with PermissionError (processing_error)
        assert len(responses) == 1
        assert responses[0]["error"] == "processing_error"

    def test_vfs_handler_cannot_write_route_prev(self):
        """Test that handler cannot write route.prev via VFS (read-only)."""

        def prev_writer(payload):
            asya_runtime._msg_vfs.write("route/prev", "injected")
            return payload

        message = {
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "a", "next": ["b"]},
        }

        responses = call_invoke(message, prev_writer)

        # Should fail with PermissionError (processing_error)
        assert len(responses) == 1
        assert responses[0]["error"] == "processing_error"

    def test_vfs_handler_fanout_each_yields_with_vfs_next(self):
        """Test fan-out generator where each yield modifies route.next via VFS."""

        def fanout_handler(payload):
            asya_runtime._msg_vfs.write("route/next", "b")
            yield {"id": 1}
            asya_runtime._msg_vfs.write("route/next", "c")
            yield {"id": 2}

        message = {
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "a", "next": ["b"]},
        }

        responses = call_invoke(message, fanout_handler)

        assert len(responses) == 2
        assert responses[0]["payload"] == {"id": 1}
        assert responses[0]["route"]["curr"] == "b"
        assert responses[1]["payload"] == {"id": 2}
        assert responses[1]["route"]["curr"] == "c"

    def test_vfs_handler_adds_future_actors_via_next(self):
        """Test that handler CAN add future actors by writing route.next via VFS."""

        def extending_handler(payload):
            asya_runtime._msg_vfs.write("route/next", "c\nd\ne")
            return payload

        message = {
            "payload": {"test": "data"},
            "route": {"prev": ["a"], "curr": "b", "next": ["c"]},
        }

        responses = call_invoke(message, extending_handler)

        # Should succeed - only next changed via VFS.
        # Runtime shifts: "b" -> prev (prev becomes ["a","b"]), curr becomes "c"
        assert len(responses) == 1
        assert responses[0]["route"]["prev"] == ["a", "b"]
        assert responses[0]["route"]["curr"] == "c"
        assert responses[0]["route"]["next"] == ["d", "e"]

    def test_vfs_handler_replaces_future_actors(self):
        """Test that handler CAN replace future actors by writing route.next via VFS."""

        def replacing_handler(payload):
            asya_runtime._msg_vfs.write("route/next", "x\ny")
            return payload

        message = {
            "payload": {"test": "data"},
            "route": {"prev": ["a"], "curr": "b", "next": ["c", "d"]},
        }

        responses = call_invoke(message, replacing_handler)

        # Should succeed - next replaced via VFS.
        # Runtime shifts: "b" -> prev (prev becomes ["a","b"]), curr becomes "x"
        assert len(responses) == 1
        assert responses[0]["route"]["prev"] == ["a", "b"]
        assert responses[0]["route"]["curr"] == "x"
        assert responses[0]["route"]["next"] == ["y"]


class TestLargePayloads:
    """Test handling of large payloads."""

    @pytest.mark.parametrize("size_kb", [10, 100, 500, 1024, 5 * 1024, 10 * 1024])
    def test_large_payloads(self, size_kb):
        """Test various payload sizes from KB to MB."""

        def echo_handler(payload):
            return payload

        large_data = "X" * (size_kb * 1024)
        message = {
            "payload": {"data": large_data},
            "route": {"prev": [], "curr": "a", "next": []},
        }

        responses = call_invoke(message, echo_handler)

        assert len(responses) == 1
        assert len(responses[0]["payload"]["data"]) == size_kb * 1024

    def test_empty_body_invoke(self):
        """Test _handle_invoke with empty body (invalid JSON)."""

        def simple_handler(payload):
            return payload

        status_code, body = asya_runtime._handle_invoke(b"", simple_handler)

        assert status_code == 400
        parsed = json.loads(body)
        assert parsed["error"] == "msg_parsing_error"


class TestConfigFixtures:
    """Test configuration fixture patterns."""

    def test_mock_env_fixture_basic(self, mock_env):
        """Test mock_env fixture with basic config override."""
        original_value = asya_runtime.ASYA_SOCKET_CHMOD
        assert original_value == asya_runtime.ASYA_SOCKET_CHMOD

        with mock_env(ASYA_SOCKET_CHMOD="0o600"):
            assert asya_runtime.ASYA_SOCKET_CHMOD == "0o600"

        assert original_value == asya_runtime.ASYA_SOCKET_CHMOD

    def test_mock_env_fixture_multiple_vars(self, mock_env):
        """Test mock_env fixture with multiple env vars."""
        with mock_env(
            ASYA_SOCKET_CHMOD="0o600",
            ASYA_ENABLE_VALIDATION="false",
        ):
            assert asya_runtime.ASYA_SOCKET_CHMOD == "0o600"
            assert asya_runtime.ASYA_ENABLE_VALIDATION is False


class TestInvokeProtocol:
    """Test the _handle_invoke HTTP protocol function."""

    def test_invoke_success(self):
        """Test _handle_invoke returns 200 with frames on success."""

        def echo_handler(payload):
            return payload

        data = json.dumps(
            {
                "payload": {"hello": "world"},
                "route": {"prev": [], "curr": "a", "next": []},
            }
        ).encode("utf-8")

        status_code, body = asya_runtime._handle_invoke(data, echo_handler)
        assert status_code == 200
        parsed = json.loads(body)
        assert "frames" in parsed
        assert len(parsed["frames"]) == 1
        assert parsed["frames"][0]["payload"] == {"hello": "world"}

    def test_invoke_none_response_returns_204(self):
        """Test _handle_invoke returns 204 when handler returns None."""

        def none_handler(payload):
            return None

        data = json.dumps(
            {
                "payload": {"test": True},
                "route": {"prev": [], "curr": "a", "next": []},
            }
        ).encode("utf-8")

        status_code, body = asya_runtime._handle_invoke(data, none_handler)
        assert status_code == 204
        assert body == b""

    def test_invoke_invalid_json_returns_400(self):
        """Test _handle_invoke returns 400 for invalid JSON."""

        def simple_handler(payload):
            return payload

        status_code, body = asya_runtime._handle_invoke(b"not valid json{", simple_handler)
        assert status_code == 400
        parsed = json.loads(body)
        assert parsed["error"] == "msg_parsing_error"

    def test_invoke_handler_exception_returns_500(self):
        """Test _handle_invoke returns 500 when handler raises."""

        def failing_handler(payload):
            raise ValueError("Handler failed")

        data = json.dumps(
            {
                "payload": {"test": "data"},
                "route": {"prev": [], "curr": "a", "next": []},
            }
        ).encode("utf-8")

        status_code, body = asya_runtime._handle_invoke(data, failing_handler)
        assert status_code == 500
        parsed = json.loads(body)
        assert parsed["error"] == "processing_error"
        assert parsed["details"]["message"] == "Handler failed"


class TestSocketSetup:
    """Test Unix HTTP socket server setup and cleanup."""

    def _make_dummy_handler(self):
        def dummy(payload):
            return payload

        return dummy

    def test_socket_setup_cleanup(self):
        """Test Unix HTTP server creates socket with default chmod."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            server = asya_runtime._UnixHTTPServer(socket_path, asya_runtime._InvokeHandler)
            server.user_func = self._make_dummy_handler()
            assert os.path.exists(socket_path)

            stat_info = os.stat(socket_path)
            permissions = oct(stat_info.st_mode)[-3:]
            assert permissions == "666"

            server.server_close()
            assert not os.path.exists(socket_path)

    def test_socket_setup_custom_chmod(self, monkeypatch):
        """Test Unix HTTP server creates socket with custom chmod."""
        monkeypatch.setattr(asya_runtime, "ASYA_SOCKET_CHMOD", "0o600")

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            server = asya_runtime._UnixHTTPServer(socket_path, asya_runtime._InvokeHandler)
            server.user_func = self._make_dummy_handler()
            assert os.path.exists(socket_path)

            stat_info = os.stat(socket_path)
            permissions = oct(stat_info.st_mode)[-3:]
            assert permissions == "600"

            server.server_close()

    def test_socket_setup_no_chmod(self, monkeypatch):
        """Test Unix HTTP server creates socket without chmod."""
        monkeypatch.setattr(asya_runtime, "ASYA_SOCKET_CHMOD", "")

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            server = asya_runtime._UnixHTTPServer(socket_path, asya_runtime._InvokeHandler)
            server.user_func = self._make_dummy_handler()
            assert os.path.exists(socket_path)

            stat_info = os.stat(socket_path)
            assert stat.S_ISSOCK(stat_info.st_mode)

            server.server_close()

    def test_socket_setup_removes_existing(self):
        """Test that Unix HTTP server removes existing socket file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            server1 = asya_runtime._UnixHTTPServer(socket_path, asya_runtime._InvokeHandler)
            server1.user_func = self._make_dummy_handler()
            server1.server_close()

            server2 = asya_runtime._UnixHTTPServer(socket_path, asya_runtime._InvokeHandler)
            server2.user_func = self._make_dummy_handler()
            assert os.path.exists(socket_path)

            server2.server_close()


class TestParseMsg:
    """Test _parse_message_json and _validate_message functions."""

    def test_parse_msg_with_payload_and_route(self):
        """Test parsing message with both payload and route."""
        data = json.dumps({"payload": {"test": "data"}, "route": {"prev": [], "curr": "a", "next": ["b"]}}).encode(
            "utf-8"
        )

        msg = asya_runtime._parse_message_json(data)
        msg = asya_runtime._validate_message(msg)

        assert msg["payload"] == {"test": "data"}
        assert msg["route"] == {"prev": [], "curr": "a", "next": ["b"]}

    def test_parse_msg_missing_payload(self):
        """Test parsing message without payload field."""
        with pytest.raises(ValueError, match="Missing required .*payload"):
            data = json.dumps({"route": {"prev": [], "curr": "a", "next": []}}).encode("utf-8")
            msg = asya_runtime._parse_message_json(data)
            asya_runtime._validate_message(msg)

    def test_parse_msg_missing_route(self):
        """Test parsing message without route field."""
        with pytest.raises(ValueError, match="Missing required .*route"):
            data = json.dumps({"payload": {"test": "data"}}).encode("utf-8")
            msg = asya_runtime._parse_message_json(data)
            asya_runtime._validate_message(msg)

    @pytest.mark.parametrize("payload", [None, {}])
    def test_parse_msg_empty_payload(self, payload):
        """Test parsing message with null/empty payload."""
        data = json.dumps({"payload": payload, "route": {"prev": [], "curr": "a", "next": []}}).encode("utf-8")

        msg = asya_runtime._parse_message_json(data)
        msg = asya_runtime._validate_message(msg)

        assert msg["payload"] == payload
        assert msg["route"] == {"prev": [], "curr": "a", "next": []}

    def test_parse_msg_invalid_json(self):
        """Test parsing invalid JSON."""
        with pytest.raises(json.JSONDecodeError):
            asya_runtime._parse_message_json(b"not json{")

    def test_parse_msg_invalid_utf8(self):
        """Test parsing invalid UTF-8."""
        with pytest.raises(UnicodeDecodeError):
            asya_runtime._parse_message_json(b"\xff\xfe invalid utf8")


class TestErrorDict:
    """Test _error_dict function."""

    def test_error_dict_basic(self):
        """Test error dict with just error code."""
        err = asya_runtime._error_response("test_error")
        assert err == {"error": "test_error"}

    def test_error_dict_with_exception(self):
        """Test error dict with exception details."""
        try:
            raise ValueError("Test exception envelope")
        except ValueError as e:
            err = asya_runtime._error_response("processing_error", e)
            assert err["error"] == "processing_error"
            assert err["details"]["message"] == "Test exception envelope"
            assert err["details"]["type"] == "ValueError"
            assert err["details"]["mro"] == ["Exception"]
            assert "traceback" in err["details"]
            assert "ValueError" in err["details"]["traceback"]

    def test_error_dict_stdlib_subclass_fqn_and_mro(self):
        """Test that stdlib subclass gets fully qualified type and MRO chain."""
        import json as json_mod

        try:
            json_mod.loads("{invalid")
        except json_mod.JSONDecodeError as e:
            err = asya_runtime._error_response("processing_error", e)
            assert err["details"]["type"] == "json.decoder.JSONDecodeError"
            assert err["details"]["mro"] == ["ValueError", "Exception"]

    def test_error_dict_user_defined_subclass(self):
        """Test that user-defined exception subclass gets correct FQN and MRO."""

        class MyAppError(RuntimeError):
            pass

        class MySpecificError(MyAppError):
            pass

        try:
            raise MySpecificError("custom error")
        except MySpecificError as e:
            err = asya_runtime._error_response("processing_error", e)
            # User-defined classes have module set to test module
            assert "MySpecificError" in err["details"]["type"]
            mro = err["details"]["mro"]
            assert "MyAppError" in mro[0]
            assert "RuntimeError" in mro[1]
            assert "Exception" in mro[2]
            assert len(mro) == 3

    def test_error_dict_builtin_exception_no_module_prefix(self):
        """Test that builtin exceptions have no module prefix."""
        try:
            raise KeyError("missing key")
        except KeyError as e:
            err = asya_runtime._error_response("processing_error", e)
            assert err["details"]["type"] == "KeyError"
            assert err["details"]["mro"] == ["LookupError", "Exception"]


class TestHandleRequestPayloadMode:
    """Test _handle_invoke in payload mode."""

    def test_handle_request_success_single_output(self):
        """Test successful request with single output."""

        def simple_handler(payload):
            return {"result": payload["value"] * 2}

        message = {
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"value": 42},
        }

        responses = call_invoke(message, simple_handler)

        assert len(responses) == 1
        assert responses[0]["payload"] == {"result": 84}
        # Route shifts: curr becomes "", prev gets "actor1"
        assert responses[0]["route"] == {"prev": ["actor1"], "curr": "", "next": []}

    def test_handle_request_multi_actor_route(self):
        """Test that payload mode shifts route for multi-actor pipelines."""

        def pipeline_handler(payload):
            return {"doubled": payload["value"] * 2}

        # Message for actor at start of 3-actor pipeline
        message = {
            "route": {"prev": [], "curr": "doubler", "next": ["incrementer", "finalizer"]},
            "payload": {"value": 21},
        }

        responses = call_invoke(message, pipeline_handler)

        assert len(responses) == 1
        assert responses[0]["payload"] == {"doubled": 42}
        # Route shifts: "doubler" moves to prev, curr becomes "incrementer"
        assert responses[0]["route"] == {"prev": ["doubler"], "curr": "incrementer", "next": ["finalizer"]}

    def test_handle_request_fanout_list_output(self):
        """Test fan-out with list output in payload mode."""

        def fanout_handler(payload):
            yield {"id": 1}
            yield {"id": 2}
            yield {"id": 3}

        message = {
            "route": {"prev": [], "curr": "fan", "next": []},
            "payload": {"test": "data"},
        }

        responses = call_invoke(message, fanout_handler)

        assert len(responses) == 3
        assert responses[0]["payload"] == {"id": 1}
        assert responses[1]["payload"] == {"id": 2}
        assert responses[2]["payload"] == {"id": 3}
        # All should have shifted route (auto-shifts)
        for resp in responses:
            assert resp["route"] == {"prev": ["fan"], "curr": "", "next": []}


class TestHandleRequestVFSMode:
    """Test _handle_invoke with VFS-based metadata access."""

    def test_handle_request_success_single_output(self):
        """Test successful request with single output using payload mode."""

        def simple_handler(payload):
            return {"result": payload["value"] * 2}

        message = {
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"value": 42},
        }

        responses = call_invoke(message, simple_handler)

        assert len(responses) == 1
        assert responses[0]["payload"] == {"result": 84}
        # Route shifts: actor1 -> prev, curr becomes ""
        assert responses[0]["route"] == {"prev": ["actor1"], "curr": "", "next": []}

    def test_handle_request_route_modification_via_vfs(self):
        """Test that handler can modify next via VFS."""

        def route_modifying_handler(payload):
            # Read current next and append "modified"
            current_next = asya_runtime._msg_vfs.read("route/next").strip()
            new_next = (current_next + "\nmodified").strip()
            asya_runtime._msg_vfs.write("route/next", new_next)
            return payload

        message = {
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"data": "test"},
        }

        responses = call_invoke(message, route_modifying_handler)

        assert len(responses) == 1
        # Route shifts: handler appended "modified" to next, so curr becomes "modified"
        assert responses[0]["route"]["prev"] == ["actor1"]
        assert responses[0]["route"]["curr"] == "modified"
        assert responses[0]["route"]["next"] == []

    def test_handle_request_fanout_list_output(self):
        """Test fan-out with generator in payload mode."""

        def fanout_handler(payload):
            yield {"id": 1}
            yield {"id": 2}
            yield {"id": 3}

        message = {
            "route": {"prev": [], "curr": "fan", "next": []},
            "payload": {"test": "data"},
        }

        responses = call_invoke(message, fanout_handler)

        assert len(responses) == 3
        assert responses[0]["payload"] == {"id": 1}
        assert responses[1]["payload"] == {"id": 2}
        assert responses[2]["payload"] == {"id": 3}

    def test_handle_request_vfs_read_id(self):
        """Test that handler can read message id via VFS."""

        def id_reader(payload):
            msg_id = asya_runtime._msg_vfs.read("id")
            return {"id_seen": msg_id, **payload}

        message = {
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"test": "data"},
            "id": "msg-xyz-789",
        }

        responses = call_invoke(message, id_reader)

        assert len(responses) == 1
        assert responses[0]["payload"]["id_seen"] == "msg-xyz-789"


class TestHandleRequestErrorCases:
    """Test error handling in _handle_invoke."""

    def test_handle_request_invalid_json(self):
        """Test handling of invalid JSON."""

        def simple_handler(payload):
            return payload

        status_code, body = asya_runtime._handle_invoke(b"not valid json{", simple_handler)

        assert status_code == 400
        parsed = json.loads(body)
        assert parsed["error"] == "msg_parsing_error"
        assert "details" in parsed

    def test_handle_request_handler_exception(self):
        """Test handling of handler exceptions."""

        def failing_handler(payload):
            raise ValueError("Handler failed")

        message = {
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "a", "next": []},
        }

        responses = call_invoke(message, failing_handler)

        assert len(responses) == 1
        assert responses[0]["error"] == "processing_error"
        assert responses[0]["details"]["message"] == "Handler failed"
        assert responses[0]["details"]["type"] == "ValueError"

    def test_handle_request_generic_exception(self):
        """Test handling when an unexpected exception occurs during handler dispatch."""

        def raising_handler(payload):
            raise RuntimeError("unexpected failure")

        message = {
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"test": "data"},
        }

        responses = call_invoke(message, raising_handler)

        assert len(responses) == 1
        assert responses[0]["error"] == "processing_error"
        assert "unexpected failure" in responses[0]["details"]["message"]


class TestClassBasedHandlers:
    """Test class handler detection and execution."""

    def test_class_handler_detection_and_instantiation(self, mock_env, tmp_path):
        """Test that class handlers are detected and instantiated correctly."""
        test_module = tmp_path / "test_class_handler.py"
        test_module.write_text(
            textwrap.dedent("""
            class Processor:
                def __init__(self):
                    self.counter = 0

                def process(self, payload):
                    self.counter += 1
                    return {"count": self.counter, "input": payload}
            """)
        )

        sys.path.insert(0, str(tmp_path))
        try:
            with mock_env(ASYA_HANDLER="test_class_handler.Processor.process"):
                handler = asya_runtime._load_function()
                assert callable(handler)
        finally:
            sys.path.pop(0)

    def test_class_handler_state_preserved_across_calls(self, mock_env, tmp_path):
        """Test that class state is preserved between multiple calls."""
        test_module = tmp_path / "stateful_handler.py"
        test_module.write_text(
            textwrap.dedent("""
            class StatefulProcessor:
                def __init__(self):
                    self.call_count = 0
                    self.total = 0

                def process(self, payload):
                    self.call_count += 1
                    self.total += payload.get("value", 0)
                    return {"calls": self.call_count, "total": self.total}
            """)
        )

        sys.path.insert(0, str(tmp_path))
        try:
            with mock_env(ASYA_HANDLER="stateful_handler.StatefulProcessor.process"):
                handler = asya_runtime._load_function()

                # First call
                message1 = {
                    "payload": {"value": 10},
                    "route": {"prev": [], "curr": "a", "next": []},
                }
                responses1 = call_invoke(message1, handler)

                assert len(responses1) == 1
                assert responses1[0]["payload"]["calls"] == 1
                assert responses1[0]["payload"]["total"] == 10

                # Second call
                message2 = {
                    "payload": {"value": 20},
                    "route": {"prev": [], "curr": "a", "next": []},
                }
                responses2 = call_invoke(message2, handler)

                assert len(responses2) == 1
                assert responses2[0]["payload"]["calls"] == 2
                assert responses2[0]["payload"]["total"] == 30

        finally:
            sys.path.pop(0)

    def test_class_handler_payload_mode(self, mock_env, tmp_path):
        """Test class handler in payload mode."""
        test_module = tmp_path / "payload_class.py"
        test_module.write_text(
            textwrap.dedent("""
            class PayloadProcessor:
                def __init__(self):
                    self.multiplier = 2

                def process(self, payload):
                    return {"result": payload["value"] * self.multiplier}
            """)
        )

        sys.path.insert(0, str(tmp_path))
        try:
            with mock_env(ASYA_HANDLER="payload_class.PayloadProcessor.process"):
                handler = asya_runtime._load_function()

                message = {
                    "payload": {"value": 21},
                    "route": {"prev": [], "curr": "a", "next": []},
                }
                responses = call_invoke(message, handler)

                assert len(responses) == 1
                assert responses[0]["payload"]["result"] == 42

        finally:
            sys.path.pop(0)

    def test_class_handler_vfs_headers_access(self, mock_env, tmp_path):
        """Test class handler that reads headers via VFS."""
        test_module = tmp_path / "vfs_class.py"
        test_module.write_text(
            textwrap.dedent("""
            import asya_runtime

            class VFSProcessor:
                def __init__(self):
                    self.prefix = "processed"

                def process(self, payload):
                    import asya_runtime
                    try:
                        trace_id = asya_runtime._msg_vfs.read("headers/trace_id")
                    except FileNotFoundError:
                        trace_id = ""
                    return {"prefix": self.prefix, "data": payload, "trace_id": trace_id}
            """)
        )

        sys.path.insert(0, str(tmp_path))
        try:
            with mock_env(ASYA_HANDLER="vfs_class.VFSProcessor.process"):
                handler = asya_runtime._load_function()

                message = {
                    "payload": {"value": 100},
                    "route": {"prev": [], "curr": "a", "next": []},
                    "headers": {"trace_id": "123"},
                }
                responses = call_invoke(message, handler)

                assert len(responses) == 1
                assert responses[0]["payload"]["prefix"] == "processed"
                assert responses[0]["payload"]["data"]["value"] == 100
                assert responses[0]["payload"]["trace_id"] == "123"

        finally:
            sys.path.pop(0)

    def test_class_handler_with_default_params(self, mock_env, tmp_path):
        """Test class handler with __init__ having default parameters."""
        test_module = tmp_path / "default_params.py"
        test_module.write_text(
            textwrap.dedent("""
            class ProcessorWithDefaults:
                def __init__(self, multiplier=3, prefix="result"):
                    self.multiplier = multiplier
                    self.prefix = prefix

                def process(self, payload):
                    return {self.prefix: payload["value"] * self.multiplier}
            """)
        )

        sys.path.insert(0, str(tmp_path))
        try:
            with mock_env(ASYA_HANDLER="default_params.ProcessorWithDefaults.process"):
                handler = asya_runtime._load_function()
                assert callable(handler)
        finally:
            sys.path.pop(0)

    def test_class_handler_init_without_defaults_fails(self, mock_env, tmp_path):
        """Test that class with required __init__ params fails."""
        test_module = tmp_path / "required_params.py"
        test_module.write_text(
            textwrap.dedent("""
            class ProcessorNoDefaults:
                def __init__(self, required_param):
                    self.value = required_param

                def process(self, payload):
                    return payload
            """)
        )

        sys.path.insert(0, str(tmp_path))
        try:
            with mock_env(ASYA_HANDLER="required_params.ProcessorNoDefaults.process"):
                with pytest.raises(SystemExit) as exc_info:
                    asya_runtime._load_function()
                assert exc_info.value.code == 1
        finally:
            sys.path.pop(0)

    def test_class_handler_missing_process_method(self, mock_env, tmp_path):
        """Test that class without process method fails."""
        test_module = tmp_path / "no_process.py"
        test_module.write_text(
            textwrap.dedent("""
            class ProcessorNoMethod:
                def __init__(self):
                    self.value = 42

                def other_method(self, payload):
                    return payload
            """)
        )

        sys.path.insert(0, str(tmp_path))
        try:
            with mock_env(ASYA_HANDLER="no_process.ProcessorNoMethod.process"):
                with pytest.raises(SystemExit) as exc_info:
                    asya_runtime._load_function()
                assert exc_info.value.code == 1
        finally:
            sys.path.pop(0)

    def test_class_handler_process_not_callable(self, mock_env, tmp_path):
        """Test that class with non-callable process attribute fails."""
        test_module = tmp_path / "process_not_callable.py"
        test_module.write_text(
            textwrap.dedent("""
            class ProcessorNotCallable:
                def __init__(self):
                    self.process = "not_a_method"
            """)
        )

        sys.path.insert(0, str(tmp_path))
        try:
            with mock_env(ASYA_HANDLER="process_not_callable.ProcessorNotCallable.process"):
                with pytest.raises(SystemExit) as exc_info:
                    asya_runtime._load_function()
                assert exc_info.value.code == 1
        finally:
            sys.path.pop(0)

    def test_class_handler_init_raises_exception(self, mock_env, tmp_path):
        """Test that class with failing __init__ fails gracefully."""
        test_module = tmp_path / "failing_init.py"
        test_module.write_text(
            textwrap.dedent("""
            class ProcessorFailingInit:
                def __init__(self):
                    raise RuntimeError("Initialization failed")

                def process(self, payload):
                    return payload
            """)
        )

        sys.path.insert(0, str(tmp_path))
        try:
            with mock_env(ASYA_HANDLER="failing_init.ProcessorFailingInit.process"):
                with pytest.raises(SystemExit) as exc_info:
                    asya_runtime._load_function()
                assert exc_info.value.code == 1
        finally:
            sys.path.pop(0)

    def test_class_handler_fanout_payload_mode(self, mock_env, tmp_path):
        """Test class handler returning list in payload mode."""
        test_module = tmp_path / "fanout_class.py"
        test_module.write_text(
            textwrap.dedent("""
            class FanoutProcessor:
                def __init__(self):
                    self.count = 3

                def process(self, payload):
                    for i in range(self.count):
                        yield {"id": i, "input": payload}
            """)
        )

        sys.path.insert(0, str(tmp_path))
        try:
            with mock_env(ASYA_HANDLER="fanout_class.FanoutProcessor.process"):
                handler = asya_runtime._load_function()

                message = {
                    "payload": {"value": 42},
                    "route": {"prev": [], "curr": "fan", "next": []},
                }
                responses = call_invoke(message, handler)

                assert len(responses) == 3
                assert responses[0]["payload"]["id"] == 0
                assert responses[1]["payload"]["id"] == 1
                assert responses[2]["payload"]["id"] == 2

        finally:
            sys.path.pop(0)

    def test_class_handler_returns_none(self, mock_env, tmp_path):
        """Test class handler returning None (abort execution)."""
        test_module = tmp_path / "none_class.py"
        test_module.write_text(
            textwrap.dedent("""
            class NoneProcessor:
                def __init__(self):
                    pass

                def process(self, payload):
                    return None
            """)
        )

        sys.path.insert(0, str(tmp_path))
        try:
            with mock_env(ASYA_HANDLER="none_class.NoneProcessor.process"):
                handler = asya_runtime._load_function()

                message = {
                    "payload": {"value": 42},
                    "route": {"prev": [], "curr": "a", "next": []},
                }
                responses = call_invoke(message, handler)

                assert len(responses) == 0

        finally:
            sys.path.pop(0)

    def test_class_handler_validation_disabled(self, mock_env, tmp_path):
        """Test class handler with validation disabled."""
        test_module = tmp_path / "no_validation.py"
        test_module.write_text(
            textwrap.dedent("""
            class NoValidationProcessor:
                def __init__(self):
                    self.value = 100

                def process(self, payload):
                    return {"result": self.value + payload.get("value", 0)}
            """)
        )

        sys.path.insert(0, str(tmp_path))
        try:
            with mock_env(ASYA_HANDLER="no_validation.NoValidationProcessor.process", ASYA_ENABLE_VALIDATION="false"):
                handler = asya_runtime._load_function()

                message = {
                    "payload": {"value": 23},
                    "route": {"prev": [], "curr": "a", "next": []},
                }
                responses = call_invoke(message, handler)

                assert len(responses) == 1
                assert responses[0]["payload"]["result"] == 123

        finally:
            sys.path.pop(0)

    def test_class_handler_with_complex_state(self, mock_env, tmp_path):
        """Test class handler with complex internal state."""
        test_module = tmp_path / "complex_state.py"
        test_module.write_text(
            textwrap.dedent("""
            class ComplexStateProcessor:
                def __init__(self, cache_size=10):
                    self.cache = []
                    self.cache_size = cache_size
                    self.stats = {"calls": 0, "cache_hits": 0}

                def process(self, payload):
                    self.stats["calls"] += 1
                    value = payload.get("value")

                    if value in self.cache:
                        self.stats["cache_hits"] += 1
                    else:
                        self.cache.append(value)
                        if len(self.cache) > self.cache_size:
                            self.cache.pop(0)

                    return {
                        "value": value,
                        "in_cache": value in self.cache,
                        "stats": self.stats.copy()
                    }
            """)
        )

        sys.path.insert(0, str(tmp_path))
        try:
            with mock_env(ASYA_HANDLER="complex_state.ComplexStateProcessor.process"):
                handler = asya_runtime._load_function()

                # First call
                message1 = {
                    "payload": {"value": 100},
                    "route": {"prev": [], "curr": "a", "next": []},
                }
                responses1 = call_invoke(message1, handler)

                assert responses1[0]["payload"]["stats"]["calls"] == 1
                assert responses1[0]["payload"]["stats"]["cache_hits"] == 0
                assert responses1[0]["payload"]["in_cache"]

                # Second call with same value
                message2 = {
                    "payload": {"value": 100},
                    "route": {"prev": [], "curr": "a", "next": []},
                }
                responses2 = call_invoke(message2, handler)

                assert responses2[0]["payload"]["stats"]["calls"] == 2
                assert responses2[0]["payload"]["stats"]["cache_hits"] == 1

        finally:
            sys.path.pop(0)

    def test_class_handler_without_custom_init(self, mock_env, tmp_path):
        """Test that class handlers without custom __init__ work correctly.

        This tests the fix for the bug where classes inheriting object.__init__
        (which has *args, **kwargs) were rejected by the runtime validation.
        """
        test_module = tmp_path / "no_init_handler.py"
        test_module.write_text(
            textwrap.dedent("""
            class ProcessorWithoutInit:
                MULTIPLIER = 3

                def process(self, payload):
                    return {"result": payload["value"] * self.MULTIPLIER}
            """)
        )

        sys.path.insert(0, str(tmp_path))
        try:
            with mock_env(ASYA_HANDLER="no_init_handler.ProcessorWithoutInit.process"):
                handler = asya_runtime._load_function()

                message = {
                    "payload": {"value": 7},
                    "route": {"prev": [], "curr": "a", "next": []},
                }
                responses = call_invoke(message, handler)

                assert len(responses) == 1
                assert responses[0]["payload"]["result"] == 21

        finally:
            sys.path.pop(0)


class TestLoadFunction:
    """Test the _load_function functionality."""

    def test_load_function_missing_handler(self, mock_env):
        """Test that missing ASYA_HANDLER causes exit."""
        with mock_env(ASYA_HANDLER=""):
            with pytest.raises(SystemExit) as excinfo:
                asya_runtime._load_function()
            assert excinfo.value.code == 1

    def test_load_function_invalid_format_no_dot(self, mock_env):
        """Test that ASYA_HANDLER without dot causes exit."""
        with mock_env(ASYA_HANDLER="invalid"):
            with pytest.raises(SystemExit) as excinfo:
                asya_runtime._load_function()
            assert excinfo.value.code == 1

    def test_load_function_invalid_format_special_chars(self, mock_env):
        """Test that ASYA_HANDLER with special characters causes exit."""
        invalid_handlers = [
            "../etc/passwd",
            "os;rm -rf /",
            "__import__('os').system('cmd')",
            "my-module.func",  # Hyphens not allowed
            "my module.func",  # Spaces not allowed
        ]

        for invalid in invalid_handlers:
            with mock_env(ASYA_HANDLER=invalid):
                with pytest.raises(SystemExit) as excinfo:
                    asya_runtime._load_function()
                assert excinfo.value.code == 1

    def test_load_function_module_not_found(self, mock_env):
        """Test that missing module causes exit."""
        with mock_env(ASYA_HANDLER="nonexistent_module_xyz.function"):
            with pytest.raises(SystemExit) as excinfo:
                asya_runtime._load_function()
            assert excinfo.value.code == 1

    def test_load_function_too_many_attr_parts(self, mock_env, tmp_path):
        """Test that ASYA_HANDLER with too many attribute parts (a.b.C.D.method) causes exit."""
        test_module = tmp_path / "deep_module.py"
        test_module.write_text(
            textwrap.dedent("""
            class Outer:
                class Inner:
                    def method(self): pass
            """)
        )
        sys.path.insert(0, str(tmp_path))
        try:
            with mock_env(ASYA_HANDLER="deep_module.Outer.Inner.method"):
                with pytest.raises(SystemExit) as exc_info:
                    asya_runtime._load_function()
                assert exc_info.value.code == 1
        finally:
            sys.path.pop(0)


class TestVFSReadOnly:
    """Test VFS read-only path enforcement."""

    def test_vfs_id_is_read_only(self):
        """Test that writing to VFS id path raises PermissionError."""

        def id_writer(payload):
            asya_runtime._msg_vfs.write("id", "injected")
            return payload

        message = {
            "id": "original-id",
            "payload": {"test": True},
            "route": {"prev": [], "curr": "a", "next": []},
        }

        responses = call_invoke(message, id_writer)

        assert len(responses) == 1
        assert responses[0]["error"] == "processing_error"

    def test_vfs_parent_id_is_read_only(self):
        """Test that writing to VFS parent_id path raises PermissionError."""

        def parent_id_writer(payload):
            asya_runtime._msg_vfs.write("parent_id", "injected")
            return payload

        message = {
            "id": "msg-1",
            "parent_id": "original-parent",
            "payload": {},
            "route": {"prev": [], "curr": "a", "next": []},
        }

        responses = call_invoke(message, parent_id_writer)

        assert len(responses) == 1
        assert responses[0]["error"] == "processing_error"

    def test_vfs_route_next_is_writable(self):
        """Test that route.next is writable via VFS."""

        def next_writer(payload):
            asya_runtime._msg_vfs.write("route/next", "new-actor")
            return payload

        message = {
            "payload": {"test": True},
            "route": {"prev": [], "curr": "a", "next": ["old-actor"]},
        }

        responses = call_invoke(message, next_writer)

        assert len(responses) == 1
        assert responses[0]["route"]["curr"] == "new-actor"
        assert responses[0]["route"]["next"] == []

    def test_vfs_msg_root_default(self):
        """Test that ASYA_MSG_ROOT defaults to /proc/asya/msg."""
        assert asya_runtime.ASYA_MSG_ROOT == "/proc/asya/msg"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_handle_request_unicode_content(self):
        """Test handling of unicode content."""

        def simple_handler(payload):
            return payload

        message = {
            "payload": {"text": "Hello 世界 こんにちは"},
            "route": {"prev": [], "curr": "a", "next": []},
        }

        responses = call_invoke(message, simple_handler)

        assert len(responses) == 1
        assert responses[0]["payload"]["text"] == "Hello 世界 こんにちは"

    def test_handle_request_deeply_nested_json(self):
        """Test handling of deeply nested JSON."""

        def simple_handler(payload):
            return payload

        nested = {"level": 0}
        current = nested
        for i in range(1, 50):
            current["next"] = {"level": i}
            current = current["next"]

        message = {"payload": nested, "route": {"prev": [], "curr": "a", "next": []}}

        responses = call_invoke(message, simple_handler)

        assert len(responses) == 1
        assert responses[0]["payload"]["level"] == 0

    def test_handle_request_null_payload(self):
        """Test handling of null payload."""

        def simple_handler(payload):
            return payload if payload is not None else {"default": True}

        message = {"payload": None, "route": {"prev": [], "curr": "a", "next": []}}

        responses = call_invoke(message, simple_handler)

        assert len(responses) == 1
        assert responses[0]["payload"] == {"default": True}

    def test_handler_raises_runtime_error(self):
        """Test handler that raises RuntimeError."""

        def error_handler(payload):
            raise RuntimeError("Something went wrong")

        message = {
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "a", "next": []},
        }

        responses = call_invoke(message, error_handler)

        assert len(responses) == 1
        response_error: str | None = responses[0].get("error")
        response_details: dict = responses[0].get("details", {})
        assert response_error == "processing_error"
        assert response_details.get("type") == "RuntimeError"
        assert "Something went wrong" in str(response_details.get("message", ""))

    def test_handler_returns_complex_types(self):
        """Test handler that returns various Python types."""

        def complex_handler(payload):
            return {
                "int": 42,
                "float": 3.14,
                "bool": True,
                "null": None,
                "string": "test",
                "list": [1, 2, 3],
                "nested": {"a": {"b": {"c": "deep"}}},
            }

        message = {
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "a", "next": []},
        }

        responses = call_invoke(message, complex_handler)

        assert len(responses) == 1
        assert responses[0]["payload"]["int"] == 42
        assert responses[0]["payload"]["float"] == 3.14
        assert responses[0]["payload"]["bool"] is True
        assert responses[0]["payload"]["null"] is None

    def test_handler_returns_large_response(self):
        """Test handler that returns a large response."""

        def large_handler(payload):
            return {"data": "X" * (1024 * 1024)}

        message = {
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "a", "next": []},
        }

        responses = call_invoke(message, large_handler)

        assert len(responses) == 1
        assert len(responses[0]["payload"]["data"]) == 1024 * 1024

    def test_message_with_special_characters(self):
        """Test messages with special JSON characters."""

        def simple_handler(payload):
            return payload

        message = {
            "payload": {"text": 'Test "quotes" and \\backslashes\\ and \n newlines \t tabs'},
            "route": {"prev": [], "curr": "a", "next": []},
        }

        responses = call_invoke(message, simple_handler)

        assert len(responses) == 1
        assert responses[0]["payload"]["text"] == 'Test "quotes" and \\backslashes\\ and \n newlines \t tabs'


class TestStatusPreservation:
    """Test that status field is properly preserved through message processing."""

    def test_payload_mode_preserves_status_in_frame(self):
        """Test that status is included in response frame in payload mode."""

        def simple_handler(payload):
            return {"result": payload["value"] * 2}

        status = {
            "phase": "processing",
            "actor": "doubler",
            "attempt": 1,
            "max_attempts": 1,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:01:00Z",
        }
        message = {
            "payload": {"value": 21},
            "route": {"prev": [], "curr": "doubler", "next": ["next_actor"]},
            "status": status,
        }

        responses = call_invoke(message, simple_handler)

        assert len(responses) == 1
        assert responses[0]["payload"] == {"result": 42}
        assert responses[0]["status"] == status
        # Route shifts: doubler -> prev, curr becomes next_actor
        assert responses[0]["route"] == {"prev": ["doubler"], "curr": "next_actor", "next": []}

    def test_payload_mode_no_status_backward_compat(self):
        """Test that payload mode works without status (backward compat)."""

        def simple_handler(payload):
            return {"result": "ok"}

        message = {
            "payload": {"test": True},
            "route": {"prev": [], "curr": "a", "next": []},
        }

        responses = call_invoke(message, simple_handler)

        assert len(responses) == 1
        assert responses[0]["payload"] == {"result": "ok"}
        assert "status" not in responses[0]

    def test_vfs_status_is_readable(self):
        """Test that status fields are readable via VFS."""

        def status_reader(payload):
            try:
                phase = asya_runtime._msg_vfs.read("status/phase")
            except FileNotFoundError:
                phase = "not-found"
            return {"phase_seen": phase, **payload}

        status = {
            "phase": "processing",
            "actor": "processor",
            "attempt": 1,
            "max_attempts": 1,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:01:00Z",
        }
        message = {
            "payload": {"data": "test"},
            "route": {"prev": [], "curr": "processor", "next": ["next_actor"]},
            "status": status,
        }

        responses = call_invoke(message, status_reader)

        assert len(responses) == 1
        assert responses[0]["payload"]["phase_seen"] == "processing"
        # Status is preserved through VFS snapshot automatically
        assert responses[0]["status"] == status


class TestHeadersPreservation:
    """Test that headers field is properly preserved through message processing."""

    def test_headers_preserved_in_payload_mode(self):
        """Test that headers are preserved when using payload mode."""

        def simple_handler(payload):
            return {"result": payload["value"] * 2}

        message = {
            "payload": {"value": 42},
            "route": {"prev": [], "curr": "doubler", "next": []},
            "headers": {"trace_id": "abc-123", "priority": "high"},
        }

        responses = call_invoke(message, simple_handler)

        assert len(responses) == 1
        assert responses[0]["payload"] == {"result": 84}
        assert responses[0]["headers"] == {"trace_id": "abc-123", "priority": "high"}
        # Payload mode shifts route: doubler -> prev, curr becomes ""
        assert responses[0]["route"] == {"prev": ["doubler"], "curr": "", "next": []}

    def test_headers_preserved_in_fanout_payload_mode(self):
        """Test that headers are preserved in fanout with payload mode."""

        def fanout_handler(payload):
            yield {"id": 1}
            yield {"id": 2}

        message = {
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "fan", "next": []},
            "headers": {"correlation_id": "xyz-789"},
        }

        responses = call_invoke(message, fanout_handler)

        assert len(responses) == 2
        assert responses[0]["payload"] == {"id": 1}
        assert responses[0]["headers"] == {"correlation_id": "xyz-789"}
        assert responses[1]["payload"] == {"id": 2}
        assert responses[1]["headers"] == {"correlation_id": "xyz-789"}

    def test_headers_optional_in_payload_mode(self):
        """Test that headers are optional and don't break processing."""

        def simple_handler(payload):
            return payload

        message = {
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "echo", "next": []},
        }

        responses = call_invoke(message, simple_handler)

        assert len(responses) == 1
        assert responses[0]["payload"] == {"test": "data"}
        assert "headers" not in responses[0]

    def test_headers_readable_via_vfs(self):
        """Test that headers are readable via VFS and preserved in output."""

        def header_reader(payload):
            req_id = asya_runtime._msg_vfs.read("headers/request_id")
            return {"value": payload["value"], "request_id": req_id}

        message = {
            "payload": {"value": 100},
            "route": {"prev": [], "curr": "passthrough", "next": []},
            "headers": {"request_id": "req-456"},
        }

        responses = call_invoke(message, header_reader)

        assert len(responses) == 1
        assert responses[0]["payload"] == {"value": 100, "request_id": "req-456"}
        # Headers preserved from VFS snapshot
        assert responses[0]["headers"] == {"request_id": "req-456"}

    def test_headers_validation_invalid_type(self):
        """Test that headers validation rejects non-dict types."""

        def simple_handler(payload):
            return payload

        message = {
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "echo", "next": []},
            "headers": "this should be a dict, not a string",
        }

        responses = call_invoke(message, simple_handler)

        assert len(responses) == 1
        assert responses[0]["error"] == "msg_parsing_error"
        assert "Field 'headers' must be a dict" in responses[0]["details"]["message"]


class TestVFSHeaderAccess:
    """Test VFS-based header access from handlers."""

    def test_vfs_headers_readable(self):
        """Test that headers are readable via VFS."""

        def header_reader(payload):
            priority = asya_runtime._msg_vfs.read("headers/priority")
            trace_id = asya_runtime._msg_vfs.read("headers/trace_id")
            return {
                "priority": priority,
                "trace_id": trace_id,
                "value": payload["value"],
            }

        message = {
            "payload": {"value": 42},
            "route": {"prev": [], "curr": "processor", "next": []},
            "headers": {"priority": "high", "trace_id": "xyz"},
        }

        responses = call_invoke(message, header_reader)

        assert len(responses) == 1
        assert responses[0]["payload"] == {"priority": "high", "trace_id": "xyz", "value": 42}
        # Headers preserved in output via VFS snapshot
        assert responses[0]["headers"] == {"priority": "high", "trace_id": "xyz"}

    def test_vfs_headers_writable(self):
        """Test that new headers can be added via VFS."""

        def header_writer(payload):
            asya_runtime._msg_vfs.write("headers/new-header", "added-value")
            return payload

        message = {
            "payload": {"test": True},
            "route": {"prev": [], "curr": "a", "next": []},
            "headers": {"existing": "kept"},
        }

        responses = call_invoke(message, header_writer)

        assert len(responses) == 1
        assert responses[0]["headers"]["existing"] == "kept"
        assert responses[0]["headers"]["new-header"] == "added-value"

    def test_vfs_headers_fanout_preserved(self):
        """Test that headers are preserved in fan-out via VFS."""

        def fanout_handler(payload):
            yield {"id": 1}
            yield {"id": 2}

        message = {
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "fan", "next": []},
            "headers": {"correlation_id": "abc"},
        }

        responses = call_invoke(message, fanout_handler)

        assert len(responses) == 2
        assert responses[0]["payload"] == {"id": 1}
        assert responses[0]["headers"] == {"correlation_id": "abc"}
        assert responses[1]["payload"] == {"id": 2}
        assert responses[1]["headers"] == {"correlation_id": "abc"}

    def test_vfs_missing_header_raises_file_not_found(self):
        """Test that reading a non-existent header raises FileNotFoundError."""

        def missing_header_reader(payload):
            asya_runtime._msg_vfs.read("headers/nonexistent")
            return payload

        message = {
            "payload": {"test": True},
            "route": {"prev": [], "curr": "a", "next": []},
            "headers": {},
        }

        responses = call_invoke(message, missing_header_reader)

        assert len(responses) == 1
        assert responses[0]["error"] == "processing_error"

    def test_vfs_handler_returns_none(self):
        """Test handler returning None aborts pipeline."""

        def none_handler(payload):
            return None

        message = {
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "processor", "next": []},
        }

        responses = call_invoke(message, none_handler)

        assert len(responses) == 0


class TestLoadFunctionErrors:
    """Test _load_function error handling."""

    def test_load_function_invalid_format_no_dot(self, mock_env):
        """Test loading function with invalid format (no dot separator)."""
        with mock_env(ASYA_HANDLER="invalid_no_dot"):
            with pytest.raises(SystemExit) as exc_info:
                asya_runtime._load_function()
            assert exc_info.value.code == 1

    def test_load_function_not_callable(self, mock_env, tmp_path):
        """Test loading non-callable attribute."""
        test_module = tmp_path / "test_module.py"
        test_module.write_text(
            textwrap.dedent("""
            NOT_A_FUNCTION = 'I am a string'
            """)
        )

        sys.path.insert(0, str(tmp_path))
        try:
            with mock_env(ASYA_HANDLER="test_module.NOT_A_FUNCTION"):
                with pytest.raises(SystemExit) as exc_info:
                    asya_runtime._load_function()
                assert exc_info.value.code == 1
        finally:
            sys.path.pop(0)

    def test_load_function_module_not_found(self, mock_env):
        """Test loading function from non-existent module."""
        with mock_env(ASYA_HANDLER="nonexistent_module.some_func"):
            with pytest.raises(SystemExit) as exc_info:
                asya_runtime._load_function()
            assert exc_info.value.code == 1

    def test_load_function_attribute_not_found(self, mock_env, tmp_path):
        """Test loading non-existent function from module."""
        test_module = tmp_path / "test_module2.py"
        test_module.write_text(
            textwrap.dedent("""
            def real_func(): pass
            """)
        )

        sys.path.insert(0, str(tmp_path))
        try:
            with mock_env(ASYA_HANDLER="test_module2.nonexistent_func"):
                with pytest.raises(SystemExit) as exc_info:
                    asya_runtime._load_function()
                assert exc_info.value.code == 1
        finally:
            sys.path.pop(0)


class TestSocketSetupErrors:
    """Test Unix HTTP server socket error handling."""

    def test_setup_socket_file_exists_and_is_directory(self, tmp_path):
        """Test socket setup when path exists as directory."""
        socket_path = tmp_path / "socket"
        socket_path.mkdir()

        with pytest.raises(OSError):
            asya_runtime._UnixHTTPServer(str(socket_path), asya_runtime._InvokeHandler)


class TestInvokeEdgeCases:
    """Test _handle_invoke edge cases."""

    def test_invoke_missing_payload_field_returns_400(self):
        """Test _handle_invoke returns 400 when message is missing payload."""

        def dummy_handler(payload):
            return {"result": "ok"}

        data = json.dumps(
            {
                "route": {"prev": [], "curr": "a", "next": []},
            }
        ).encode("utf-8")

        status_code, body = asya_runtime._handle_invoke(data, dummy_handler)
        assert status_code == 400
        parsed = json.loads(body)
        assert parsed["error"] == "msg_parsing_error"

    def test_invoke_missing_route_field_returns_400(self):
        """Test _handle_invoke returns 400 when message is missing route."""

        def dummy_handler(payload):
            return {"result": "ok"}

        data = json.dumps(
            {
                "payload": {"test": "data"},
            }
        ).encode("utf-8")

        status_code, body = asya_runtime._handle_invoke(data, dummy_handler)
        assert status_code == 400
        parsed = json.loads(body)
        assert parsed["error"] == "msg_parsing_error"


class TestCallHandler:
    """Test _call_handler() dispatch for sync and async functions."""

    def test_call_handler_sync_function(self):
        """Sync function is called directly without asyncio."""

        def sync_func(arg):
            return {"value": arg["x"] * 2}

        result = asya_runtime._call_handler(sync_func, {"x": 5})
        assert result == {"value": 10}

    def test_call_handler_async_function(self):
        """Async function is dispatched via asyncio.run()."""

        async def async_func(arg):
            return {"value": arg["x"] * 3}

        result = asya_runtime._call_handler(async_func, {"x": 5})
        assert result == {"value": 15}

    def test_call_handler_async_returning_none(self):
        """Async function returning None."""

        async def async_none(arg):
            return None

        result = asya_runtime._call_handler(async_none, {"x": 1})
        assert result is None

    def test_call_handler_async_returning_list(self):
        """Async function returning a list (fan-out)."""

        async def async_list(arg):
            return [{"i": 0}, {"i": 1}]

        result = asya_runtime._call_handler(async_list, {})
        assert result == [{"i": 0}, {"i": 1}]

    def test_call_handler_async_raising_exception(self):
        """Async function that raises is propagated."""

        async def async_error(arg):
            raise ValueError("async boom")

        with pytest.raises(ValueError, match="async boom"):
            asya_runtime._call_handler(async_error, {})

    def test_call_handler_sync_raising_exception(self):
        """Sync function that raises is propagated."""

        def sync_error(arg):
            raise RuntimeError("sync boom")

        with pytest.raises(RuntimeError, match="sync boom"):
            asya_runtime._call_handler(sync_error, {})


class TestAsyncHandlers:
    """Test async handler execution through _handle_invoke."""

    def test_async_payload_mode_basic(self):
        """Async handler in payload mode returns correct result."""

        async def async_echo(payload):
            return {"echoed": payload["msg"]}

        message = {
            "payload": {"msg": "hello"},
            "route": {"prev": [], "curr": "a", "next": []},
        }

        responses = call_invoke(message, async_echo)

        assert len(responses) == 1
        assert responses[0]["payload"] == {"echoed": "hello"}
        # Payload mode shifts route: "a" -> prev, curr becomes ""
        assert responses[0]["route"] == {"prev": ["a"], "curr": "", "next": []}

    def test_async_payload_mode_list_return(self):
        """Async handler returning list is treated as single payload (not fan-out)."""

        async def async_list_return(payload):
            return [{"i": 0}, {"i": 1}, {"i": 2}]

        message = {
            "payload": {"test": True},
            "route": {"prev": [], "curr": "a", "next": ["b"]},
        }

        responses = call_invoke(message, async_list_return)

        assert len(responses) == 1
        assert responses[0]["payload"] == [{"i": 0}, {"i": 1}, {"i": 2}]
        # Route shifts: "a" -> prev, curr becomes "b"
        assert responses[0]["route"] == {"prev": ["a"], "curr": "b", "next": []}

    def test_async_payload_mode_none_return(self):
        """Async handler returning None in payload mode aborts pipeline."""

        async def async_none(payload):
            return None

        message = {
            "payload": {"test": True},
            "route": {"prev": [], "curr": "a", "next": []},
        }

        responses = call_invoke(message, async_none)

        assert len(responses) == 0

    def test_async_vfs_header_access(self):
        """Async handler reads headers via VFS."""

        async def async_vfs_handler(payload):
            trace_id = asya_runtime._msg_vfs.read("headers/trace_id")
            return {"processed": payload["data"], "trace_id": trace_id}

        message = {
            "payload": {"data": "test"},
            "route": {"prev": [], "curr": "a", "next": ["b"]},
            "headers": {"trace_id": "t1"},
        }

        responses = call_invoke(message, async_vfs_handler)

        assert len(responses) == 1
        assert responses[0]["payload"] == {"processed": "test", "trace_id": "t1"}
        # Route shifts: "a" -> prev, curr becomes "b" (from next)
        assert responses[0]["route"] == {"prev": ["a"], "curr": "b", "next": []}
        assert responses[0]["headers"] == {"trace_id": "t1"}

    def test_async_handler_exception_produces_processing_error(self):
        """Async handler raising exception results in processing_error."""

        async def async_error(payload):
            raise ValueError("async handler failed")

        message = {
            "payload": {"test": True},
            "route": {"prev": [], "curr": "a", "next": []},
        }

        responses = call_invoke(message, async_error)

        assert len(responses) == 1
        assert responses[0]["error"] == "processing_error"
        assert "async handler failed" in responses[0]["details"]["message"]
        assert responses[0]["details"]["type"] == "ValueError"

    def test_sync_handler_still_works(self):
        """Sync handlers continue to work unchanged (regression test)."""

        def sync_handler(payload):
            return {"result": payload["value"] + 1}

        message = {
            "payload": {"value": 41},
            "route": {"prev": [], "curr": "a", "next": []},
        }

        responses = call_invoke(message, sync_handler)

        assert len(responses) == 1
        assert responses[0]["payload"] == {"result": 42}

    def test_async_class_method_handler(self):
        """Async class method handler works through _call_handler."""

        class AsyncProcessor:
            def __init__(self):
                self.count = 0

            async def process(self, payload):
                self.count += 1
                return {"count": self.count, "data": payload}

        processor = AsyncProcessor()

        message = {
            "payload": {"test": "data"},
            "route": {"prev": [], "curr": "a", "next": []},
        }

        responses = call_invoke(message, processor.process)

        assert len(responses) == 1
        assert responses[0]["payload"]["count"] == 1
        assert responses[0]["payload"]["data"] == {"test": "data"}

    def test_async_handler_preserves_headers(self):
        """Async handler in payload mode preserves headers."""

        async def async_handler(payload):
            return {"result": "ok"}

        message = {
            "payload": {"test": True},
            "route": {"prev": [], "curr": "a", "next": ["b"]},
            "headers": {"trace_id": "abc", "priority": "high"},
        }

        responses = call_invoke(message, async_handler)

        assert len(responses) == 1
        assert responses[0]["headers"] == {"trace_id": "abc", "priority": "high"}


class TestHTTPServer:
    """Test HTTP server infrastructure."""

    def test_server_binds_to_unix_socket(self, tmp_path):
        socket_path = str(tmp_path / "test.sock")
        server = asya_runtime._UnixHTTPServer(socket_path, asya_runtime._InvokeHandler)
        assert os.path.exists(socket_path)
        server.server_close()
        assert not os.path.exists(socket_path)

    def test_server_removes_existing_socket(self, tmp_path):
        socket_path = str(tmp_path / "test.sock")
        Path(socket_path).touch()
        server = asya_runtime._UnixHTTPServer(socket_path, asya_runtime._InvokeHandler)
        assert os.path.exists(socket_path)
        server.server_close()

    def test_server_chmod(self, tmp_path, mock_env):
        with mock_env(ASYA_SOCKET_CHMOD="0o600"):
            socket_path = str(tmp_path / "chmod.sock")
            server = asya_runtime._UnixHTTPServer(socket_path, asya_runtime._InvokeHandler)
            mode = os.stat(socket_path).st_mode & 0o777
            assert mode == 0o600
            server.server_close()


class TestHTTPInvoke:
    """Test POST /invoke endpoint via HTTP."""

    # --- Success (200) ---

    def test_payload_mode_success(self, runtime_invoke):
        def handler(payload):
            return {"result": payload["x"] + 1}

        message = {
            "payload": {"x": 10},
            "route": {"prev": [], "curr": "a", "next": ["b"]},
        }
        frames, status = runtime_invoke(handler, message)
        assert status == 200
        assert len(frames) == 1
        assert frames[0]["payload"] == {"result": 11}
        assert frames[0]["route"]["curr"] == "b"
        assert frames[0]["route"]["prev"] == ["a"]

    def test_payload_mode_preserves_headers(self, runtime_invoke):
        message = {
            "payload": {"x": 1},
            "route": {"prev": [], "curr": "a", "next": ["b"]},
            "headers": {"trace_id": "abc-123"},
        }
        frames, status = runtime_invoke(lambda p: {"ok": True}, message)
        assert status == 200
        assert frames[0]["headers"] == {"trace_id": "abc-123"}

    def test_payload_mode_preserves_status(self, runtime_invoke):
        message = {
            "payload": {},
            "route": {"prev": [], "curr": "a", "next": []},
            "status": {"phase": "working"},
        }
        frames, status = runtime_invoke(lambda p: {"ok": True}, message)
        assert status == 200
        assert frames[0]["status"] == {"phase": "working"}

    def test_async_handler(self, runtime_invoke):
        async def handler(payload):
            return {"async": True}

        message = {"payload": {}, "route": {"prev": [], "curr": "a", "next": []}}
        frames, status = runtime_invoke(handler, message)
        assert status == 200
        assert frames[0]["payload"] == {"async": True}

    # --- Abort (204) ---

    def test_handler_returns_none_204(self, runtime_invoke):
        message = {"payload": {}, "route": {"prev": [], "curr": "a", "next": []}}
        frames, status = runtime_invoke(lambda p: None, message)
        assert status == 204
        assert frames == []

    # --- Handler error (500) ---

    def test_handler_exception_500(self, runtime_invoke):
        def bad_handler(payload):
            raise ValueError("something broke")

        message = {"payload": {}, "route": {"prev": [], "curr": "a", "next": []}}
        error, status = runtime_invoke(bad_handler, message)
        assert status == 500
        assert error["error"] == "processing_error"
        assert "something broke" in error["details"]["message"]
        assert error["details"]["type"] == "ValueError"

    # --- Parse error (400) ---

    def test_missing_payload_400(self, runtime_invoke):
        message = {"route": {"prev": [], "curr": "a", "next": []}}
        error, status = runtime_invoke(lambda p: p, message)
        assert status == 400
        assert error["error"] == "msg_parsing_error"

    def test_missing_route_400(self, runtime_invoke):
        message = {"payload": {"x": 1}}
        error, status = runtime_invoke(lambda p: p, message)
        assert status == 400
        assert error["error"] == "msg_parsing_error"

    # --- Generators (collected into frames array) ---

    def test_generator_fanout(self, runtime_invoke):
        def gen(payload):
            yield {"id": 1}
            yield {"id": 2}
            yield {"id": 3}

        message = {"payload": {}, "route": {"prev": [], "curr": "a", "next": ["b"]}}
        frames, status = runtime_invoke(gen, message)
        assert status == 200
        assert len(frames) == 3
        assert [f["payload"]["id"] for f in frames] == [1, 2, 3]
        assert all(f["route"]["curr"] == "b" for f in frames)

    def test_generator_yields_nothing_204(self, runtime_invoke):
        # A proper generator that immediately returns without yielding any values
        def empty_gen(payload):
            yield from []

        message = {"payload": {}, "route": {"prev": [], "curr": "a", "next": []}}
        frames, status = runtime_invoke(empty_gen, message)
        assert status == 204

    # --- VFS access via handler ---

    def test_vfs_id_access_success(self, runtime_invoke):
        def handler(payload):
            msg_id = asya_runtime._msg_vfs.read("id")
            return {"processed": True, "id_seen": msg_id}

        message = {"id": "test-msg-id", "payload": {"x": 1}, "route": {"prev": [], "curr": "a", "next": []}}
        frames, status = runtime_invoke(handler, message)
        assert status == 200
        assert frames[0]["payload"]["processed"] is True
        assert frames[0]["payload"]["id_seen"] == "test-msg-id"

    def test_vfs_handler_returns_none(self, runtime_invoke):
        message = {"payload": {}, "route": {"prev": [], "curr": "a", "next": []}}
        frames, status = runtime_invoke(lambda p: None, message)
        assert status == 204

    def test_vfs_generator_handler(self, runtime_invoke):
        def gen(payload):
            for i in range(2):
                yield {"i": i}

        message = {"payload": {}, "route": {"prev": [], "curr": "a", "next": []}}
        frames, status = runtime_invoke(gen, message)
        assert status == 200
        assert len(frames) == 2
        assert frames[0]["payload"]["i"] == 0
        assert frames[1]["payload"]["i"] == 1

    # --- Large payloads ---

    @pytest.mark.parametrize("size_kb", [10, 100, 500, 1024])
    def test_large_payloads(self, runtime_invoke, size_kb):
        large_data = "X" * (size_kb * 1024)
        message = {
            "payload": {"data": large_data},
            "route": {"prev": [], "curr": "a", "next": []},
        }
        frames, status = runtime_invoke(lambda p: p, message)
        assert status == 200
        assert len(frames[0]["payload"]["data"]) == size_kb * 1024

    # --- 404 ---

    def test_wrong_path_404(self, tmp_path):
        socket_path = str(tmp_path / "test.sock")
        server = asya_runtime._UnixHTTPServer(socket_path, asya_runtime._InvokeHandler)
        server.user_func = lambda p: p
        thread = threading.Thread(target=server.handle_request)
        thread.start()

        conn = _UnixHTTPConnection(socket_path)
        conn.request("POST", "/health")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        thread.join(timeout=5)
        server.server_close()
        assert resp.status == 404


class TestHTTPHealthz:
    """Test GET /healthz endpoint."""

    def _make_get_request(self, tmp_path, path):
        socket_path = str(tmp_path / "healthz.sock")
        server = asya_runtime._UnixHTTPServer(socket_path, asya_runtime._InvokeHandler)
        server.user_func = lambda p: p
        thread = threading.Thread(target=server.handle_request)
        thread.start()

        conn = _UnixHTTPConnection(socket_path)
        conn.request("GET", path)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        thread.join(timeout=5)
        server.server_close()
        return resp.status, raw

    def test_healthz_returns_200_with_ready_status(self, tmp_path):
        status, raw = self._make_get_request(tmp_path, "/healthz")
        assert status == 200
        data = json.loads(raw)
        assert data == {"status": "ready"}

    def test_healthz_unknown_path_returns_404(self, tmp_path):
        status, _ = self._make_get_request(tmp_path, "/unknown")
        assert status == 404
