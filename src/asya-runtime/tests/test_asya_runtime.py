#!/usr/bin/env python3
"""Tests for asya_runtime.py HTTP server."""

import http.client as http_client
import importlib
import json
import os
import socket
import sys
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
            with mock_env(ASYA_HANDLER_MODE="envelope", ASYA_SOCKET_CHMOD="0o600"):
                # asya_runtime module is reloaded with new env vars
                assert asya_runtime.ASYA_HANDLER_MODE == "envelope"

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


@pytest.fixture
def runtime_invoke(tmp_path):
    """Invoke a handler via HTTP runtime server and return (frames_or_error, status_code).

    Returns:
        For 200: (list[dict], 200) — list of response frames
        For 204: ([], 204) — abort (handler returned None)
        For 4xx/5xx: (dict, status) — error response body
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

    def test_handler_returns_string_payload_mode(self, runtime_invoke):
        """Test handler returning string instead of dict in payload mode."""

        def string_handler(payload):
            return "this is a string, not a dict"

        message = {
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
        }
        frames, status = runtime_invoke(string_handler, message)

        assert status == 200
        assert len(frames) == 1
        assert frames[0]["payload"] == "this is a string, not a dict"

    def test_handler_returns_number_payload_mode(self, runtime_invoke):
        """Test handler returning number in payload mode."""

        def number_handler(payload):
            return 42

        message = {
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
        }
        frames, status = runtime_invoke(number_handler, message)

        assert status == 200
        assert len(frames) == 1
        assert frames[0]["payload"] == 42

    def test_handler_returns_none_payload_mode(self, runtime_invoke):
        """Test handler returning None in payload mode (abort execution)."""

        def none_handler(payload):
            return None

        message = {
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
        }
        frames, status = runtime_invoke(none_handler, message)

        assert status == 204
        assert frames == []

    def test_handler_returns_empty_list(self, runtime_invoke):
        """Test handler returning empty list (returns list as single payload)."""

        def empty_list_handler(payload):
            return []

        message = {
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
        }
        frames, status = runtime_invoke(empty_list_handler, message)

        assert status == 200
        assert len(frames) == 1
        assert frames[0]["payload"] == []


class TestRouteValidation:
    """Test route validation edge cases."""

    def test_parse_msg_route_current_missing_defaults_to_zero(self):
        """Test route without current field - should default to 0."""
        data = json.dumps({"payload": {"test": "data"}, "route": {"actors": ["a", "b"]}}).encode("utf-8")
        msg = asya_runtime._parse_message_json(data)
        validated = asya_runtime._validate_message(msg)

        assert validated["route"]["current"] == 0
        assert validated["route"]["actors"] == ["a", "b"]

    def test_parse_msg_route_not_dict(self):
        """Test route as string instead of dict - should fail validation."""
        with pytest.raises(ValueError, match="Field 'route' must be a dict"):
            data = json.dumps({"payload": {"test": "data"}, "route": "not a dict"}).encode("utf-8")
            msg = asya_runtime._parse_message_json(data)
            asya_runtime._validate_message(msg)

    def test_parse_msg_route_missing_actors(self):
        """Test route without actors field - should fail validation."""
        with pytest.raises(ValueError, match="Missing required field 'actors' in route"):
            data = json.dumps({"payload": {"test": "data"}, "route": {"current": 0}}).encode("utf-8")
            msg = asya_runtime._parse_message_json(data)
            asya_runtime._validate_message(msg)

    def test_parse_msg_route_actors_not_list(self):
        """Test route with actors as non-list - should fail validation."""
        with pytest.raises(ValueError, match="Field 'route.actors' must be a list"):
            data = json.dumps({"payload": {"test": "data"}, "route": {"actors": "not a list"}}).encode("utf-8")
            msg = asya_runtime._parse_message_json(data)
            asya_runtime._validate_message(msg)

    def test_parse_msg_route_current_not_int(self):
        """Test route with current as non-integer - should fail validation."""
        with pytest.raises(ValueError, match="Field 'route.current' must be an integer"):
            data = json.dumps(
                {
                    "payload": {"test": "data"},
                    "route": {"actors": ["a", "b"], "current": "0"},
                }
            ).encode("utf-8")
            msg = asya_runtime._parse_message_json(data)
            asya_runtime._validate_message(msg)

    def test_parse_msg_route_current_negative(self):
        """Test route with negative current index - should fail validation."""
        with pytest.raises(ValueError, match="Invalid route.current=-1"):
            data = json.dumps({"payload": {"test": "data"}, "route": {"actors": ["a"], "current": -1}}).encode("utf-8")
            msg = asya_runtime._parse_message_json(data)
            asya_runtime._validate_message(msg)

    def test_parse_msg_route_current_out_of_bounds(self):
        """Test route with current index beyond actors length - should fail validation."""
        with pytest.raises(ValueError, match="Invalid route.current=10"):
            data = json.dumps(
                {
                    "payload": {"test": "data"},
                    "route": {"actors": ["a", "b"], "current": 10},
                }
            ).encode("utf-8")
            msg = asya_runtime._parse_message_json(data)
            asya_runtime._validate_message(msg)

    def test_parse_msg_route_empty_actors_current_zero(self):
        """Test route with empty actors array and current=0 - should fail validation."""
        with pytest.raises(ValueError, match="Field 'route.actors' cannot be empty"):
            data = json.dumps({"payload": {"test": "data"}, "route": {"actors": [], "current": 0}}).encode("utf-8")
            msg = asya_runtime._parse_message_json(data)
            asya_runtime._validate_message(msg)


class TestMessageFieldPreservation:
    """Test that message fields are properly preserved through validation."""

    def test_validate_message_preserves_id_field(self):
        """Test that id field is preserved through validation."""
        message = {
            "id": "envelope-123",
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
        }
        validated = asya_runtime._validate_message(message)

        assert validated["id"] == "envelope-123"
        assert validated["payload"] == {"test": "data"}
        assert validated["route"] == {"actors": ["a"], "current": 0}

    def test_validate_message_preserves_parent_id_field(self):
        """Test that parent_id field is preserved through validation."""
        message = {
            "id": "envelope-456",
            "parent_id": "parent-envelope-123",
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
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
            "route": {"actors": ["a", "b"], "current": 0},
            "headers": {"trace_id": "trace-123", "priority": "high"},
        }
        validated = asya_runtime._validate_message(message)

        assert validated["id"] == "envelope-789"
        assert validated["parent_id"] == "parent-envelope-456"
        assert validated["payload"] == {"test": "data"}
        assert validated["route"] == {"actors": ["a", "b"], "current": 0}
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
            "route": {"actors": ["a", "b"], "current": 0},
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
            "route": {"actors": ["a"], "current": 0},
        }
        validated = asya_runtime._validate_message(message)

        assert "status" not in validated

    def test_validate_message_without_id_field(self):
        """Test that message without id field still validates (id is optional)."""
        message = {
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
        }
        validated = asya_runtime._validate_message(message)

        assert "id" not in validated
        assert validated["payload"] == {"test": "data"}

    def test_validate_message_id_field_invalid_type(self):
        """Test that id field with non-string type fails validation."""
        message = {
            "id": 12345,
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
        }
        with pytest.raises(ValueError, match="Field 'id' must be a string"):
            asya_runtime._validate_message(message)

    def test_envelope_mode_handler_accesses_id_field(self, runtime_invoke, mock_env):
        """Test that envelope mode handlers can access message id field."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def envelope_handler(msg):
                message_id = msg["id"]
                return {
                    "id": message_id,
                    "payload": {"message_id": message_id, "data": msg["payload"]},
                    "route": msg["route"],
                }

            message = {
                "id": "test-envelope-123",
                "payload": {"value": 42},
                "route": {"actors": ["a"], "current": 0},
            }
            frames, status = runtime_invoke(envelope_handler, message)

            assert status == 200
            assert len(frames) == 1
            assert frames[0]["id"] == "test-envelope-123"
            assert frames[0]["payload"]["message_id"] == "test-envelope-123"


class TestEnvelopeModeValidation:
    """Test envelope mode validation edge cases."""

    def test_handler_returns_invalid_payload_type_in_message(self, runtime_invoke, mock_env):
        """Test handler returns message with payload as string instead of dict."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def invalid_handler(msg):
                return {"payload": "not a dict", "route": msg["route"]}

            message = {
                "payload": {"test": "data"},
                "route": {"actors": ["a"], "current": 0},
            }
            frames, status = runtime_invoke(invalid_handler, message)

            assert status == 200
            assert len(frames) == 1
            assert frames[0]["payload"] == "not a dict"

    def test_handler_returns_invalid_route_type_in_message(self, runtime_invoke, mock_env):
        """Test handler returns message with route as wrong type."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def invalid_handler(msg):
                return {"payload": {"ok": True}, "route": "invalid"}

            message = {
                "payload": {"test": "data"},
                "route": {"actors": ["a"], "current": 0},
            }
            error, status = runtime_invoke(invalid_handler, message)

            assert status == 500
            assert error["error"] == "processing_error"
            assert "Field 'route' must be a dict" in error["details"]["message"]

    def test_handler_yields_valid_then_invalid_message(self, runtime_invoke, mock_env):
        """Test generator handler yields one valid and one invalid envelope.

        With HTTP, frames are collected before responding, so the validation
        error on the second yield causes the entire request to fail with 500.
        """
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def mixed_handler(msg):
                yield {"payload": {"id": 1}, "route": msg["route"]}
                yield {"payload": {"id": 2}}  # Missing 'route'

            message = {
                "payload": {"test": "data"},
                "route": {"actors": ["a"], "current": 0},
            }
            error, status = runtime_invoke(mixed_handler, message)

            assert status == 500
            assert error["error"] == "processing_error"
            assert "Missing required field 'route'" in error["details"]["message"]

    def test_handler_changes_current_actor(self, runtime_invoke, mock_env):
        """Test that handler cannot change actor name at the current position."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def actor_changing_handler(msg):
                return {
                    "payload": msg["payload"],
                    "route": {"actors": ["x", "b", "c"], "current": 0},
                }

            message = {
                "payload": {"test": "data"},
                "route": {"actors": ["a", "b", "c"], "current": 0},
            }
            error, status = runtime_invoke(actor_changing_handler, message)

            assert status == 500
            assert error["error"] == "processing_error"
            assert "Route" in error["details"]["message"] and (
                "modification" in error["details"]["message"] or "mismatch" in error["details"]["message"]
            )
            assert "'a'" in error["details"]["message"]
            assert "'x'" in error["details"]["message"] or "['x']" in error["details"]["message"]

    def test_handler_modifies_route_but_keeps_current_actor(self, runtime_invoke, mock_env):
        """Test that handler can modify route actors as long as current actor stays same."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def route_modifying_handler(msg):
                return {
                    "payload": msg["payload"],
                    "route": {"actors": ["a", "b", "c", "d"], "current": 0},
                }

            message = {
                "payload": {"test": "data"},
                "route": {"actors": ["a", "b"], "current": 0},
            }
            frames, status = runtime_invoke(route_modifying_handler, message)

            assert status == 200
            assert len(frames) == 1
            assert frames[0]["route"]["actors"] == ["a", "b", "c", "d"]
            assert frames[0]["route"]["current"] == 0

    def test_handler_fanout_with_actor_validation(self, runtime_invoke, mock_env):
        """Test fan-out where all output messages maintain correct current actor."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def fanout_handler(msg):
                yield {"payload": {"id": 1}, "route": {"actors": ["a", "b"], "current": 0}}
                yield {"payload": {"id": 2}, "route": {"actors": ["a", "b"], "current": 0}}
                yield {"payload": {"id": 3}, "route": {"actors": ["a", "c"], "current": 0}}

            message = {
                "payload": {"test": "data"},
                "route": {"actors": ["a", "b"], "current": 0},
            }
            frames, status = runtime_invoke(fanout_handler, message)

            assert status == 200
            assert len(frames) == 3
            assert frames[0]["payload"] == {"id": 1}
            assert frames[1]["payload"] == {"id": 2}
            assert frames[2]["payload"] == {"id": 3}

    def test_handler_fanout_with_invalid_actor_name(self, runtime_invoke, mock_env):
        """Test fan-out where one message has changed actor name at current position.

        With HTTP, the validation error on the second yield causes the
        entire request to fail with 500.
        """
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def invalid_fanout_handler(msg):
                yield {"payload": {"id": 1}, "route": {"actors": ["a", "b"], "current": 0}}
                yield {"payload": {"id": 2}, "route": {"actors": ["x", "b"], "current": 0}}

            message = {
                "payload": {"test": "data"},
                "route": {"actors": ["a", "b"], "current": 0},
            }
            error, status = runtime_invoke(invalid_fanout_handler, message)

            assert status == 500
            assert error["error"] == "processing_error"

    def test_handler_erases_processed_actors_first_actor(self, runtime_invoke, mock_env):
        """Test that handler cannot erase already-processed actors at first actor."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def erasing_handler(msg):
                return {
                    "payload": msg["payload"],
                    "route": {"actors": ["x", "a", "b"], "current": 1},
                }

            message = {
                "payload": {"test": "data"},
                "route": {"actors": ["a", "b", "c"], "current": 0},
            }
            error, status = runtime_invoke(erasing_handler, message)

            assert status == 500
            assert error["error"] == "processing_error"
            assert "Route modification error" in error["details"]["message"]
            assert "already-processed actors cannot be erased" in error["details"]["message"]

    def test_handler_erases_processed_actors_middle(self, runtime_invoke, mock_env):
        """Test that handler cannot erase already-processed actors in the middle."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def erasing_handler(msg):
                return {
                    "payload": msg["payload"],
                    "route": {"actors": ["a", "c", "d"], "current": 2},
                }

            message = {
                "payload": {"test": "data"},
                "route": {"actors": ["a", "b", "c"], "current": 2},
            }
            error, status = runtime_invoke(erasing_handler, message)

            assert status == 500
            assert error["error"] == "processing_error"
            assert "Route modification error" in error["details"]["message"]
            assert "['a', 'b', 'c']" in error["details"]["message"]

    def test_handler_modifies_one_processed_actor(self, runtime_invoke, mock_env):
        """Test that handler cannot modify an already-processed actor name."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def modifying_handler(msg):
                return {
                    "payload": msg["payload"],
                    "route": {"actors": ["a-modified", "b", "c", "d"], "current": 1},
                }

            message = {
                "payload": {"test": "data"},
                "route": {"actors": ["a", "b", "c"], "current": 1},
            }
            error, status = runtime_invoke(modifying_handler, message)

            assert status == 500
            assert error["error"] == "processing_error"
            assert "Route modification error" in error["details"]["message"]

    def test_handler_adds_future_actors_preserves_prefix(self, runtime_invoke, mock_env):
        """Test that handler CAN add future actors if prefix is preserved."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def extending_handler(msg):
                return {
                    "payload": msg["payload"],
                    "route": {"actors": ["a", "b", "c", "d", "e"], "current": 1},
                }

            message = {
                "payload": {"test": "data"},
                "route": {"actors": ["a", "b", "c"], "current": 1},
            }
            frames, status = runtime_invoke(extending_handler, message)

            assert status == 200
            assert len(frames) == 1
            assert frames[0]["route"]["actors"] == ["a", "b", "c", "d", "e"]
            assert frames[0]["route"]["current"] == 1

    def test_handler_replaces_future_actors(self, runtime_invoke, mock_env):
        """Test that handler CAN replace future actors (after current)."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def replacing_handler(msg):
                return {
                    "payload": msg["payload"],
                    "route": {"actors": ["a", "b", "x", "y"], "current": 1},
                }

            message = {
                "payload": {"test": "data"},
                "route": {"actors": ["a", "b", "c", "d"], "current": 1},
            }
            frames, status = runtime_invoke(replacing_handler, message)

            assert status == 200
            assert len(frames) == 1
            assert frames[0]["route"]["actors"] == ["a", "b", "x", "y"]
            assert frames[0]["route"]["current"] == 1


class TestLargePayloads:
    """Test handling of large payloads."""

    @pytest.mark.parametrize("size_kb", [10, 100, 500, 1024, 5 * 1024, 10 * 1024])
    def test_large_payloads(self, runtime_invoke, size_kb):
        """Test various payload sizes from KB to MB."""

        def echo_handler(payload):
            return payload

        large_data = "X" * (size_kb * 1024)
        message = {
            "payload": {"data": large_data},
            "route": {"actors": ["a"], "current": 0},
        }
        frames, status = runtime_invoke(echo_handler, message)

        assert status == 200
        assert len(frames) == 1
        assert len(frames[0]["payload"]["data"]) == size_kb * 1024

    def test_empty_body_returns_400(self, tmp_path):
        """Test empty HTTP body returns 400."""
        socket_path = str(tmp_path / "test.sock")
        server = asya_runtime._UnixHTTPServer(socket_path, asya_runtime._InvokeHandler)
        server.user_func = lambda p: p
        thread = threading.Thread(target=server.handle_request)
        thread.start()

        conn = _UnixHTTPConnection(socket_path)
        conn.request("POST", "/invoke", body=b"", headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        status = resp.status
        raw = resp.read()
        conn.close()
        thread.join(timeout=5)
        server.server_close()

        assert status == 400
        data = json.loads(raw)
        assert data["error"] == "msg_parsing_error"


class TestConfigFixtures:
    """Test configuration fixture patterns."""

    def test_mock_env_fixture_basic(self, mock_env):
        """Test mock_env fixture with basic config override."""
        original_value = asya_runtime.ASYA_HANDLER_MODE
        assert original_value == asya_runtime.ASYA_HANDLER_MODE

        with mock_env(ASYA_HANDLER_MODE="envelope"):
            assert asya_runtime.ASYA_HANDLER_MODE == "envelope"

        assert original_value == asya_runtime.ASYA_HANDLER_MODE

    def test_mock_env_fixture_multiple_vars(self, mock_env):
        """Test mock_env fixture with multiple env vars."""
        with mock_env(
            ASYA_HANDLER_MODE="envelope",
            ASYA_SOCKET_CHMOD="0o600",
        ):
            assert asya_runtime.ASYA_HANDLER_MODE == "envelope"
            assert asya_runtime.ASYA_SOCKET_CHMOD == "0o600"


class TestParseMsg:
    """Test _parse_message_json and _validate_message functions."""

    def test_parse_msg_with_payload_and_route(self):
        """Test parsing message with both payload and route."""
        data = json.dumps({"payload": {"test": "data"}, "route": {"actors": ["a", "b"], "current": 0}}).encode("utf-8")

        msg = asya_runtime._parse_message_json(data)
        msg = asya_runtime._validate_message(msg)

        assert msg["payload"] == {"test": "data"}
        assert msg["route"] == {"actors": ["a", "b"], "current": 0}

    def test_parse_msg_missing_payload(self):
        """Test parsing message without payload field."""
        with pytest.raises(ValueError, match="Missing required .*payload"):
            data = json.dumps({"route": {"actors": ["a"], "current": 0}}).encode("utf-8")
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
        data = json.dumps({"payload": payload, "route": {"actors": ["a"], "current": 0}}).encode("utf-8")

        msg = asya_runtime._parse_message_json(data)
        msg = asya_runtime._validate_message(msg)

        assert msg["payload"] == payload
        assert msg["route"] == {"actors": ["a"], "current": 0}

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
    """Test POST /invoke in payload mode (ASYA_HANDLER_MODE=payload)."""

    def test_handle_request_success_single_output(self, runtime_invoke, mock_env):
        """Test successful request with single output."""
        with mock_env(ASYA_HANDLER_MODE="payload"):

            def simple_handler(payload):
                return {"result": payload["value"] * 2}

            message = {
                "route": {"actors": ["actor1"], "current": 0},
                "payload": {"value": 42},
            }
            frames, status = runtime_invoke(simple_handler, message)

            assert status == 200
            assert len(frames) == 1
            assert frames[0]["payload"] == {"result": 84}
            assert frames[0]["route"] == {"actors": ["actor1"], "current": 1}

    def test_handle_request_multi_actor_route(self, runtime_invoke, mock_env):
        """Test that payload mode increments current for multi-actor pipelines."""
        with mock_env(ASYA_HANDLER_MODE="payload"):

            def pipeline_handler(payload):
                return {"doubled": payload["value"] * 2}

            message = {
                "route": {"actors": ["doubler", "incrementer", "finalizer"], "current": 0},
                "payload": {"value": 21},
            }
            frames, status = runtime_invoke(pipeline_handler, message)

            assert status == 200
            assert len(frames) == 1
            assert frames[0]["payload"] == {"doubled": 42}
            assert frames[0]["route"]["current"] == 1
            assert frames[0]["route"]["actors"] == ["doubler", "incrementer", "finalizer"]

    def test_handle_request_fanout_list_output(self, runtime_invoke, mock_env):
        """Test fan-out with list output in payload mode."""
        with mock_env(ASYA_HANDLER_MODE="payload"):

            def fanout_handler(payload):
                yield {"id": 1}
                yield {"id": 2}
                yield {"id": 3}

            message = {
                "route": {"actors": ["fan"], "current": 0},
                "payload": {"test": "data"},
            }
            frames, status = runtime_invoke(fanout_handler, message)

            assert status == 200
            assert len(frames) == 3
            assert frames[0]["payload"] == {"id": 1}
            assert frames[1]["payload"] == {"id": 2}
            assert frames[2]["payload"] == {"id": 3}
            for frame in frames:
                assert frame["route"] == {"actors": ["fan"], "current": 1}


class TestHandleRequestEnvelopeMode:
    """Test POST /invoke in envelope mode (ASYA_HANDLER_MODE=envelope)."""

    def test_handle_request_success_single_output(self, runtime_invoke, mock_env):
        """Test successful request with single output in envelope mode."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def envelope_handler(msg):
                return {
                    "payload": {"result": msg["payload"]["value"] * 2},
                    "route": msg["route"],
                }

            message = {
                "route": {"actors": ["actor1"], "current": 0},
                "payload": {"value": 42},
            }
            frames, status = runtime_invoke(envelope_handler, message)

            assert status == 200
            assert len(frames) == 1
            assert frames[0]["payload"] == {"result": 84}
            assert frames[0]["route"] == {"actors": ["actor1"], "current": 0}

    def test_handle_request_route_modification(self, runtime_invoke, mock_env):
        """Test that handler can modify route in envelope mode."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def route_modifying_handler(msg):
                new_route = msg["route"].copy()
                new_route["actors"] = msg["route"]["actors"] + ["modified"]
                new_route["current"] = 0
                return {"payload": msg["payload"], "route": new_route}

            message = {
                "route": {"actors": ["actor1"], "current": 0},
                "payload": {"data": "test"},
            }
            frames, status = runtime_invoke(route_modifying_handler, message)

            assert status == 200
            assert len(frames) == 1
            assert frames[0]["route"]["actors"] == ["actor1", "modified"]
            assert frames[0]["route"]["current"] == 0

    def test_handle_request_fanout_list_output(self, runtime_invoke, mock_env):
        """Test fan-out with list output in envelope mode."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def fanout_handler(msg):
                yield {"payload": {"id": 1}, "route": msg["route"]}
                yield {"payload": {"id": 2}, "route": msg["route"]}
                yield {"payload": {"id": 3}, "route": msg["route"]}

            message = {
                "route": {"actors": ["fan"], "current": 0},
                "payload": {"test": "data"},
            }
            frames, status = runtime_invoke(fanout_handler, message)

            assert status == 200
            assert len(frames) == 3
            assert frames[0]["payload"] == {"id": 1}
            assert frames[1]["payload"] == {"id": 2}
            assert frames[2]["payload"] == {"id": 3}

    def test_handle_request_invalid_output_missing_keys(self, runtime_invoke, mock_env):
        """Test that handler output is validated for required keys."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def invalid_handler(msg):
                return {"payload": {"test": "data"}}

            message = {
                "route": {"actors": ["actor1"], "current": 0},
                "payload": {"test": "data"},
            }
            error, status = runtime_invoke(invalid_handler, message)

            assert status == 500
            assert error["error"] == "processing_error"
            assert "Missing required field 'route'" in error["details"]["message"]

    def test_handle_request_invalid_output_list_missing_keys(self, runtime_invoke, mock_env):
        """Test that handler list output is validated for required keys.

        With HTTP, the validation error on the second yield causes the
        entire request to fail with 500.
        """
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def invalid_fanout_handler(msg):
                yield {"payload": {"id": 1}, "route": msg["route"]}
                yield {"payload": {"id": 2}}  # Missing 'route'

            message = {
                "route": {"actors": ["actor1"], "current": 0},
                "payload": {"test": "data"},
            }
            error, status = runtime_invoke(invalid_fanout_handler, message)

            assert status == 500
            assert error["error"] == "processing_error"
            assert "Missing required field 'route'" in error["details"]["message"]


class TestHandleRequestErrorCases:
    """Test error handling in POST /invoke."""

    def test_handle_request_invalid_json(self, tmp_path):
        """Test handling of invalid JSON."""
        socket_path = str(tmp_path / "test.sock")
        server = asya_runtime._UnixHTTPServer(socket_path, asya_runtime._InvokeHandler)
        server.user_func = lambda p: p
        thread = threading.Thread(target=server.handle_request)
        thread.start()

        conn = _UnixHTTPConnection(socket_path)
        conn.request(
            "POST",
            "/invoke",
            body=b"not valid json{",
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        status = resp.status
        raw = resp.read()
        conn.close()
        thread.join(timeout=5)
        server.server_close()

        assert status == 400
        data = json.loads(raw)
        assert data["error"] == "msg_parsing_error"
        assert "details" in data

    def test_handle_request_handler_exception(self, runtime_invoke):
        """Test handling of handler exceptions."""

        def failing_handler(payload):
            raise ValueError("Handler failed")

        message = {
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
        }
        error, status = runtime_invoke(failing_handler, message)

        assert status == 500
        assert error["error"] == "processing_error"
        assert error["details"]["message"] == "Handler failed"
        assert error["details"]["type"] == "ValueError"

    def test_handle_request_invalid_handler_mode(self, runtime_invoke, mock_env):
        """Test handling when ASYA_HANDLER_MODE is invalid."""

        def simple_handler(payload):
            return payload

        message = {
            "route": {"actors": ["actor1"], "current": 0},
            "payload": {"test": "data"},
        }

        with mock_env(ASYA_HANDLER_MODE="unexpected-value"):
            error, status = runtime_invoke(simple_handler, message)

            assert status == 500
            assert error["error"] == "processing_error"


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

    def test_class_handler_state_preserved_across_calls(self, runtime_invoke, mock_env, tmp_path):
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

                message1 = {
                    "payload": {"value": 10},
                    "route": {"actors": ["a"], "current": 0},
                }
                frames1, status1 = runtime_invoke(handler, message1)

                assert status1 == 200
                assert len(frames1) == 1
                assert frames1[0]["payload"]["calls"] == 1
                assert frames1[0]["payload"]["total"] == 10

                message2 = {
                    "payload": {"value": 20},
                    "route": {"actors": ["a"], "current": 0},
                }
                frames2, status2 = runtime_invoke(handler, message2)

                assert status2 == 200
                assert len(frames2) == 1
                assert frames2[0]["payload"]["calls"] == 2
                assert frames2[0]["payload"]["total"] == 30

        finally:
            sys.path.pop(0)

    def test_class_handler_payload_mode(self, runtime_invoke, mock_env, tmp_path):
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
            with mock_env(ASYA_HANDLER="payload_class.PayloadProcessor.process", ASYA_HANDLER_MODE="payload"):
                handler = asya_runtime._load_function()

                message = {
                    "payload": {"value": 21},
                    "route": {"actors": ["a"], "current": 0},
                }
                frames, status = runtime_invoke(handler, message)

                assert status == 200
                assert len(frames) == 1
                assert frames[0]["payload"]["result"] == 42

        finally:
            sys.path.pop(0)

    def test_class_handler_envelope_mode(self, runtime_invoke, mock_env, tmp_path):
        """Test class handler in envelope mode."""
        test_module = tmp_path / "envelope_class.py"
        test_module.write_text(
            textwrap.dedent("""
            class EnvelopeProcessor:
                def __init__(self):
                    self.prefix = "processed"

                def process(self, msg):
                    return {
                        "payload": {"prefix": self.prefix, "data": msg["payload"]},
                        "route": msg["route"],
                        "headers": msg.get("headers", {}),
                    }
            """)
        )

        sys.path.insert(0, str(tmp_path))
        try:
            with mock_env(ASYA_HANDLER="envelope_class.EnvelopeProcessor.process", ASYA_HANDLER_MODE="envelope"):
                handler = asya_runtime._load_function()

                message = {
                    "payload": {"value": 100},
                    "route": {"actors": ["a"], "current": 0},
                    "headers": {"trace_id": "123"},
                }
                frames, status = runtime_invoke(handler, message)

                assert status == 200
                assert len(frames) == 1
                assert frames[0]["payload"]["prefix"] == "processed"
                assert frames[0]["payload"]["data"]["value"] == 100
                assert frames[0]["headers"]["trace_id"] == "123"

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
                    self.process = "not a method"
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

    def test_class_handler_fanout_payload_mode(self, runtime_invoke, mock_env, tmp_path):
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
                    "route": {"actors": ["fan"], "current": 0},
                }
                frames, status = runtime_invoke(handler, message)

                assert status == 200
                assert len(frames) == 3
                assert frames[0]["payload"]["id"] == 0
                assert frames[1]["payload"]["id"] == 1
                assert frames[2]["payload"]["id"] == 2

        finally:
            sys.path.pop(0)

    def test_class_handler_returns_none(self, runtime_invoke, mock_env, tmp_path):
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
                    "route": {"actors": ["a"], "current": 0},
                }
                frames, status = runtime_invoke(handler, message)

                assert status == 204
                assert frames == []

        finally:
            sys.path.pop(0)

    def test_class_handler_validation_disabled(self, runtime_invoke, mock_env, tmp_path):
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
                    "route": {"actors": ["a"], "current": 0},
                }
                frames, status = runtime_invoke(handler, message)

                assert status == 200
                assert len(frames) == 1
                assert frames[0]["payload"]["result"] == 123

        finally:
            sys.path.pop(0)

    def test_class_handler_with_complex_state(self, runtime_invoke, mock_env, tmp_path):
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

                message1 = {
                    "payload": {"value": 100},
                    "route": {"actors": ["a"], "current": 0},
                }
                frames1, status1 = runtime_invoke(handler, message1)

                assert status1 == 200
                assert frames1[0]["payload"]["stats"]["calls"] == 1
                assert frames1[0]["payload"]["stats"]["cache_hits"] == 0
                assert frames1[0]["payload"]["in_cache"]

                message2 = {
                    "payload": {"value": 100},
                    "route": {"actors": ["a"], "current": 0},
                }
                frames2, status2 = runtime_invoke(handler, message2)

                assert status2 == 200
                assert frames2[0]["payload"]["stats"]["calls"] == 2
                assert frames2[0]["payload"]["stats"]["cache_hits"] == 1

        finally:
            sys.path.pop(0)

    def test_class_handler_without_custom_init(self, runtime_invoke, mock_env, tmp_path):
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
                    "route": {"actors": ["a"], "current": 0},
                }
                frames, status = runtime_invoke(handler, message)

                assert status == 200
                assert len(frames) == 1
                assert frames[0]["payload"]["result"] == 21

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

    def test_load_function_invalid_handler_arg(self, mock_env):
        """Test that invalid ASYA_HANDLER_MODE causes ValueError."""
        with mock_env(ASYA_HANDLER="test.module.func", ASYA_HANDLER_MODE="invalid"):
            with pytest.raises(ValueError, match="Invalid ASYA_HANDLER_MODE"):
                asya_runtime._load_function()


class TestHandlerArgValidation:
    """Test ASYA_HANDLER_MODE validation."""

    def test_valid_handler_args(self, mock_env):
        """Test that valid ASYA_HANDLER_MODE values are accepted."""
        valid_args = ["payload", "envelope", "PAYLOAD", "envelope"]  # Case-insensitive

        for arg in valid_args:
            with mock_env(ASYA_HANDLER_MODE=arg):
                # Should accept both lowercase versions
                assert asya_runtime.ASYA_HANDLER_MODE in ("payload", "envelope")

    def test_default_handler_arg(self):
        """Test that default ASYA_HANDLER_MODE is 'payload'."""
        assert asya_runtime.ASYA_HANDLER_MODE == "payload"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_handle_request_unicode_content(self, runtime_invoke):
        """Test handling of unicode content."""

        def simple_handler(payload):
            return payload

        message = {
            "payload": {"text": "Hello 世界 こんにちは"},
            "route": {"actors": ["a"], "current": 0},
        }
        frames, status = runtime_invoke(simple_handler, message)

        assert status == 200
        assert len(frames) == 1
        assert frames[0]["payload"]["text"] == "Hello 世界 こんにちは"

    def test_handle_request_deeply_nested_json(self, runtime_invoke):
        """Test handling of deeply nested JSON."""

        def simple_handler(payload):
            return payload

        nested = {"level": 0}
        current = nested
        for i in range(1, 50):
            current["next"] = {"level": i}
            current = current["next"]

        message = {"payload": nested, "route": {"actors": ["a"], "current": 0}}
        frames, status = runtime_invoke(simple_handler, message)

        assert status == 200
        assert len(frames) == 1
        assert frames[0]["payload"]["level"] == 0

    def test_handle_request_null_payload(self, runtime_invoke):
        """Test handling of null payload."""

        def simple_handler(payload):
            return payload if payload is not None else {"default": True}

        message = {"payload": None, "route": {"actors": ["a"], "current": 0}}
        frames, status = runtime_invoke(simple_handler, message)

        assert status == 200
        assert len(frames) == 1
        assert frames[0]["payload"] == {"default": True}

    def test_handler_raises_runtime_error(self, runtime_invoke):
        """Test handler that raises RuntimeError."""

        def error_handler(payload):
            raise RuntimeError("Something went wrong")

        message = {
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
        }
        error, status = runtime_invoke(error_handler, message)

        assert status == 500
        assert error["error"] == "processing_error"
        assert error["details"]["type"] == "RuntimeError"
        assert "Something went wrong" in error["details"]["message"]

    def test_handler_returns_complex_types(self, runtime_invoke):
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
            "route": {"actors": ["a"], "current": 0},
        }
        frames, status = runtime_invoke(complex_handler, message)

        assert status == 200
        assert len(frames) == 1
        assert frames[0]["payload"]["int"] == 42
        assert frames[0]["payload"]["float"] == 3.14
        assert frames[0]["payload"]["bool"] is True
        assert frames[0]["payload"]["null"] is None

    def test_handler_returns_large_response(self, runtime_invoke):
        """Test handler that returns a large response."""

        def large_handler(payload):
            return {"data": "X" * (1024 * 1024)}

        message = {
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
        }
        frames, status = runtime_invoke(large_handler, message)

        assert status == 200
        assert len(frames) == 1
        assert len(frames[0]["payload"]["data"]) == 1024 * 1024

    def test_message_with_special_characters(self, runtime_invoke):
        """Test messages with special JSON characters."""

        def simple_handler(payload):
            return payload

        message = {
            "payload": {"text": 'Test "quotes" and \\backslashes\\ and \n newlines \t tabs'},
            "route": {"actors": ["a"], "current": 0},
        }
        frames, status = runtime_invoke(simple_handler, message)

        assert status == 200
        assert len(frames) == 1
        assert frames[0]["payload"]["text"] == 'Test "quotes" and \\backslashes\\ and \n newlines \t tabs'


class TestStatusPreservation:
    """Test that status field is properly preserved through message processing."""

    def test_payload_mode_preserves_status_in_frame(self, runtime_invoke):
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
            "route": {"actors": ["doubler", "next"], "current": 0},
            "status": status,
        }
        frames, http_status = runtime_invoke(simple_handler, message)

        assert http_status == 200
        assert len(frames) == 1
        assert frames[0]["payload"] == {"result": 42}
        assert frames[0]["status"] == status
        assert frames[0]["route"]["current"] == 1

    def test_payload_mode_no_status_backward_compat(self, runtime_invoke):
        """Test that payload mode works without status (backward compat)."""

        def simple_handler(payload):
            return {"result": "ok"}

        message = {
            "payload": {"test": True},
            "route": {"actors": ["a"], "current": 0},
        }
        frames, status = runtime_invoke(simple_handler, message)

        assert status == 200
        assert len(frames) == 1
        assert frames[0]["payload"] == {"result": "ok"}
        assert "status" not in frames[0]

    def test_envelope_mode_preserves_status(self, runtime_invoke, mock_env):
        """Test that status flows through envelope mode via _validate_message."""
        msg_status = {
            "phase": "processing",
            "actor": "processor",
            "attempt": 1,
            "max_attempts": 1,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:01:00Z",
        }

        def envelope_handler(msg):
            return {
                "payload": {"processed": True},
                "route": {**msg["route"], "current": msg["route"]["current"] + 1},
                "status": msg.get("status"),
            }

        message = {
            "payload": {"data": "test"},
            "route": {"actors": ["processor", "next"], "current": 0},
            "status": msg_status,
        }

        with mock_env(ASYA_HANDLER_MODE="envelope"):
            frames, status = runtime_invoke(envelope_handler, message)

        assert status == 200
        assert len(frames) == 1
        assert frames[0]["status"] == msg_status


class TestHeadersPreservation:
    """Test that headers field is properly preserved through message processing."""

    def test_headers_preserved_in_payload_mode(self, runtime_invoke):
        """Test that headers are preserved when using payload mode."""

        def simple_handler(payload):
            return {"result": payload["value"] * 2}

        message = {
            "payload": {"value": 42},
            "route": {"actors": ["doubler"], "current": 0},
            "headers": {"trace_id": "abc-123", "priority": "high"},
        }
        frames, status = runtime_invoke(simple_handler, message)

        assert status == 200
        assert len(frames) == 1
        assert frames[0]["payload"] == {"result": 84}
        assert frames[0]["headers"] == {"trace_id": "abc-123", "priority": "high"}
        assert frames[0]["route"] == {"actors": ["doubler"], "current": 1}

    def test_headers_preserved_in_fanout_payload_mode(self, runtime_invoke):
        """Test that headers are preserved in fanout with payload mode."""

        def fanout_handler(payload):
            yield {"id": 1}
            yield {"id": 2}

        message = {
            "payload": {"test": "data"},
            "route": {"actors": ["fan"], "current": 0},
            "headers": {"correlation_id": "xyz-789"},
        }
        frames, status = runtime_invoke(fanout_handler, message)

        assert status == 200
        assert len(frames) == 2
        assert frames[0]["payload"] == {"id": 1}
        assert frames[0]["headers"] == {"correlation_id": "xyz-789"}
        assert frames[1]["payload"] == {"id": 2}
        assert frames[1]["headers"] == {"correlation_id": "xyz-789"}

    def test_headers_optional_in_payload_mode(self, runtime_invoke):
        """Test that headers are optional and don't break processing."""

        def simple_handler(payload):
            return payload

        message = {
            "payload": {"test": "data"},
            "route": {"actors": ["echo"], "current": 0},
        }
        frames, status = runtime_invoke(simple_handler, message)

        assert status == 200
        assert len(frames) == 1
        assert frames[0]["payload"] == {"test": "data"}
        assert "headers" not in frames[0]

    def test_headers_preserved_in_envelope_mode(self, runtime_invoke, mock_env):
        """Test that headers are preserved when using envelope mode."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def envelope_handler(msg):
                return msg

            message = {
                "payload": {"value": 100},
                "route": {"actors": ["passthrough"], "current": 0},
                "headers": {"request_id": "req-456"},
            }
            frames, status = runtime_invoke(envelope_handler, message)

            assert status == 200
            assert len(frames) == 1
            assert frames[0]["payload"] == {"value": 100}
            assert frames[0]["headers"] == {"request_id": "req-456"}

    def test_headers_validation_invalid_type(self, runtime_invoke):
        """Test that headers validation rejects non-dict types."""

        def simple_handler(payload):
            return payload

        message = {
            "payload": {"test": "data"},
            "route": {"actors": ["echo"], "current": 0},
            "headers": "this should be a dict, not a string",
        }
        error, status = runtime_invoke(simple_handler, message)

        assert status == 400
        assert error["error"] == "msg_parsing_error"
        assert "Field 'headers' must be a dict" in error["details"]["message"]


class TestEnvelopeMode:
    """Test ASYA_HANDLER_MODE=envelope mode."""

    def test_envelope_mode_basic(self, runtime_invoke, mock_env):
        """Test envelope mode with basic handler."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def envelope_handler(msg):
                return msg

            message = {
                "payload": {"value": 123},
                "route": {"actors": ["passthrough"], "current": 0},
                "headers": {"trace_id": "test-123"},
            }
            frames, status = runtime_invoke(envelope_handler, message)

            assert status == 200
            assert len(frames) == 1
            assert frames[0]["payload"] == {"value": 123}
            assert frames[0]["headers"] == {"trace_id": "test-123"}
            assert frames[0]["route"] == {"actors": ["passthrough"], "current": 0}

    def test_envelope_mode_headers_access(self, runtime_invoke, mock_env):
        """Test that envelope mode gives access to headers."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def headers_reader(msg):
                priority = msg.get("headers", {}).get("priority", "low")
                return {
                    "payload": {
                        "priority": priority,
                        "value": msg["payload"]["value"],
                    },
                    "route": msg["route"],
                    "headers": msg.get("headers", {}),
                }

            message = {
                "payload": {"value": 42},
                "route": {"actors": ["processor"], "current": 0},
                "headers": {"priority": "high", "trace_id": "xyz"},
            }
            frames, status = runtime_invoke(headers_reader, message)

            assert status == 200
            assert len(frames) == 1
            assert frames[0]["payload"] == {"priority": "high", "value": 42}
            assert frames[0]["headers"] == {"priority": "high", "trace_id": "xyz"}

    def test_envelope_mode_fanout(self, runtime_invoke, mock_env):
        """Test envelope mode with fanout."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def fanout_handler(msg):
                yield {"payload": {"id": 1}, "route": msg["route"], "headers": msg.get("headers", {})}
                yield {"payload": {"id": 2}, "route": msg["route"], "headers": msg.get("headers", {})}

            message = {
                "payload": {"test": "data"},
                "route": {"actors": ["fan"], "current": 0},
                "headers": {"correlation_id": "abc"},
            }
            frames, status = runtime_invoke(fanout_handler, message)

            assert status == 200
            assert len(frames) == 2
            assert frames[0]["payload"] == {"id": 1}
            assert frames[0]["headers"] == {"correlation_id": "abc"}
            assert frames[1]["payload"] == {"id": 2}
            assert frames[1]["headers"] == {"correlation_id": "abc"}

    def test_envelope_mode_validation(self, runtime_invoke, mock_env):
        """Test envelope mode output validation."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def invalid_handler(msg):
                return {"payload": {"result": "ok"}}  # Missing route

            message = {
                "payload": {"test": "data"},
                "route": {"actors": ["processor"], "current": 0},
            }
            error, status = runtime_invoke(invalid_handler, message)

            assert status == 500
            assert error["error"] == "processing_error"
            assert "Missing required field 'route'" in error["details"]["message"]

    def test_envelope_mode_returns_none(self, runtime_invoke, mock_env):
        """Test envelope mode handler returning None."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def none_handler(msg):
                return None

            message = {
                "payload": {"test": "data"},
                "route": {"actors": ["processor"], "current": 0},
            }
            frames, status = runtime_invoke(none_handler, message)

            assert status == 204
            assert frames == []


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
    """Test async handler execution through POST /invoke."""

    def test_async_payload_mode_basic(self, runtime_invoke):
        """Async handler in payload mode returns correct result."""

        async def async_echo(payload):
            return {"echoed": payload["msg"]}

        message = {
            "payload": {"msg": "hello"},
            "route": {"actors": ["a"], "current": 0},
        }
        frames, status = runtime_invoke(async_echo, message)

        assert status == 200
        assert len(frames) == 1
        assert frames[0]["payload"] == {"echoed": "hello"}
        assert frames[0]["route"]["current"] == 1

    def test_async_payload_mode_list_return(self, runtime_invoke):
        """Async handler returning list is treated as single payload (not fan-out)."""

        async def async_list_return(payload):
            return [{"i": 0}, {"i": 1}, {"i": 2}]

        message = {
            "payload": {"test": True},
            "route": {"actors": ["a", "b"], "current": 0},
        }
        frames, status = runtime_invoke(async_list_return, message)

        assert status == 200
        assert len(frames) == 1
        assert frames[0]["payload"] == [{"i": 0}, {"i": 1}, {"i": 2}]
        assert frames[0]["route"]["current"] == 1

    def test_async_payload_mode_none_return(self, runtime_invoke):
        """Async handler returning None in payload mode aborts pipeline."""

        async def async_none(payload):
            return None

        message = {
            "payload": {"test": True},
            "route": {"actors": ["a"], "current": 0},
        }
        frames, status = runtime_invoke(async_none, message)

        assert status == 204
        assert frames == []

    def test_async_envelope_mode(self, runtime_invoke, mock_env):
        """Async handler in envelope mode receives full message."""

        async def async_envelope(message):
            return {
                "payload": {"processed": message["payload"]["data"]},
                "route": {**message["route"], "current": message["route"]["current"] + 1},
                "headers": message.get("headers", {}),
            }

        message = {
            "payload": {"data": "test"},
            "route": {"actors": ["a", "b"], "current": 0},
            "headers": {"trace_id": "t1"},
        }

        with mock_env(ASYA_HANDLER_MODE="envelope"):
            frames, status = runtime_invoke(async_envelope, message)

        assert status == 200
        assert len(frames) == 1
        assert frames[0]["payload"] == {"processed": "test"}
        assert frames[0]["route"]["current"] == 1
        assert frames[0]["headers"] == {"trace_id": "t1"}

    def test_async_handler_exception_produces_processing_error(self, runtime_invoke):
        """Async handler raising exception results in processing_error."""

        async def async_error(payload):
            raise ValueError("async handler failed")

        message = {
            "payload": {"test": True},
            "route": {"actors": ["a"], "current": 0},
        }
        error, status = runtime_invoke(async_error, message)

        assert status == 500
        assert error["error"] == "processing_error"
        assert "async handler failed" in error["details"]["message"]
        assert error["details"]["type"] == "ValueError"

    def test_sync_handler_still_works(self, runtime_invoke):
        """Sync handlers continue to work unchanged (regression test)."""

        def sync_handler(payload):
            return {"result": payload["value"] + 1}

        message = {
            "payload": {"value": 41},
            "route": {"actors": ["a"], "current": 0},
        }
        frames, status = runtime_invoke(sync_handler, message)

        assert status == 200
        assert len(frames) == 1
        assert frames[0]["payload"] == {"result": 42}

    def test_async_class_method_handler(self, runtime_invoke):
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
            "route": {"actors": ["a"], "current": 0},
        }
        frames, status = runtime_invoke(processor.process, message)

        assert status == 200
        assert len(frames) == 1
        assert frames[0]["payload"]["count"] == 1
        assert frames[0]["payload"]["data"] == {"test": "data"}

    def test_async_handler_preserves_headers(self, runtime_invoke):
        """Async handler in payload mode preserves headers."""

        async def async_handler(payload):
            return {"result": "ok"}

        message = {
            "payload": {"test": True},
            "route": {"actors": ["a", "b"], "current": 0},
            "headers": {"trace_id": "abc", "priority": "high"},
        }
        frames, status = runtime_invoke(async_handler, message)

        assert status == 200
        assert len(frames) == 1
        assert frames[0]["headers"] == {"trace_id": "abc", "priority": "high"}


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
            "route": {"actors": ["a", "b"], "current": 0},
        }
        frames, status = runtime_invoke(handler, message)
        assert status == 200
        assert len(frames) == 1
        assert frames[0]["payload"] == {"result": 11}
        assert frames[0]["route"]["current"] == 1
        assert frames[0]["route"]["actors"] == ["a", "b"]

    def test_payload_mode_preserves_headers(self, runtime_invoke):
        message = {
            "payload": {"x": 1},
            "route": {"actors": ["a", "b"], "current": 0},
            "headers": {"trace_id": "abc-123"},
        }
        frames, status = runtime_invoke(lambda p: {"ok": True}, message)
        assert status == 200
        assert frames[0]["headers"] == {"trace_id": "abc-123"}

    def test_payload_mode_preserves_status(self, runtime_invoke):
        message = {
            "payload": {},
            "route": {"actors": ["a"], "current": 0},
            "status": {"phase": "working"},
        }
        frames, status = runtime_invoke(lambda p: {"ok": True}, message)
        assert status == 200
        assert frames[0]["status"] == {"phase": "working"}

    def test_async_handler(self, runtime_invoke):
        async def handler(payload):
            return {"async": True}

        message = {"payload": {}, "route": {"actors": ["a"], "current": 0}}
        frames, status = runtime_invoke(handler, message)
        assert status == 200
        assert frames[0]["payload"] == {"async": True}

    # --- Abort (204) ---

    def test_handler_returns_none_204(self, runtime_invoke):
        message = {"payload": {}, "route": {"actors": ["a"], "current": 0}}
        frames, status = runtime_invoke(lambda p: None, message)
        assert status == 204
        assert frames == []

    # --- Handler error (500) ---

    def test_handler_exception_500(self, runtime_invoke):
        def bad_handler(payload):
            raise ValueError("something broke")

        message = {"payload": {}, "route": {"actors": ["a"], "current": 0}}
        error, status = runtime_invoke(bad_handler, message)
        assert status == 500
        assert error["error"] == "processing_error"
        assert "something broke" in error["details"]["message"]
        assert error["details"]["type"] == "ValueError"

    # --- Parse error (400) ---

    def test_missing_payload_400(self, runtime_invoke):
        message = {"route": {"actors": ["a"], "current": 0}}
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

        message = {"payload": {}, "route": {"actors": ["a", "b"], "current": 0}}
        frames, status = runtime_invoke(gen, message)
        assert status == 200
        assert len(frames) == 3
        assert [f["payload"]["id"] for f in frames] == [1, 2, 3]
        assert all(f["route"]["current"] == 1 for f in frames)

    def test_generator_yields_nothing_204(self, runtime_invoke):
        def empty_gen(payload):
            return
            yield  # noqa: unreachable

        message = {"payload": {}, "route": {"actors": ["a"], "current": 0}}
        frames, status = runtime_invoke(empty_gen, message)
        assert status == 204

    # --- Envelope mode ---

    def test_envelope_mode_success(self, runtime_invoke, mock_env):
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def handler(msg):
                return {
                    "payload": {"processed": True},
                    "route": msg["route"],
                }

            message = {"payload": {"x": 1}, "route": {"actors": ["a"], "current": 0}}
            frames, status = runtime_invoke(handler, message)
            assert status == 200
            assert frames[0]["payload"] == {"processed": True}

    def test_envelope_mode_returns_none(self, runtime_invoke, mock_env):
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            message = {"payload": {}, "route": {"actors": ["a"], "current": 0}}
            frames, status = runtime_invoke(lambda m: None, message)
            assert status == 204

    def test_envelope_mode_generator(self, runtime_invoke, mock_env):
        with mock_env(ASYA_HANDLER_MODE="envelope"):

            def gen(msg):
                for i in range(2):
                    yield {
                        "payload": {"i": i},
                        "route": msg["route"],
                    }

            message = {"payload": {}, "route": {"actors": ["a"], "current": 0}}
            frames, status = runtime_invoke(gen, message)
            assert status == 200
            assert len(frames) == 2

    # --- Large payloads ---

    @pytest.mark.parametrize("size_kb", [10, 100, 500, 1024])
    def test_large_payloads(self, runtime_invoke, size_kb):
        large_data = "X" * (size_kb * 1024)
        message = {
            "payload": {"data": large_data},
            "route": {"actors": ["a"], "current": 0},
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
