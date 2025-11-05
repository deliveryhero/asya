#!/usr/bin/env python3
"""Tests for asya_runtime.py Unix socket server."""
import importlib
import json
import os
import socket
import stat
import struct
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

# Add parent directory to path to import asya_runtime functions
sys.path.insert(0, str(Path(__file__).parent.parent))

import asya_runtime


@pytest.fixture
def runtime_env():
    """
    Fixture factory for setting environment variables and reloading asya_runtime.

    This provides the most realistic testing by using actual environment variables
    and module reloading, matching production behavior exactly.

    Usage:
        def test_something(runtime_env):
            with runtime_env(ASYA_HANDLER_ARG_TYPE="message", ASYA_SOCKET_CHMOD="0o600"):
                # asya_runtime module is reloaded with new env vars
                assert asya_runtime.ASYA_HANDLER_ARG_TYPE == "message"

    Yields:
        Callable: Context manager that accepts env var overrides as kwargs
    """

    @contextmanager
    def _runtime_env(**env_vars):
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

    return _runtime_env


@pytest.fixture
def socket_pair():
    """
    Create a connected socket pair for testing.

    Yields:
        tuple: (server_sock, client_sock) - A pair of connected sockets
    """
    server_sock, client_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        yield server_sock, client_sock
    finally:
        server_sock.close()
        client_sock.close()


class TestHandlerReturnTypeValidation:
    """Test handler return type validation in payload mode."""

    def test_handler_returns_string_payload_mode(self, socket_pair):
        """Test handler returning string instead of dict in payload mode."""
        server_sock, client_sock = socket_pair

        def string_handler(payload):
            return "this is a string, not a dict"

        message = {"payload": {"test": "data"}, "route": {"steps": ["a"], "current": 0}}
        message_data = json.dumps(message).encode("utf-8")
        asya_runtime._send_msg(client_sock, message_data)

        responses = asya_runtime._handle_request(server_sock, string_handler)

        # String is a valid payload type
        assert len(responses) == 1
        assert responses[0]["payload"] == "this is a string, not a dict"

    def test_handler_returns_number_payload_mode(self, socket_pair):
        """Test handler returning number in payload mode."""
        server_sock, client_sock = socket_pair

        def number_handler(payload):
            return 42

        message = {"payload": {"test": "data"}, "route": {"steps": ["a"], "current": 0}}
        message_data = json.dumps(message).encode("utf-8")
        asya_runtime._send_msg(client_sock, message_data)

        responses = asya_runtime._handle_request(server_sock, number_handler)

        assert len(responses) == 1
        assert responses[0]["payload"] == 42

    def test_handler_returns_none_payload_mode(self, socket_pair):
        """Test handler returning None in payload mode (abort execution)."""
        server_sock, client_sock = socket_pair

        def none_handler(payload):
            return None

        message = {"payload": {"test": "data"}, "route": {"steps": ["a"], "current": 0}}
        message_data = json.dumps(message).encode("utf-8")
        asya_runtime._send_msg(client_sock, message_data)

        responses = asya_runtime._handle_request(server_sock, none_handler)

        assert len(responses) == 0

    def test_handler_returns_empty_list(self, socket_pair):
        """Test handler returning empty list (no fan-out)."""
        server_sock, client_sock = socket_pair

        def empty_list_handler(payload):
            return []

        message = {"payload": {"test": "data"}, "route": {"steps": ["a"], "current": 0}}
        message_data = json.dumps(message).encode("utf-8")
        asya_runtime._send_msg(client_sock, message_data)

        responses = asya_runtime._handle_request(server_sock, empty_list_handler)

        # Empty list means no output messages
        assert len(responses) == 0


class TestRouteValidation:
    """Test route validation edge cases."""

    def test_parse_msg_route_not_dict(self):
        """Test route as string instead of dict - should fail validation."""
        with pytest.raises(ValueError, match="Field 'route' must be a dict"):
            data = json.dumps(
                {"payload": {"test": "data"}, "route": "not a dict"}
            ).encode("utf-8")
            msg = asya_runtime._parse_msg_json(data)
            asya_runtime._validate_message_syntax(msg)

    def test_parse_msg_route_missing_steps(self):
        """Test route without steps field - should fail validation."""
        with pytest.raises(ValueError, match="Missing required field 'steps' in route"):
            data = json.dumps(
                {"payload": {"test": "data"}, "route": {"current": 0}}
            ).encode("utf-8")
            msg = asya_runtime._parse_msg_json(data)
            asya_runtime._validate_message_syntax(msg)

    def test_parse_msg_route_steps_not_list(self):
        """Test route with steps as non-list - should fail validation."""
        with pytest.raises(ValueError, match="Field 'route.steps' must be a list"):
            data = json.dumps(
                {"payload": {"test": "data"}, "route": {"steps": "not a list"}}
            ).encode("utf-8")
            msg = asya_runtime._parse_msg_json(data)
            asya_runtime._validate_message_syntax(msg)

    def test_parse_msg_route_missing_current(self):
        """Test route without current field - should fail validation."""
        with pytest.raises(
            ValueError, match="Missing required field 'current' in route"
        ):
            data = json.dumps(
                {"payload": {"test": "data"}, "route": {"steps": ["a", "b"]}}
            ).encode("utf-8")
            msg = asya_runtime._parse_msg_json(data)
            asya_runtime._validate_message_syntax(msg)

    def test_parse_msg_route_current_not_int(self):
        """Test route with current as non-integer - should fail validation."""
        with pytest.raises(
            ValueError, match="Field 'route.current' must be an integer"
        ):
            data = json.dumps(
                {
                    "payload": {"test": "data"},
                    "route": {"steps": ["a", "b"], "current": "0"},
                }
            ).encode("utf-8")
            msg = asya_runtime._parse_msg_json(data)
            asya_runtime._validate_message_syntax(msg)

    def test_parse_msg_route_current_negative(self):
        """Test route with negative current index - should fail validation."""
        with pytest.raises(ValueError, match="Invalid route.current=-1"):
            data = json.dumps(
                {"payload": {"test": "data"}, "route": {"steps": ["a"], "current": -1}}
            ).encode("utf-8")
            msg = asya_runtime._parse_msg_json(data)
            asya_runtime._validate_message_syntax(msg)

    def test_parse_msg_route_current_out_of_bounds(self):
        """Test route with current index beyond steps length - should fail validation."""
        with pytest.raises(ValueError, match="Invalid route.current=10"):
            data = json.dumps(
                {
                    "payload": {"test": "data"},
                    "route": {"steps": ["a", "b"], "current": 10},
                }
            ).encode("utf-8")
            msg = asya_runtime._parse_msg_json(data)
            asya_runtime._validate_message_syntax(msg)

    def test_parse_msg_route_empty_steps_current_zero(self):
        """Test route with empty steps array and current=0 - should fail validation."""
        with pytest.raises(ValueError, match="Invalid route.current=0"):
            data = json.dumps(
                {"payload": {"test": "data"}, "route": {"steps": [], "current": 0}}
            ).encode("utf-8")
            msg = asya_runtime._parse_msg_json(data)
            asya_runtime._validate_message_syntax(msg)


class TestMessageModeValidation:
    """Test message mode validation edge cases."""

    def test_handler_returns_invalid_payload_type_in_message(
        self, socket_pair, runtime_env
    ):
        """Test handler returns message with payload as string instead of dict."""
        with runtime_env(ASYA_HANDLER_ARG_TYPE="message"):
            server_sock, client_sock = socket_pair

            def invalid_handler(msg):
                # Return message with payload as string
                return {"payload": "not a dict", "route": msg["route"]}

            message = {
                "payload": {"test": "data"},
                "route": {"steps": ["a"], "current": 0},
            }
            message_data = json.dumps(message).encode("utf-8")
            asya_runtime._send_msg(client_sock, message_data)

            responses = asya_runtime._handle_request(server_sock, invalid_handler)

            # Should work - payload can be any JSON type
            assert len(responses) == 1
            assert responses[0]["payload"] == "not a dict"

    def test_handler_returns_invalid_route_type_in_message(
        self, socket_pair, runtime_env
    ):
        """Test handler returns message with route as wrong type."""
        with runtime_env(ASYA_HANDLER_ARG_TYPE="message"):
            server_sock, client_sock = socket_pair

            def invalid_handler(msg):
                # Return message with route as string
                return {"payload": {"ok": True}, "route": "invalid"}

            message = {
                "payload": {"test": "data"},
                "route": {"steps": ["a"], "current": 0},
            }
            message_data = json.dumps(message).encode("utf-8")
            asya_runtime._send_msg(client_sock, message_data)

            responses = asya_runtime._handle_request(server_sock, invalid_handler)

            # Should return error - route validation will fail
            assert len(responses) == 1
            assert responses[0]["error"] == "processing_error"
            assert "Field 'route' must be a dict" in responses[0]["details"]["message"]

    def test_handler_returns_list_with_invalid_message(self, socket_pair, runtime_env):
        """Test handler returns list with one valid and one invalid message."""
        with runtime_env(ASYA_HANDLER_ARG_TYPE="message"):
            server_sock, client_sock = socket_pair

            def mixed_handler(msg):
                return [
                    {"payload": {"id": 1}, "route": msg["route"]},
                    {"payload": {"id": 2}},  # Missing 'route'
                ]

            message = {
                "payload": {"test": "data"},
                "route": {"steps": ["a"], "current": 0},
            }
            message_data = json.dumps(message).encode("utf-8")
            asya_runtime._send_msg(client_sock, message_data)

            responses = asya_runtime._handle_request(server_sock, mixed_handler)

            # Should return error because second message is invalid
            assert len(responses) == 1
            assert responses[0]["error"] == "processing_error"
            assert "message[1/2]" in responses[0]["details"]["message"]

    def test_handler_changes_current_actor(self, socket_pair, runtime_env):
        """Test that handler cannot change current actor position."""
        with runtime_env(ASYA_HANDLER_ARG_TYPE="message"):
            server_sock, client_sock = socket_pair

            def actor_changing_handler(msg):
                # Try to change current to point to different actor
                return {
                    "payload": msg["payload"],
                    "route": {"steps": ["a", "b", "c"], "current": 1},
                }

            message = {
                "payload": {"test": "data"},
                "route": {"steps": ["a", "b", "c"], "current": 0},
            }
            message_data = json.dumps(message).encode("utf-8")
            asya_runtime._send_msg(client_sock, message_data)

            responses = asya_runtime._handle_request(
                server_sock, actor_changing_handler
            )

            # Should return error - actor changed from 'a' (index 0) to 'b' (index 1)
            assert len(responses) == 1
            assert responses[0]["error"] == "processing_error"
            assert "Route mismatch" in responses[0]["details"]["message"]
            assert "'a'" in responses[0]["details"]["message"]
            assert "'b'" in responses[0]["details"]["message"]

    def test_handler_modifies_route_but_keeps_current_actor(
        self, socket_pair, runtime_env
    ):
        """Test that handler can modify route steps as long as current actor stays same."""
        with runtime_env(ASYA_HANDLER_ARG_TYPE="message"):
            server_sock, client_sock = socket_pair

            def route_modifying_handler(msg):
                # Add more steps but keep current pointing to same actor
                return {
                    "payload": msg["payload"],
                    "route": {"steps": ["a", "b", "c", "d"], "current": 0},
                }

            message = {
                "payload": {"test": "data"},
                "route": {"steps": ["a", "b"], "current": 0},
            }
            message_data = json.dumps(message).encode("utf-8")
            asya_runtime._send_msg(client_sock, message_data)

            responses = asya_runtime._handle_request(
                server_sock, route_modifying_handler
            )

            # Should work - current still points to 'a'
            assert len(responses) == 1
            assert responses[0]["route"]["steps"] == ["a", "b", "c", "d"]
            assert responses[0]["route"]["current"] == 0

    def test_handler_fanout_with_actor_validation(self, socket_pair, runtime_env):
        """Test fan-out where all output messages maintain correct current actor."""
        with runtime_env(ASYA_HANDLER_ARG_TYPE="message"):
            server_sock, client_sock = socket_pair

            def fanout_handler(msg):
                # Return multiple messages, all pointing to same current actor
                return [
                    {
                        "payload": {"id": 1},
                        "route": {"steps": ["a", "b"], "current": 0},
                    },
                    {
                        "payload": {"id": 2},
                        "route": {"steps": ["a", "b"], "current": 0},
                    },
                    {
                        "payload": {"id": 3},
                        "route": {"steps": ["a", "c"], "current": 0},
                    },
                ]

            message = {
                "payload": {"test": "data"},
                "route": {"steps": ["a", "b"], "current": 0},
            }
            message_data = json.dumps(message).encode("utf-8")
            asya_runtime._send_msg(client_sock, message_data)

            responses = asya_runtime._handle_request(server_sock, fanout_handler)

            # Should work - all output messages point to 'a' at index 0
            assert len(responses) == 3
            assert responses[0]["payload"] == {"id": 1}
            assert responses[1]["payload"] == {"id": 2}
            assert responses[2]["payload"] == {"id": 3}

    def test_handler_fanout_with_invalid_actor_name(self, socket_pair, runtime_env):
        """Test fan-out where one message has wrong current actor."""
        with runtime_env(ASYA_HANDLER_ARG_TYPE="message"):
            server_sock, client_sock = socket_pair

            def invalid_fanout_handler(msg):
                return [
                    {
                        "payload": {"id": 1},
                        "route": {"steps": ["a", "b"], "current": 0},
                    },
                    {
                        "payload": {"id": 2},
                        "route": {"steps": ["a", "b"], "current": 1},
                    },  # Wrong actor
                ]

            message = {
                "payload": {"test": "data"},
                "route": {"steps": ["a", "b"], "current": 0},
            }
            message_data = json.dumps(message).encode("utf-8")
            asya_runtime._send_msg(client_sock, message_data)

            responses = asya_runtime._handle_request(
                server_sock, invalid_fanout_handler
            )

            # Should return error for message[1]
            assert len(responses) == 1
            assert responses[0]["error"] == "processing_error"
            assert "message[1/2]" in responses[0]["details"]["message"]
            assert "Route mismatch" in responses[0]["details"]["message"]


class TestLargePayloads:
    """Test handling of large payloads."""

    @pytest.mark.parametrize("size_kb", [10, 100, 500, 1024, 5 * 1024, 10 * 1024])
    def test_large_payloads(self, socket_pair, size_kb):
        """Test various payload sizes from KB to MB using threading."""
        import threading

        server_sock, client_sock = socket_pair

        def echo_handler(payload):
            return payload

        # Create payload of specified size
        large_data = "X" * (size_kb * 1024)
        message = {
            "payload": {"data": large_data},
            "route": {"steps": ["a"], "current": 0},
        }
        message_data = json.dumps(message).encode("utf-8")

        responses_container = []

        def sender():
            asya_runtime._send_msg(client_sock, message_data)

        def receiver():
            resp = asya_runtime._handle_request(server_sock, echo_handler)
            responses_container.append(resp)

        # Use threading to avoid socket buffer deadlock
        recv_thread = threading.Thread(target=receiver)
        send_thread = threading.Thread(target=sender)

        recv_thread.start()
        send_thread.start()

        send_thread.join(timeout=2)
        recv_thread.join(timeout=2)

        assert len(responses_container) == 1
        responses = responses_container[0]
        assert len(responses) == 1
        assert len(responses[0]["payload"]["data"]) == size_kb * 1024

    def test_zero_length_message(self, socket_pair):
        """Test zero-length message."""
        server_sock, client_sock = socket_pair

        def simple_handler(payload):
            return payload

        # Send zero-length message (just length prefix = 0)
        asya_runtime._send_msg(client_sock, b"")

        responses = asya_runtime._handle_request(server_sock, simple_handler)

        # Should return parsing error
        assert len(responses) == 1
        assert responses[0]["error"] == "msg_parsing_error"


class TestConnectionEdgeCases:
    """Test socket and connection edge cases."""

    def test_connection_closed_during_length_read(self, socket_pair):
        """Test connection closed while reading length prefix."""
        server_sock, client_sock = socket_pair

        def simple_handler(payload):
            return payload

        # Send partial length prefix (only 2 bytes instead of 4)
        client_sock.send(b"\x00\x00")
        client_sock.close()

        responses = asya_runtime._handle_request(server_sock, simple_handler)

        assert len(responses) == 1
        assert responses[0]["error"] == "connection_error"

    def test_connection_closed_during_data_read(self, socket_pair):
        """Test connection closed while reading message data."""
        server_sock, client_sock = socket_pair

        def simple_handler(payload):
            return payload

        # Send length prefix indicating 100 bytes
        import struct

        length_prefix = struct.pack(">I", 100)
        client_sock.send(length_prefix)
        # Send only 10 bytes then close
        client_sock.send(b"X" * 10)
        client_sock.close()

        responses = asya_runtime._handle_request(server_sock, simple_handler)

        assert len(responses) == 1
        assert responses[0]["error"] == "connection_error"


class TestConfigFixtures:
    """Test configuration fixture patterns."""

    def test_runtime_env_fixture_basic(self, runtime_env):
        """Test runtime_env fixture with basic config override."""
        original_value = asya_runtime.ASYA_HANDLER_ARG_TYPE
        assert asya_runtime.ASYA_HANDLER_ARG_TYPE == original_value

        with runtime_env(ASYA_HANDLER_ARG_TYPE="message"):
            assert asya_runtime.ASYA_HANDLER_ARG_TYPE == "message"

        assert asya_runtime.ASYA_HANDLER_ARG_TYPE == original_value

    def test_runtime_env_fixture_multiple_vars(self, runtime_env):
        """Test runtime_env fixture with multiple env vars."""
        with runtime_env(
            ASYA_HANDLER_ARG_TYPE="message",
            ASYA_SOCKET_CHMOD="0o600",
            ASYA_CHUNK_SIZE="8192",
        ):
            assert asya_runtime.ASYA_HANDLER_ARG_TYPE == "message"
            assert asya_runtime.ASYA_SOCKET_CHMOD == "0o600"
            assert asya_runtime.ASYA_CHUNK_SIZE == 8192


class TestSocketProtocol:
    """Test the socket protocol functions."""

    def test_recv_exact(self, socket_pair):
        """Test recv_exact function."""
        server_sock, client_sock = socket_pair

        test_data = b"Hello, World!"
        client_sock.sendall(test_data)

        received = asya_runtime._recv_exact(server_sock, len(test_data))
        assert received == test_data

        client_sock.sendall(b"1234567890")
        part1 = asya_runtime._recv_exact(server_sock, 5)
        part2 = asya_runtime._recv_exact(server_sock, 5)
        assert part1 == b"12345"
        assert part2 == b"67890"

    def test_recv_exact_connection_closed(self, socket_pair):
        """Test recv_exact when connection is closed."""
        server_sock, client_sock = socket_pair

        client_sock.close()

        with pytest.raises(ConnectionError, match="Connection closed while reading"):
            asya_runtime._recv_exact(server_sock, 10)

    def test_send_msg(self, socket_pair):
        """Test send_msg function."""
        server_sock, client_sock = socket_pair

        test_data = b"Test message with length prefix"
        asya_runtime._send_msg(client_sock, test_data)

        length_bytes = asya_runtime._recv_exact(server_sock, 4)
        length = struct.unpack(">I", length_bytes)[0]
        assert length == len(test_data)

        received = asya_runtime._recv_exact(server_sock, length)
        assert received == test_data

    @pytest.mark.parametrize("size_kb", [10, 1024, 10 * 1024, 100 * 1024])
    def test_send_recv_large_message(self, socket_pair, size_kb):
        """Test send/recv with large message."""
        server_sock, client_sock = socket_pair

        test_data = b"X" * (size_kb * 1024)

        def sender():
            asya_runtime._send_msg(client_sock, test_data)

        sender_thread = threading.Thread(target=sender)
        sender_thread.start()

        length_bytes = asya_runtime._recv_exact(server_sock, 4)
        length = struct.unpack(">I", length_bytes)[0]
        assert length == len(test_data)

        received = asya_runtime._recv_exact(server_sock, length)
        assert received == test_data

        sender_thread.join()


class TestSocketSetup:
    """Test socket setup and cleanup."""

    def test_socket_setup_cleanup(self):
        """Test socket setup with default chmod."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            sock = asya_runtime._setup_socket(socket_path)
            assert os.path.exists(socket_path)

            stat_info = os.stat(socket_path)
            permissions = oct(stat_info.st_mode)[-3:]
            assert permissions == "660"

            sock.close()
            os.unlink(socket_path)
            assert not os.path.exists(socket_path)

    def test_socket_setup_custom_chmod(self, monkeypatch):
        """Test socket setup with custom chmod."""
        monkeypatch.setattr(asya_runtime, "ASYA_SOCKET_CHMOD", "0o600")

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            sock = asya_runtime._setup_socket(socket_path)
            assert os.path.exists(socket_path)

            stat_info = os.stat(socket_path)
            permissions = oct(stat_info.st_mode)[-3:]
            assert permissions == "600"

            sock.close()
            os.unlink(socket_path)

    def test_socket_setup_no_chmod(self, monkeypatch):
        """Test socket setup with chmod disabled."""
        monkeypatch.setattr(asya_runtime, "ASYA_SOCKET_CHMOD", "")

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            sock = asya_runtime._setup_socket(socket_path)
            assert os.path.exists(socket_path)

            stat_info = os.stat(socket_path)
            assert stat.S_ISSOCK(stat_info.st_mode)

            sock.close()
            os.unlink(socket_path)

    def test_socket_setup_removes_existing(self):
        """Test that setup removes existing socket file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            sock1 = asya_runtime._setup_socket(socket_path)
            sock1.close()

            sock2 = asya_runtime._setup_socket(socket_path)
            assert os.path.exists(socket_path)

            sock2.close()
            os.unlink(socket_path)


class TestParseMsg:
    """Test _parse_msg_json and _validate_message_syntax functions."""

    def test_parse_msg_with_payload_and_route(self):
        """Test parsing message with both payload and route."""
        data = json.dumps(
            {"payload": {"test": "data"}, "route": {"steps": ["a", "b"], "current": 0}}
        ).encode("utf-8")

        msg = asya_runtime._parse_msg_json(data)
        msg = asya_runtime._validate_message_syntax(msg)

        assert msg["payload"] == {"test": "data"}
        assert msg["route"] == {"steps": ["a", "b"], "current": 0}

    def test_parse_msg_missing_payload(self):
        """Test parsing message without payload field."""
        with pytest.raises(ValueError, match="Missing required .*payload"):
            data = json.dumps({"route": {"steps": ["a"], "current": 0}}).encode("utf-8")
            msg = asya_runtime._parse_msg_json(data)
            asya_runtime._validate_message_syntax(msg)

    def test_parse_msg_missing_route(self):
        """Test parsing message without route field."""
        with pytest.raises(ValueError, match="Missing required .*route"):
            data = json.dumps({"payload": {"test": "data"}}).encode("utf-8")
            msg = asya_runtime._parse_msg_json(data)
            asya_runtime._validate_message_syntax(msg)

    @pytest.mark.parametrize("payload", [None, {}])
    def test_parse_msg_empty_payload(self, payload):
        """Test parsing message with null/empty payload."""
        data = json.dumps(
            {"payload": payload, "route": {"steps": ["a"], "current": 0}}
        ).encode("utf-8")

        msg = asya_runtime._parse_msg_json(data)
        msg = asya_runtime._validate_message_syntax(msg)

        assert msg["payload"] == payload
        assert msg["route"] == {"steps": ["a"], "current": 0}

    def test_parse_msg_invalid_json(self):
        """Test parsing invalid JSON."""
        with pytest.raises(json.JSONDecodeError):
            asya_runtime._parse_msg_json(b"not json{")

    def test_parse_msg_invalid_utf8(self):
        """Test parsing invalid UTF-8."""
        with pytest.raises(UnicodeDecodeError):
            asya_runtime._parse_msg_json(b"\xff\xfe invalid utf8")


class TestErrorDict:
    """Test _error_dict function."""

    def test_error_dict_basic(self):
        """Test error dict with just error code."""
        errs = asya_runtime._error_response("test_error")
        assert errs == [{"error": "test_error"}]

    def test_error_dict_with_exception(self):
        """Test error dict with exception details."""
        try:
            raise ValueError("Test exception message")
        except ValueError as e:
            errs = asya_runtime._error_response("processing_error", e)
            assert len(errs) == 1
            err = errs[0]
            assert err["error"] == "processing_error"
            assert err["details"]["message"] == "Test exception message"
            assert err["details"]["type"] == "ValueError"
            assert "traceback" in err["details"]
            assert "ValueError" in err["details"]["traceback"]


class TestHandleRequestPayloadMode:
    """Test _handle_request in payload mode (ASYA_HANDLER_ARG_TYPE=payload)."""

    def test_handle_request_success_single_output(self, socket_pair, runtime_env):
        """Test successful request with single output."""
        with runtime_env(ASYA_HANDLER_ARG_TYPE="payload"):
            server_sock, client_sock = socket_pair

            def simple_handler(payload):
                return {"result": payload["value"] * 2}

            message = {
                "route": {"steps": ["step1"], "current": 0},
                "payload": {"value": 42},
            }
            message_data = json.dumps(message).encode("utf-8")
            asya_runtime._send_msg(client_sock, message_data)

            responses = asya_runtime._handle_request(server_sock, simple_handler)

            assert len(responses) == 1
            assert responses[0]["payload"] == {"result": 84}
            assert responses[0]["route"] == {"steps": ["step1"], "current": 0}

    def test_handle_request_fanout_list_output(self, socket_pair, runtime_env):
        """Test fan-out with list output in payload mode."""
        with runtime_env(ASYA_HANDLER_ARG_TYPE="payload"):
            server_sock, client_sock = socket_pair

            def fanout_handler(payload):
                # Return a list of payloads
                return [{"id": 1}, {"id": 2}, {"id": 3}]

            message = {
                "route": {"steps": ["fan"], "current": 0},
                "payload": {"test": "data"},
            }
            message_data = json.dumps(message).encode("utf-8")
            asya_runtime._send_msg(client_sock, message_data)

            responses = asya_runtime._handle_request(server_sock, fanout_handler)

            assert len(responses) == 3
            assert responses[0]["payload"] == {"id": 1}
            assert responses[1]["payload"] == {"id": 2}
            assert responses[2]["payload"] == {"id": 3}
            # All should preserve the original route
            for resp in responses:
                assert resp["route"] == {"steps": ["fan"], "current": 0}


class TestHandleRequestMessageMode:
    """Test _handle_request in message mode (ASYA_HANDLER_ARG_TYPE=message)."""

    def test_handle_request_success_single_output(self, socket_pair, runtime_env):
        """Test successful request with single output in message mode."""
        with runtime_env(ASYA_HANDLER_ARG_TYPE="message"):
            server_sock, client_sock = socket_pair

            def message_handler(msg):
                return {
                    "payload": {"result": msg["payload"]["value"] * 2},
                    "route": msg["route"],
                }

            message = {
                "route": {"steps": ["step1"], "current": 0},
                "payload": {"value": 42},
            }
            message_data = json.dumps(message).encode("utf-8")
            asya_runtime._send_msg(client_sock, message_data)

            responses = asya_runtime._handle_request(server_sock, message_handler)

            assert len(responses) == 1
            assert responses[0]["payload"] == {"result": 84}
            assert responses[0]["route"] == {"steps": ["step1"], "current": 0}

    def test_handle_request_route_modification(self, socket_pair, runtime_env):
        """Test that handler can modify route in message mode."""
        with runtime_env(ASYA_HANDLER_ARG_TYPE="message"):
            server_sock, client_sock = socket_pair

            def route_modifying_handler(msg):
                new_route = msg["route"].copy()
                new_route["steps"] = msg["route"]["steps"] + ["modified"]
                new_route["current"] = 0  # Must keep current pointing to same actor
                return {"payload": msg["payload"], "route": new_route}

            message = {
                "route": {"steps": ["step1"], "current": 0},
                "payload": {"data": "test"},
            }
            message_data = json.dumps(message).encode("utf-8")
            asya_runtime._send_msg(client_sock, message_data)

            responses = asya_runtime._handle_request(
                server_sock, route_modifying_handler
            )

            assert len(responses) == 1
            assert responses[0]["route"]["steps"] == ["step1", "modified"]
            assert responses[0]["route"]["current"] == 0

    def test_handle_request_fanout_list_output(self, socket_pair, runtime_env):
        """Test fan-out with list output in message mode."""
        with runtime_env(ASYA_HANDLER_ARG_TYPE="message"):
            server_sock, client_sock = socket_pair

            def fanout_handler(msg):
                return [
                    {"payload": {"id": 1}, "route": msg["route"]},
                    {"payload": {"id": 2}, "route": msg["route"]},
                    {"payload": {"id": 3}, "route": msg["route"]},
                ]

            message = {
                "route": {"steps": ["fan"], "current": 0},
                "payload": {"test": "data"},
            }
            message_data = json.dumps(message).encode("utf-8")
            asya_runtime._send_msg(client_sock, message_data)

            responses = asya_runtime._handle_request(server_sock, fanout_handler)

            assert len(responses) == 3
            assert responses[0]["payload"] == {"id": 1}
            assert responses[1]["payload"] == {"id": 2}
            assert responses[2]["payload"] == {"id": 3}

    def test_handle_request_invalid_output_missing_keys(self, socket_pair, runtime_env):
        """Test that handler output is validated for required keys."""
        with runtime_env(ASYA_HANDLER_ARG_TYPE="message"):
            server_sock, client_sock = socket_pair

            def invalid_handler(msg):
                # Missing 'route' key
                return {"payload": {"test": "data"}}

            message = {
                "route": {"steps": ["step1"], "current": 0},
                "payload": {"test": "data"},
            }
            message_data = json.dumps(message).encode("utf-8")
            asya_runtime._send_msg(client_sock, message_data)

            responses = asya_runtime._handle_request(server_sock, invalid_handler)

            assert len(responses) == 1
            assert responses[0]["error"] == "processing_error"
            assert (
                "Missing required field 'route'" in responses[0]["details"]["message"]
            )

    def test_handle_request_invalid_output_list_missing_keys(
        self, socket_pair, runtime_env
    ):
        """Test that handler list output is validated for required keys."""
        with runtime_env(ASYA_HANDLER_ARG_TYPE="message"):
            server_sock, client_sock = socket_pair

            def invalid_fanout_handler(msg):
                return [
                    {"payload": {"id": 1}, "route": msg["route"]},
                    {"payload": {"id": 2}},  # Missing 'route'
                ]

            message = {
                "route": {"steps": ["step1"], "current": 0},
                "payload": {"test": "data"},
            }
            message_data = json.dumps(message).encode("utf-8")
            asya_runtime._send_msg(client_sock, message_data)

            responses = asya_runtime._handle_request(
                server_sock, invalid_fanout_handler
            )

            assert len(responses) == 1
            assert responses[0]["error"] == "processing_error"
            assert "message[1/2]" in responses[0]["details"]["message"]


class TestHandleRequestErrorCases:
    """Test error handling in _handle_request."""

    def test_handle_request_invalid_json(self, socket_pair):
        """Test handling of invalid JSON."""
        server_sock, client_sock = socket_pair

        def simple_handler(payload):
            return payload

        invalid_data = b"not valid json{"
        asya_runtime._send_msg(client_sock, invalid_data)

        responses = asya_runtime._handle_request(server_sock, simple_handler)

        assert len(responses) == 1
        assert responses[0]["error"] == "msg_parsing_error"
        assert "details" in responses[0]

    def test_handle_request_handler_exception(self, socket_pair):
        """Test handling of handler exceptions."""
        server_sock, client_sock = socket_pair

        def failing_handler(payload):
            raise ValueError("Handler failed")

        message = {"payload": {"test": "data"}, "route": {"steps": ["a"], "current": 0}}
        message_data = json.dumps(message).encode("utf-8")
        asya_runtime._send_msg(client_sock, message_data)

        responses = asya_runtime._handle_request(server_sock, failing_handler)

        assert len(responses) == 1
        assert responses[0]["error"] == "processing_error"
        assert responses[0]["details"]["message"] == "Handler failed"
        assert responses[0]["details"]["type"] == "ValueError"

    def test_handle_request_connection_closed(self, socket_pair):
        """Test handling when connection is closed."""
        server_sock, client_sock = socket_pair

        def simple_handler(payload):
            return payload

        client_sock.close()

        responses = asya_runtime._handle_request(server_sock, simple_handler)

        assert len(responses) == 1
        assert responses[0]["error"] == "connection_error"

    def test_handle_request_generic_exception(self, socket_pair, runtime_env):
        """Test handling when an unexpected exception occurs during validation."""
        server_sock, client_sock = socket_pair

        def simple_handler(payload):
            return payload

        message = {
            "route": {"steps": ["step1"], "current": 0},
            "payload": {"test": "data"},
        }
        message_data = json.dumps(message).encode("utf-8")
        asya_runtime._send_msg(client_sock, message_data)

        with runtime_env(ASYA_HANDLER_ARG_TYPE="unexpected-value"):
            responses = asya_runtime._handle_request(server_sock, simple_handler)

            # Invalid ASYA_HANDLER_ARG_TYPE causes parsing/validation error
            assert len(responses) == 1
            assert responses[0]["error"] in ("processing_error", "msg_parsing_error")


class TestLoadFunction:
    """Test the _load_function functionality."""

    def test_load_function_missing_handler(self, runtime_env):
        """Test that missing ASYA_HANDLER causes exit."""
        with runtime_env(ASYA_HANDLER=""):
            with pytest.raises(SystemExit) as excinfo:
                asya_runtime._load_function()
            assert excinfo.value.code == 1

    def test_load_function_invalid_format_no_dot(self, runtime_env):
        """Test that ASYA_HANDLER without dot causes exit."""
        with runtime_env(ASYA_HANDLER="invalid"):
            with pytest.raises(SystemExit) as excinfo:
                asya_runtime._load_function()
            assert excinfo.value.code == 1

    def test_load_function_invalid_format_special_chars(self, runtime_env):
        """Test that ASYA_HANDLER with special characters causes exit."""
        invalid_handlers = [
            "../etc/passwd",
            "os;rm -rf /",
            "__import__('os').system('cmd')",
            "my-module.func",  # Hyphens not allowed
            "my module.func",  # Spaces not allowed
        ]

        for invalid in invalid_handlers:
            with runtime_env(ASYA_HANDLER=invalid):
                with pytest.raises(SystemExit) as excinfo:
                    asya_runtime._load_function()
                assert excinfo.value.code == 1

    def test_load_function_module_not_found(self, runtime_env):
        """Test that missing module causes exit."""
        with runtime_env(ASYA_HANDLER="nonexistent_module_xyz.function"):
            with pytest.raises(SystemExit) as excinfo:
                asya_runtime._load_function()
            assert excinfo.value.code == 1

    def test_load_function_invalid_handler_arg(self, runtime_env):
        """Test that invalid ASYA_HANDLER_ARG_TYPE causes ValueError."""
        with runtime_env(
            ASYA_HANDLER="test.module.func", ASYA_HANDLER_ARG_TYPE="invalid"
        ):
            with pytest.raises(ValueError, match="Invalid ASYA_HANDLER_ARG_TYPE"):
                asya_runtime._load_function()


class TestHandlerArgValidation:
    """Test ASYA_HANDLER_ARG_TYPE validation."""

    def test_valid_handler_args(self, runtime_env):
        """Test that valid ASYA_HANDLER_ARG_TYPE values are accepted."""
        valid_args = ["payload", "message", "PAYLOAD", "MESSAGE"]  # Case-insensitive

        for arg in valid_args:
            with runtime_env(ASYA_HANDLER_ARG_TYPE=arg):
                # Should accept both lowercase versions
                assert asya_runtime.ASYA_HANDLER_ARG_TYPE in ("payload", "message")

    def test_default_handler_arg(self):
        """Test that default ASYA_HANDLER_ARG_TYPE is 'payload'."""
        assert asya_runtime.ASYA_HANDLER_ARG_TYPE == "payload"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_recv_exact_partial_data(self, socket_pair):
        """Test recv_exact with data arriving in small chunks."""
        import time

        server_sock, client_sock = socket_pair

        def slow_sender():
            data = b"ABCDEFGHIJ"
            for byte in data:
                time.sleep(0.01)  # Simulate slow connection for buffering test
                client_sock.send(bytes([byte]))

        sender_thread = threading.Thread(target=slow_sender)
        sender_thread.start()

        received = asya_runtime._recv_exact(server_sock, 10)
        assert received == b"ABCDEFGHIJ"

        sender_thread.join()

    def test_send_msg_empty_data(self, socket_pair):
        """Test send_msg with empty data."""
        server_sock, client_sock = socket_pair

        asya_runtime._send_msg(client_sock, b"")

        length_bytes = asya_runtime._recv_exact(server_sock, 4)
        length = struct.unpack(">I", length_bytes)[0]
        assert length == 0

    def test_handle_request_unicode_content(self, socket_pair):
        """Test handling of unicode content."""
        server_sock, client_sock = socket_pair

        def simple_handler(payload):
            return payload

        message = {
            "payload": {"text": "Hello 世界 🌍 こんにちは"},
            "route": {"steps": ["a"], "current": 0},
        }
        message_data = json.dumps(message, ensure_ascii=False).encode("utf-8")
        asya_runtime._send_msg(client_sock, message_data)

        responses = asya_runtime._handle_request(server_sock, simple_handler)

        assert len(responses) == 1
        assert responses[0]["payload"]["text"] == "Hello 世界 🌍 こんにちは"

    def test_handle_request_deeply_nested_json(self, socket_pair):
        """Test handling of deeply nested JSON."""
        server_sock, client_sock = socket_pair

        def simple_handler(payload):
            return payload

        nested = {"level": 0}
        current = nested
        for i in range(1, 50):
            current["next"] = {"level": i}
            current = current["next"]

        message = {"payload": nested, "route": {"steps": ["a"], "current": 0}}
        message_data = json.dumps(message).encode("utf-8")
        asya_runtime._send_msg(client_sock, message_data)

        responses = asya_runtime._handle_request(server_sock, simple_handler)

        assert len(responses) == 1
        assert responses[0]["payload"]["level"] == 0

    def test_handle_request_null_payload(self, socket_pair):
        """Test handling of null payload."""
        server_sock, client_sock = socket_pair

        def simple_handler(payload):
            return payload if payload is not None else {"default": True}

        message = {"payload": None, "route": {"steps": ["a"], "current": 0}}
        message_data = json.dumps(message).encode("utf-8")
        asya_runtime._send_msg(client_sock, message_data)

        responses = asya_runtime._handle_request(server_sock, simple_handler)

        assert len(responses) == 1
        assert responses[0]["payload"] == {"default": True}

    def test_handler_raises_runtime_error(self, socket_pair):
        """Test handler that raises RuntimeError."""
        server_sock, client_sock = socket_pair

        def error_handler(payload):
            raise RuntimeError("Something went wrong")

        message = {"payload": {"test": "data"}, "route": {"steps": ["a"], "current": 0}}
        message_data = json.dumps(message).encode("utf-8")
        asya_runtime._send_msg(client_sock, message_data)

        responses = asya_runtime._handle_request(server_sock, error_handler)

        assert len(responses) == 1
        assert responses[0]["error"] == "processing_error"
        assert responses[0]["details"]["type"] == "RuntimeError"
        assert "Something went wrong" in responses[0]["details"]["message"]

    def test_handler_returns_complex_types(self, socket_pair):
        """Test handler that returns various Python types."""
        server_sock, client_sock = socket_pair

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

        message = {"payload": {"test": "data"}, "route": {"steps": ["a"], "current": 0}}
        message_data = json.dumps(message).encode("utf-8")
        asya_runtime._send_msg(client_sock, message_data)

        responses = asya_runtime._handle_request(server_sock, complex_handler)

        assert len(responses) == 1
        assert responses[0]["payload"]["int"] == 42
        assert responses[0]["payload"]["float"] == 3.14
        assert responses[0]["payload"]["bool"] is True
        assert responses[0]["payload"]["null"] is None

    def test_handler_returns_large_response(self, socket_pair):
        """Test handler that returns a large response."""
        server_sock, client_sock = socket_pair

        def large_handler(payload):
            return {"data": "X" * (1024 * 1024)}

        def sender():
            message = {
                "payload": {"test": "data"},
                "route": {"steps": ["a"], "current": 0},
            }
            message_data = json.dumps(message).encode("utf-8")
            asya_runtime._send_msg(client_sock, message_data)

        sender_thread = threading.Thread(target=sender)
        sender_thread.start()

        responses = asya_runtime._handle_request(server_sock, large_handler)

        assert len(responses) == 1
        assert len(responses[0]["payload"]["data"]) == 1024 * 1024

        sender_thread.join()

    def test_message_with_special_characters(self, socket_pair):
        """Test messages with special JSON characters."""
        server_sock, client_sock = socket_pair

        def simple_handler(payload):
            return payload

        message = {
            "payload": {
                "text": 'Test "quotes" and \\backslashes\\ and \n newlines \t tabs'
            },
            "route": {"steps": ["a"], "current": 0},
        }
        message_data = json.dumps(message).encode("utf-8")
        asya_runtime._send_msg(client_sock, message_data)

        responses = asya_runtime._handle_request(server_sock, simple_handler)

        assert len(responses) == 1
        assert (
            responses[0]["payload"]["text"]
            == 'Test "quotes" and \\backslashes\\ and \n newlines \t tabs'
        )
