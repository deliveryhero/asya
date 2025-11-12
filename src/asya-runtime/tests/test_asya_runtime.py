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
import textwrap
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest


# Add parent directory to path to import asya_runtime functions
sys.path.insert(0, str(Path(__file__).parent.parent))

import asya_runtime


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

        envelope = {
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
        }
        envelope_data = json.dumps(envelope).encode("utf-8")
        asya_runtime._send_envelope(client_sock, envelope_data)

        responses = asya_runtime._handle_request(server_sock, string_handler)

        # String is a valid payload type
        assert len(responses) == 1
        assert responses[0]["payload"] == "this is a string, not a dict"

    def test_handler_returns_number_payload_mode(self, socket_pair):
        """Test handler returning number in payload mode."""
        server_sock, client_sock = socket_pair

        def number_handler(payload):
            return 42

        envelope = {
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
        }
        envelope_data = json.dumps(envelope).encode("utf-8")
        asya_runtime._send_envelope(client_sock, envelope_data)

        responses = asya_runtime._handle_request(server_sock, number_handler)

        assert len(responses) == 1
        assert responses[0]["payload"] == 42

    def test_handler_returns_none_payload_mode(self, socket_pair):
        """Test handler returning None in payload mode (abort execution)."""
        server_sock, client_sock = socket_pair

        def none_handler(payload):
            return None

        envelope = {
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
        }
        envelope_data = json.dumps(envelope).encode("utf-8")
        asya_runtime._send_envelope(client_sock, envelope_data)

        responses = asya_runtime._handle_request(server_sock, none_handler)

        assert len(responses) == 0

    def test_handler_returns_empty_list(self, socket_pair):
        """Test handler returning empty list (no fan-out)."""
        server_sock, client_sock = socket_pair

        def empty_list_handler(payload):
            return []

        envelope = {
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
        }
        envelope_data = json.dumps(envelope).encode("utf-8")
        asya_runtime._send_envelope(client_sock, envelope_data)

        responses = asya_runtime._handle_request(server_sock, empty_list_handler)

        # Empty list means no output envelopes
        assert len(responses) == 0


class TestRouteValidation:
    """Test route validation edge cases."""

    def test_parse_msg_route_current_missing_defaults_to_zero(self):
        """Test route without current field - should default to 0."""
        data = json.dumps({"payload": {"test": "data"}, "route": {"actors": ["a", "b"]}}).encode("utf-8")
        msg = asya_runtime._parse_envelope_json(data)
        validated = asya_runtime._validate_envelope(msg)

        assert validated["route"]["current"] == 0
        assert validated["route"]["actors"] == ["a", "b"]

    def test_parse_msg_route_not_dict(self):
        """Test route as string instead of dict - should fail validation."""
        with pytest.raises(ValueError, match="Field 'route' must be a dict"):
            data = json.dumps({"payload": {"test": "data"}, "route": "not a dict"}).encode("utf-8")
            msg = asya_runtime._parse_envelope_json(data)
            asya_runtime._validate_envelope(msg)

    def test_parse_msg_route_missing_actors(self):
        """Test route without actors field - should fail validation."""
        with pytest.raises(ValueError, match="Missing required field 'actors' in route"):
            data = json.dumps({"payload": {"test": "data"}, "route": {"current": 0}}).encode("utf-8")
            msg = asya_runtime._parse_envelope_json(data)
            asya_runtime._validate_envelope(msg)

    def test_parse_msg_route_actors_not_list(self):
        """Test route with actors as non-list - should fail validation."""
        with pytest.raises(ValueError, match="Field 'route.actors' must be a list"):
            data = json.dumps({"payload": {"test": "data"}, "route": {"actors": "not a list"}}).encode("utf-8")
            msg = asya_runtime._parse_envelope_json(data)
            asya_runtime._validate_envelope(msg)

    def test_parse_msg_route_current_not_int(self):
        """Test route with current as non-integer - should fail validation."""
        with pytest.raises(ValueError, match="Field 'route.current' must be an integer"):
            data = json.dumps(
                {
                    "payload": {"test": "data"},
                    "route": {"actors": ["a", "b"], "current": "0"},
                }
            ).encode("utf-8")
            msg = asya_runtime._parse_envelope_json(data)
            asya_runtime._validate_envelope(msg)

    def test_parse_msg_route_current_negative(self):
        """Test route with negative current index - should fail validation."""
        with pytest.raises(ValueError, match="Invalid route.current=-1"):
            data = json.dumps({"payload": {"test": "data"}, "route": {"actors": ["a"], "current": -1}}).encode("utf-8")
            msg = asya_runtime._parse_envelope_json(data)
            asya_runtime._validate_envelope(msg)

    def test_parse_msg_route_current_out_of_bounds(self):
        """Test route with current index beyond actors length - should fail validation."""
        with pytest.raises(ValueError, match="Invalid route.current=10"):
            data = json.dumps(
                {
                    "payload": {"test": "data"},
                    "route": {"actors": ["a", "b"], "current": 10},
                }
            ).encode("utf-8")
            msg = asya_runtime._parse_envelope_json(data)
            asya_runtime._validate_envelope(msg)

    def test_parse_msg_route_empty_actors_current_zero(self):
        """Test route with empty actors array and current=0 - should fail validation."""
        with pytest.raises(ValueError, match="Field 'route.actors' cannot be empty"):
            data = json.dumps({"payload": {"test": "data"}, "route": {"actors": [], "current": 0}}).encode("utf-8")
            msg = asya_runtime._parse_envelope_json(data)
            asya_runtime._validate_envelope(msg)


class TestEnvelopeFieldPreservation:
    """Test that envelope fields are properly preserved through validation."""

    def test_validate_envelope_preserves_id_field(self):
        """Test that id field is preserved through validation."""
        envelope = {
            "id": "envelope-123",
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
        }
        validated = asya_runtime._validate_envelope(envelope)

        assert validated["id"] == "envelope-123"
        assert validated["payload"] == {"test": "data"}
        assert validated["route"] == {"actors": ["a"], "current": 0}

    def test_validate_envelope_preserves_parent_id_field(self):
        """Test that parent_id field is preserved through validation."""
        envelope = {
            "id": "envelope-456",
            "parent_id": "parent-envelope-123",
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
        }
        validated = asya_runtime._validate_envelope(envelope)

        assert validated["id"] == "envelope-456"
        assert validated["parent_id"] == "parent-envelope-123"
        assert validated["payload"] == {"test": "data"}

    def test_validate_envelope_preserves_all_fields(self):
        """Test that all envelope fields are preserved together."""
        envelope = {
            "id": "envelope-789",
            "parent_id": "parent-envelope-456",
            "payload": {"test": "data"},
            "route": {"actors": ["a", "b"], "current": 0},
            "headers": {"trace_id": "trace-123", "priority": "high"},
        }
        validated = asya_runtime._validate_envelope(envelope)

        assert validated["id"] == "envelope-789"
        assert validated["parent_id"] == "parent-envelope-456"
        assert validated["payload"] == {"test": "data"}
        assert validated["route"] == {"actors": ["a", "b"], "current": 0}
        assert validated["headers"] == {"trace_id": "trace-123", "priority": "high"}

    def test_validate_envelope_without_id_field(self):
        """Test that envelope without id field still validates (id is optional)."""
        envelope = {
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
        }
        validated = asya_runtime._validate_envelope(envelope)

        assert "id" not in validated
        assert validated["payload"] == {"test": "data"}

    def test_validate_envelope_id_field_invalid_type(self):
        """Test that id field with non-string type fails validation."""
        envelope = {
            "id": 12345,
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
        }
        with pytest.raises(ValueError, match="Field 'id' must be a string"):
            asya_runtime._validate_envelope(envelope)

    def test_envelope_mode_handler_accesses_id_field(self, socket_pair, mock_env):
        """Test that envelope mode handlers can access envelope id field."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def envelope_handler(envelope):
                envelope_id = envelope["id"]
                return {
                    "id": envelope_id,
                    "payload": {"envelope_id": envelope_id, "data": envelope["payload"]},
                    "route": envelope["route"],
                }

            envelope = {
                "id": "test-envelope-123",
                "payload": {"value": 42},
                "route": {"actors": ["a"], "current": 0},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, envelope_handler)

            assert len(responses) == 1
            assert responses[0]["id"] == "test-envelope-123"
            assert responses[0]["payload"]["envelope_id"] == "test-envelope-123"


class TestEnvelopeModeValidation:
    """Test envelope mode validation edge cases."""

    def test_handler_returns_invalid_payload_type_in_envelope(self, socket_pair, mock_env):
        """Test handler returns envelope with payload as string instead of dict."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def invalid_handler(msg):
                # Return envelope with payload as string
                return {"payload": "not a dict", "route": msg["route"]}

            envelope = {
                "payload": {"test": "data"},
                "route": {"actors": ["a"], "current": 0},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, invalid_handler)

            # Should work - payload can be any JSON type
            assert len(responses) == 1
            assert responses[0]["payload"] == "not a dict"

    def test_handler_returns_invalid_route_type_in_envelope(self, socket_pair, mock_env):
        """Test handler returns envelope with route as wrong type."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def invalid_handler(msg):
                # Return envelope with route as string
                return {"payload": {"ok": True}, "route": "invalid"}

            envelope = {
                "payload": {"test": "data"},
                "route": {"actors": ["a"], "current": 0},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, invalid_handler)

            # Should return error - route validation will fail
            assert len(responses) == 1
            assert responses[0]["error"] == "processing_error"
            assert "Field 'route' must be a dict" in responses[0]["details"]["message"]

    def test_handler_returns_list_with_invalid_envelope(self, socket_pair, mock_env):
        """Test handler returns list with one valid and one invalid envelope."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def mixed_handler(msg):
                return [
                    {"payload": {"id": 1}, "route": msg["route"]},
                    {"payload": {"id": 2}},  # Missing 'route'
                ]

            envelope = {
                "payload": {"test": "data"},
                "route": {"actors": ["a"], "current": 0},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, mixed_handler)

            # Should return error because second envelope is invalid
            assert len(responses) == 1
            assert responses[0]["error"] == "processing_error"
            assert "envelope[1/2]" in responses[0]["details"]["message"]

    def test_handler_changes_current_actor(self, socket_pair, mock_env):
        """Test that handler cannot change actor name at the current position."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def actor_changing_handler(msg):
                # Try to change the actor name at position 0 from "a" to "x"
                return {
                    "payload": msg["payload"],
                    "route": {"actors": ["x", "b", "c"], "current": 0},
                }

            envelope = {
                "payload": {"test": "data"},
                "route": {"actors": ["a", "b", "c"], "current": 0},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, actor_changing_handler)

            # Should return error - actor at position 0 changed from 'a' to 'x'
            assert len(responses) == 1
            assert responses[0]["error"] == "processing_error"
            # Can be caught by either "Route modification error" or "Route mismatch" validation
            assert "Route" in responses[0]["details"]["message"] and (
                "modification" in responses[0]["details"]["message"] or "mismatch" in responses[0]["details"]["message"]
            )
            assert "'a'" in responses[0]["details"]["message"]
            assert "'x'" in responses[0]["details"]["message"] or "['x']" in responses[0]["details"]["message"]

    def test_handler_modifies_route_but_keeps_current_actor(self, socket_pair, mock_env):
        """Test that handler can modify route actors as long as current actor stays same."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def route_modifying_handler(msg):
                # Add more actors but keep current pointing to same actor
                return {
                    "payload": msg["payload"],
                    "route": {"actors": ["a", "b", "c", "d"], "current": 0},
                }

            envelope = {
                "payload": {"test": "data"},
                "route": {"actors": ["a", "b"], "current": 0},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, route_modifying_handler)

            # Should work - current still points to 'a'
            assert len(responses) == 1
            assert responses[0]["route"]["actors"] == ["a", "b", "c", "d"]
            assert responses[0]["route"]["current"] == 0

    def test_handler_fanout_with_actor_validation(self, socket_pair, mock_env):
        """Test fan-out where all output envelopes maintain correct current actor."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def fanout_handler(msg):
                # Return multiple envelopes, all pointing to same current actor
                return [
                    {
                        "payload": {"id": 1},
                        "route": {"actors": ["a", "b"], "current": 0},
                    },
                    {
                        "payload": {"id": 2},
                        "route": {"actors": ["a", "b"], "current": 0},
                    },
                    {
                        "payload": {"id": 3},
                        "route": {"actors": ["a", "c"], "current": 0},
                    },
                ]

            envelope = {
                "payload": {"test": "data"},
                "route": {"actors": ["a", "b"], "current": 0},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, fanout_handler)

            # Should work - all output envelopes point to 'a' at index 0
            assert len(responses) == 3
            assert responses[0]["payload"] == {"id": 1}
            assert responses[1]["payload"] == {"id": 2}
            assert responses[2]["payload"] == {"id": 3}

    def test_handler_fanout_with_invalid_actor_name(self, socket_pair, mock_env):
        """Test fan-out where one envelope has changed actor name at current position."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def invalid_fanout_handler(msg):
                return [
                    {
                        "payload": {"id": 1},
                        "route": {"actors": ["a", "b"], "current": 0},
                    },
                    {
                        "payload": {"id": 2},
                        "route": {"actors": ["x", "b"], "current": 0},
                    },  # Wrong actor - changed "a" to "x" at position 0
                ]

            envelope = {
                "payload": {"test": "data"},
                "route": {"actors": ["a", "b"], "current": 0},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, invalid_fanout_handler)

            # Should return error for envelope[1]
            assert len(responses) == 1
            assert responses[0]["error"] == "processing_error"
            assert "envelope[1/2]" in responses[0]["details"]["message"]
            # Can be caught by either "Route modification error" or "Route mismatch" validation
            assert "Route" in responses[0]["details"]["message"] and (
                "modification" in responses[0]["details"]["message"] or "mismatch" in responses[0]["details"]["message"]
            )

    def test_handler_erases_processed_actors_first_actor(self, socket_pair, mock_env):
        """Test that handler cannot erase already-processed actors at first actor."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def erasing_handler(msg):
                # Try to return route that keeps current actor but erases it from position 0
                # Input: ["a", "b", "c"], current=0
                # Output: ["x", "a", "b"], current=1 - "a" is still current but moved
                return {
                    "payload": msg["payload"],
                    "route": {"actors": ["x", "a", "b"], "current": 1},
                }

            envelope = {
                "payload": {"test": "data"},
                "route": {"actors": ["a", "b", "c"], "current": 0},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, erasing_handler)

            # Should return error
            assert len(responses) == 1
            assert responses[0]["error"] == "processing_error"
            assert "Route modification error" in responses[0]["details"]["message"]
            assert "already-processed actors cannot be erased" in responses[0]["details"]["message"]

    def test_handler_erases_processed_actors_middle(self, socket_pair, mock_env):
        """Test that handler cannot erase already-processed actors in the middle."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def erasing_handler(msg):
                # Input: ["a", "b", "c"], current=2
                # Output: ["a", "c", "d"] - erases "b" which was already processed
                return {
                    "payload": msg["payload"],
                    "route": {"actors": ["a", "c", "d"], "current": 2},
                }

            envelope = {
                "payload": {"test": "data"},
                "route": {"actors": ["a", "b", "c"], "current": 2},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, erasing_handler)

            # Should return error
            assert len(responses) == 1
            assert responses[0]["error"] == "processing_error"
            assert "Route modification error" in responses[0]["details"]["message"]
            assert "['a', 'b', 'c']" in responses[0]["details"]["message"]

    def test_handler_modifies_one_processed_actor(self, socket_pair, mock_env):
        """Test that handler cannot modify an already-processed actor name."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def modifying_handler(msg):
                # Input: ["a", "b", "c"], current=1
                # Try to return ["a-modified", "b", "c", "d"]
                return {
                    "payload": msg["payload"],
                    "route": {"actors": ["a-modified", "b", "c", "d"], "current": 1},
                }

            envelope = {
                "payload": {"test": "data"},
                "route": {"actors": ["a", "b", "c"], "current": 1},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, modifying_handler)

            # Should return error - cannot modify actor "a"
            assert len(responses) == 1
            assert responses[0]["error"] == "processing_error"
            assert "Route modification error" in responses[0]["details"]["message"]

    def test_handler_adds_future_actors_preserves_prefix(self, socket_pair, mock_env):
        """Test that handler CAN add future actors if prefix is preserved."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def extending_handler(msg):
                # Input: ["a", "b", "c"], current=1
                # Return: ["a", "b", "c", "d", "e"] - adds "d" and "e"
                return {
                    "payload": msg["payload"],
                    "route": {"actors": ["a", "b", "c", "d", "e"], "current": 1},
                }

            envelope = {
                "payload": {"test": "data"},
                "route": {"actors": ["a", "b", "c"], "current": 1},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, extending_handler)

            # Should succeed
            assert len(responses) == 1
            assert responses[0]["route"]["actors"] == ["a", "b", "c", "d", "e"]
            assert responses[0]["route"]["current"] == 1

    def test_handler_replaces_future_actors(self, socket_pair, mock_env):
        """Test that handler CAN replace future actors (after current)."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def replacing_handler(msg):
                # Input: ["a", "b", "c", "d"], current=1
                # Return: ["a", "b", "x", "y"] - replaces "c", "d" with "x", "y"
                return {
                    "payload": msg["payload"],
                    "route": {"actors": ["a", "b", "x", "y"], "current": 1},
                }

            envelope = {
                "payload": {"test": "data"},
                "route": {"actors": ["a", "b", "c", "d"], "current": 1},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, replacing_handler)

            # Should succeed - can replace future actors
            assert len(responses) == 1
            assert responses[0]["route"]["actors"] == ["a", "b", "x", "y"]
            assert responses[0]["route"]["current"] == 1


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
        envelope = {
            "payload": {"data": large_data},
            "route": {"actors": ["a"], "current": 0},
        }
        envelope_data = json.dumps(envelope).encode("utf-8")

        responses_container = []

        def sender():
            asya_runtime._send_envelope(client_sock, envelope_data)

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

    def test_zero_length_envelope(self, socket_pair):
        """Test zero-length envelope."""
        server_sock, client_sock = socket_pair

        def simple_handler(payload):
            return payload

        # Send zero-length envelope (just length prefix = 0)
        asya_runtime._send_envelope(client_sock, b"")

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
        """Test connection closed while reading envelope data."""
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
            ASYA_CHUNK_SIZE="8192",
        ):
            assert asya_runtime.ASYA_HANDLER_MODE == "envelope"
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

    def test_send_envelope(self, socket_pair):
        """Test send_msg function."""
        server_sock, client_sock = socket_pair

        test_data = b"Test envelope with length prefix"
        asya_runtime._send_envelope(client_sock, test_data)

        length_bytes = asya_runtime._recv_exact(server_sock, 4)
        length = struct.unpack(">I", length_bytes)[0]
        assert length == len(test_data)

        received = asya_runtime._recv_exact(server_sock, length)
        assert received == test_data

    @pytest.mark.parametrize("size_kb", [10, 1024, 10 * 1024, 100 * 1024])
    def test_send_recv_large_envelope(self, socket_pair, size_kb):
        """Test send/recv with large envelope."""
        server_sock, client_sock = socket_pair

        test_data = b"X" * (size_kb * 1024)

        def sender():
            asya_runtime._send_envelope(client_sock, test_data)

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
            assert permissions == "666"

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
    """Test _parse_envelope_json and _validate_envelope functions."""

    def test_parse_msg_with_payload_and_route(self):
        """Test parsing envelope with both payload and route."""
        data = json.dumps({"payload": {"test": "data"}, "route": {"actors": ["a", "b"], "current": 0}}).encode("utf-8")

        msg = asya_runtime._parse_envelope_json(data)
        msg = asya_runtime._validate_envelope(msg)

        assert msg["payload"] == {"test": "data"}
        assert msg["route"] == {"actors": ["a", "b"], "current": 0}

    def test_parse_msg_missing_payload(self):
        """Test parsing envelope without payload field."""
        with pytest.raises(ValueError, match="Missing required .*payload"):
            data = json.dumps({"route": {"actors": ["a"], "current": 0}}).encode("utf-8")
            msg = asya_runtime._parse_envelope_json(data)
            asya_runtime._validate_envelope(msg)

    def test_parse_msg_missing_route(self):
        """Test parsing envelope without route field."""
        with pytest.raises(ValueError, match="Missing required .*route"):
            data = json.dumps({"payload": {"test": "data"}}).encode("utf-8")
            msg = asya_runtime._parse_envelope_json(data)
            asya_runtime._validate_envelope(msg)

    @pytest.mark.parametrize("payload", [None, {}])
    def test_parse_msg_empty_payload(self, payload):
        """Test parsing envelope with null/empty payload."""
        data = json.dumps({"payload": payload, "route": {"actors": ["a"], "current": 0}}).encode("utf-8")

        msg = asya_runtime._parse_envelope_json(data)
        msg = asya_runtime._validate_envelope(msg)

        assert msg["payload"] == payload
        assert msg["route"] == {"actors": ["a"], "current": 0}

    def test_parse_msg_invalid_json(self):
        """Test parsing invalid JSON."""
        with pytest.raises(json.JSONDecodeError):
            asya_runtime._parse_envelope_json(b"not json{")

    def test_parse_msg_invalid_utf8(self):
        """Test parsing invalid UTF-8."""
        with pytest.raises(UnicodeDecodeError):
            asya_runtime._parse_envelope_json(b"\xff\xfe invalid utf8")


class TestErrorDict:
    """Test _error_dict function."""

    def test_error_dict_basic(self):
        """Test error dict with just error code."""
        errs = asya_runtime._error_response("test_error")
        assert errs == [{"error": "test_error"}]

    def test_error_dict_with_exception(self):
        """Test error dict with exception details."""
        try:
            raise ValueError("Test exception envelope")
        except ValueError as e:
            errs = asya_runtime._error_response("processing_error", e)
            assert len(errs) == 1
            err = errs[0]
            assert err["error"] == "processing_error"
            assert err["details"]["message"] == "Test exception envelope"
            assert err["details"]["type"] == "ValueError"
            assert "traceback" in err["details"]
            assert "ValueError" in err["details"]["traceback"]


class TestHandleRequestPayloadMode:
    """Test _handle_request in payload mode (ASYA_HANDLER_MODE=payload)."""

    def test_handle_request_success_single_output(self, socket_pair, mock_env):
        """Test successful request with single output."""
        with mock_env(ASYA_HANDLER_MODE="payload"):
            server_sock, client_sock = socket_pair

            def simple_handler(payload):
                return {"result": payload["value"] * 2}

            envelope = {
                "route": {"actors": ["actor1"], "current": 0},
                "payload": {"value": 42},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, simple_handler)

            assert len(responses) == 1
            assert responses[0]["payload"] == {"result": 84}
            # Payload mode auto-increments current
            assert responses[0]["route"] == {"actors": ["actor1"], "current": 1}

    def test_handle_request_multi_actor_route(self, socket_pair, mock_env):
        """Test that payload mode increments current for multi-actor pipelines."""
        with mock_env(ASYA_HANDLER_MODE="payload"):
            server_sock, client_sock = socket_pair

            def pipeline_handler(payload):
                return {"doubled": payload["value"] * 2}

            # Envelope for actor at index 0 in a 3-actor pipeline
            envelope = {
                "route": {"actors": ["doubler", "incrementer", "finalizer"], "current": 0},
                "payload": {"value": 21},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, pipeline_handler)

            assert len(responses) == 1
            assert responses[0]["payload"] == {"doubled": 42}
            # Current should be incremented to point to next actor
            assert responses[0]["route"]["current"] == 1
            assert responses[0]["route"]["actors"] == ["doubler", "incrementer", "finalizer"]

    def test_handle_request_fanout_list_output(self, socket_pair, mock_env):
        """Test fan-out with list output in payload mode."""
        with mock_env(ASYA_HANDLER_MODE="payload"):
            server_sock, client_sock = socket_pair

            def fanout_handler(payload):
                # Return a list of payloads
                return [{"id": 1}, {"id": 2}, {"id": 3}]

            envelope = {
                "route": {"actors": ["fan"], "current": 0},
                "payload": {"test": "data"},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, fanout_handler)

            assert len(responses) == 3
            assert responses[0]["payload"] == {"id": 1}
            assert responses[1]["payload"] == {"id": 2}
            assert responses[2]["payload"] == {"id": 3}
            # All should have incremented current (payload mode auto-increments)
            for resp in responses:
                assert resp["route"] == {"actors": ["fan"], "current": 1}


class TestHandleRequestEnvelopeMode:
    """Test _handle_request in envelope mode (ASYA_HANDLER_MODE=envelope)."""

    def test_handle_request_success_single_output(self, socket_pair, mock_env):
        """Test successful request with single output in envelope mode."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def envelope_handler(msg):
                return {
                    "payload": {"result": msg["payload"]["value"] * 2},
                    "route": msg["route"],
                }

            envelope = {
                "route": {"actors": ["actor1"], "current": 0},
                "payload": {"value": 42},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, envelope_handler)

            assert len(responses) == 1
            assert responses[0]["payload"] == {"result": 84}
            assert responses[0]["route"] == {"actors": ["actor1"], "current": 0}

    def test_handle_request_route_modification(self, socket_pair, mock_env):
        """Test that handler can modify route in envelope mode."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def route_modifying_handler(msg):
                new_route = msg["route"].copy()
                new_route["actors"] = msg["route"]["actors"] + ["modified"]
                new_route["current"] = 0  # Must keep current pointing to same actor
                return {"payload": msg["payload"], "route": new_route}

            envelope = {
                "route": {"actors": ["actor1"], "current": 0},
                "payload": {"data": "test"},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, route_modifying_handler)

            assert len(responses) == 1
            assert responses[0]["route"]["actors"] == ["actor1", "modified"]
            assert responses[0]["route"]["current"] == 0

    def test_handle_request_fanout_list_output(self, socket_pair, mock_env):
        """Test fan-out with list output in envelope mode."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def fanout_handler(msg):
                return [
                    {"payload": {"id": 1}, "route": msg["route"]},
                    {"payload": {"id": 2}, "route": msg["route"]},
                    {"payload": {"id": 3}, "route": msg["route"]},
                ]

            envelope = {
                "route": {"actors": ["fan"], "current": 0},
                "payload": {"test": "data"},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, fanout_handler)

            assert len(responses) == 3
            assert responses[0]["payload"] == {"id": 1}
            assert responses[1]["payload"] == {"id": 2}
            assert responses[2]["payload"] == {"id": 3}

    def test_handle_request_invalid_output_missing_keys(self, socket_pair, mock_env):
        """Test that handler output is validated for required keys."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def invalid_handler(msg):
                # Missing 'route' key
                return {"payload": {"test": "data"}}

            envelope = {
                "route": {"actors": ["actor1"], "current": 0},
                "payload": {"test": "data"},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, invalid_handler)

            assert len(responses) == 1
            assert responses[0]["error"] == "processing_error"
            assert "Missing required field 'route'" in responses[0]["details"]["message"]

    def test_handle_request_invalid_output_list_missing_keys(self, socket_pair, mock_env):
        """Test that handler list output is validated for required keys."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def invalid_fanout_handler(msg):
                return [
                    {"payload": {"id": 1}, "route": msg["route"]},
                    {"payload": {"id": 2}},  # Missing 'route'
                ]

            envelope = {
                "route": {"actors": ["actor1"], "current": 0},
                "payload": {"test": "data"},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, invalid_fanout_handler)

            assert len(responses) == 1
            assert responses[0]["error"] == "processing_error"
            assert "envelope[1/2]" in responses[0]["details"]["message"]


class TestHandleRequestErrorCases:
    """Test error handling in _handle_request."""

    def test_handle_request_invalid_json(self, socket_pair):
        """Test handling of invalid JSON."""
        server_sock, client_sock = socket_pair

        def simple_handler(payload):
            return payload

        invalid_data = b"not valid json{"
        asya_runtime._send_envelope(client_sock, invalid_data)

        responses = asya_runtime._handle_request(server_sock, simple_handler)

        assert len(responses) == 1
        assert responses[0]["error"] == "msg_parsing_error"
        assert "details" in responses[0]

    def test_handle_request_handler_exception(self, socket_pair):
        """Test handling of handler exceptions."""
        server_sock, client_sock = socket_pair

        def failing_handler(payload):
            raise ValueError("Handler failed")

        envelope = {
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
        }
        envelope_data = json.dumps(envelope).encode("utf-8")
        asya_runtime._send_envelope(client_sock, envelope_data)

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

    def test_handle_request_generic_exception(self, socket_pair, mock_env):
        """Test handling when an unexpected exception occurs during validation."""
        server_sock, client_sock = socket_pair

        def simple_handler(payload):
            return payload

        envelope = {
            "route": {"actors": ["actor1"], "current": 0},
            "payload": {"test": "data"},
        }
        envelope_data = json.dumps(envelope).encode("utf-8")
        asya_runtime._send_envelope(client_sock, envelope_data)

        with mock_env(ASYA_HANDLER_MODE="unexpected-value"):
            responses = asya_runtime._handle_request(server_sock, simple_handler)

            # Invalid ASYA_HANDLER_MODE causes parsing/validation error
            assert len(responses) == 1
            assert responses[0]["error"] in ("processing_error", "msg_parsing_error")


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

    def test_class_handler_state_preserved_across_calls(self, socket_pair, mock_env, tmp_path):
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
                server_sock, client_sock = socket_pair
                handler = asya_runtime._load_function()

                # First call
                envelope1 = {
                    "payload": {"value": 10},
                    "route": {"actors": ["a"], "current": 0},
                }
                asya_runtime._send_envelope(client_sock, json.dumps(envelope1).encode())
                responses1 = asya_runtime._handle_request(server_sock, handler)

                assert len(responses1) == 1
                assert responses1[0]["payload"]["calls"] == 1
                assert responses1[0]["payload"]["total"] == 10

                # Second call
                envelope2 = {
                    "payload": {"value": 20},
                    "route": {"actors": ["a"], "current": 0},
                }
                asya_runtime._send_envelope(client_sock, json.dumps(envelope2).encode())
                responses2 = asya_runtime._handle_request(server_sock, handler)

                assert len(responses2) == 1
                assert responses2[0]["payload"]["calls"] == 2
                assert responses2[0]["payload"]["total"] == 30

        finally:
            sys.path.pop(0)

    def test_class_handler_payload_mode(self, socket_pair, mock_env, tmp_path):
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
                server_sock, client_sock = socket_pair
                handler = asya_runtime._load_function()

                envelope = {
                    "payload": {"value": 21},
                    "route": {"actors": ["a"], "current": 0},
                }
                asya_runtime._send_envelope(client_sock, json.dumps(envelope).encode())
                responses = asya_runtime._handle_request(server_sock, handler)

                assert len(responses) == 1
                assert responses[0]["payload"]["result"] == 42

        finally:
            sys.path.pop(0)

    def test_class_handler_envelope_mode(self, socket_pair, mock_env, tmp_path):
        """Test class handler in envelope mode."""
        test_module = tmp_path / "envelope_class.py"
        test_module.write_text(
            textwrap.dedent("""
            class EnvelopeProcessor:
                def __init__(self):
                    self.prefix = "processed"

                def process(self, envelope):
                    return {
                        "payload": {"prefix": self.prefix, "data": envelope["payload"]},
                        "route": envelope["route"],
                        "headers": envelope.get("headers", {}),
                    }
            """)
        )

        sys.path.insert(0, str(tmp_path))
        try:
            with mock_env(ASYA_HANDLER="envelope_class.EnvelopeProcessor.process", ASYA_HANDLER_MODE="envelope"):
                server_sock, client_sock = socket_pair
                handler = asya_runtime._load_function()

                envelope = {
                    "payload": {"value": 100},
                    "route": {"actors": ["a"], "current": 0},
                    "headers": {"trace_id": "123"},
                }
                asya_runtime._send_envelope(client_sock, json.dumps(envelope).encode())
                responses = asya_runtime._handle_request(server_sock, handler)

                assert len(responses) == 1
                assert responses[0]["payload"]["prefix"] == "processed"
                assert responses[0]["payload"]["data"]["value"] == 100
                assert responses[0]["headers"]["trace_id"] == "123"

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

    def test_class_handler_fanout_payload_mode(self, socket_pair, mock_env, tmp_path):
        """Test class handler returning list in payload mode."""
        test_module = tmp_path / "fanout_class.py"
        test_module.write_text(
            textwrap.dedent("""
            class FanoutProcessor:
                def __init__(self):
                    self.count = 3

                def process(self, payload):
                    return [{"id": i, "input": payload} for i in range(self.count)]
            """)
        )

        sys.path.insert(0, str(tmp_path))
        try:
            with mock_env(ASYA_HANDLER="fanout_class.FanoutProcessor.process"):
                server_sock, client_sock = socket_pair
                handler = asya_runtime._load_function()

                envelope = {
                    "payload": {"value": 42},
                    "route": {"actors": ["fan"], "current": 0},
                }
                asya_runtime._send_envelope(client_sock, json.dumps(envelope).encode())
                responses = asya_runtime._handle_request(server_sock, handler)

                assert len(responses) == 3
                assert responses[0]["payload"]["id"] == 0
                assert responses[1]["payload"]["id"] == 1
                assert responses[2]["payload"]["id"] == 2

        finally:
            sys.path.pop(0)

    def test_class_handler_returns_none(self, socket_pair, mock_env, tmp_path):
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
                server_sock, client_sock = socket_pair
                handler = asya_runtime._load_function()

                envelope = {
                    "payload": {"value": 42},
                    "route": {"actors": ["a"], "current": 0},
                }
                asya_runtime._send_envelope(client_sock, json.dumps(envelope).encode())
                responses = asya_runtime._handle_request(server_sock, handler)

                assert len(responses) == 0

        finally:
            sys.path.pop(0)

    def test_class_handler_validation_disabled(self, socket_pair, mock_env, tmp_path):
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
                server_sock, client_sock = socket_pair
                handler = asya_runtime._load_function()

                envelope = {
                    "payload": {"value": 23},
                    "route": {"actors": ["a"], "current": 0},
                }
                asya_runtime._send_envelope(client_sock, json.dumps(envelope).encode())
                responses = asya_runtime._handle_request(server_sock, handler)

                assert len(responses) == 1
                assert responses[0]["payload"]["result"] == 123

        finally:
            sys.path.pop(0)

    def test_class_handler_with_complex_state(self, socket_pair, mock_env, tmp_path):
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
                server_sock, client_sock = socket_pair
                handler = asya_runtime._load_function()

                # First call
                envelope1 = {
                    "payload": {"value": 100},
                    "route": {"actors": ["a"], "current": 0},
                }
                asya_runtime._send_envelope(client_sock, json.dumps(envelope1).encode())
                responses1 = asya_runtime._handle_request(server_sock, handler)

                assert responses1[0]["payload"]["stats"]["calls"] == 1
                assert responses1[0]["payload"]["stats"]["cache_hits"] == 0
                assert responses1[0]["payload"]["in_cache"]

                # Second call with same value
                envelope2 = {
                    "payload": {"value": 100},
                    "route": {"actors": ["a"], "current": 0},
                }
                asya_runtime._send_envelope(client_sock, json.dumps(envelope2).encode())
                responses2 = asya_runtime._handle_request(server_sock, handler)

                assert responses2[0]["payload"]["stats"]["calls"] == 2
                assert responses2[0]["payload"]["stats"]["cache_hits"] == 1

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

    def test_send_envelope_empty_data(self, socket_pair):
        """Test send_msg with empty data."""
        server_sock, client_sock = socket_pair

        asya_runtime._send_envelope(client_sock, b"")

        length_bytes = asya_runtime._recv_exact(server_sock, 4)
        length = struct.unpack(">I", length_bytes)[0]
        assert length == 0

    def test_handle_request_unicode_content(self, socket_pair):
        """Test handling of unicode content."""
        server_sock, client_sock = socket_pair

        def simple_handler(payload):
            return payload

        envelope = {
            "payload": {"text": "Hello 世界 こんにちは"},
            "route": {"actors": ["a"], "current": 0},
        }
        envelope_data = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
        asya_runtime._send_envelope(client_sock, envelope_data)

        responses = asya_runtime._handle_request(server_sock, simple_handler)

        assert len(responses) == 1
        assert responses[0]["payload"]["text"] == "Hello 世界 こんにちは"

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

        envelope = {"payload": nested, "route": {"actors": ["a"], "current": 0}}
        envelope_data = json.dumps(envelope).encode("utf-8")
        asya_runtime._send_envelope(client_sock, envelope_data)

        responses = asya_runtime._handle_request(server_sock, simple_handler)

        assert len(responses) == 1
        assert responses[0]["payload"]["level"] == 0

    def test_handle_request_null_payload(self, socket_pair):
        """Test handling of null payload."""
        server_sock, client_sock = socket_pair

        def simple_handler(payload):
            return payload if payload is not None else {"default": True}

        envelope = {"payload": None, "route": {"actors": ["a"], "current": 0}}
        envelope_data = json.dumps(envelope).encode("utf-8")
        asya_runtime._send_envelope(client_sock, envelope_data)

        responses = asya_runtime._handle_request(server_sock, simple_handler)

        assert len(responses) == 1
        assert responses[0]["payload"] == {"default": True}

    def test_handler_raises_runtime_error(self, socket_pair):
        """Test handler that raises RuntimeError."""
        server_sock, client_sock = socket_pair

        def error_handler(payload):
            raise RuntimeError("Something went wrong")

        envelope = {
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
        }
        envelope_data = json.dumps(envelope).encode("utf-8")
        asya_runtime._send_envelope(client_sock, envelope_data)

        responses = asya_runtime._handle_request(server_sock, error_handler)

        assert len(responses) == 1
        response_error: str | None = responses[0].get("error")
        response_details: dict = responses[0].get("details", {})
        assert response_error == "processing_error"
        assert response_details.get("type") == "RuntimeError"
        assert "Something went wrong" in str(response_details.get("message", ""))

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

        envelope = {
            "payload": {"test": "data"},
            "route": {"actors": ["a"], "current": 0},
        }
        envelope_data = json.dumps(envelope).encode("utf-8")
        asya_runtime._send_envelope(client_sock, envelope_data)

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
            envelope = {
                "payload": {"test": "data"},
                "route": {"actors": ["a"], "current": 0},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

        sender_thread = threading.Thread(target=sender)
        sender_thread.start()

        responses = asya_runtime._handle_request(server_sock, large_handler)

        assert len(responses) == 1
        assert len(responses[0]["payload"]["data"]) == 1024 * 1024

        sender_thread.join()

    def test_envelope_with_special_characters(self, socket_pair):
        """Test envelopes with special JSON characters."""
        server_sock, client_sock = socket_pair

        def simple_handler(payload):
            return payload

        envelope = {
            "payload": {"text": 'Test "quotes" and \\backslashes\\ and \n newlines \t tabs'},
            "route": {"actors": ["a"], "current": 0},
        }
        envelope_data = json.dumps(envelope).encode("utf-8")
        asya_runtime._send_envelope(client_sock, envelope_data)

        responses = asya_runtime._handle_request(server_sock, simple_handler)

        assert len(responses) == 1
        assert responses[0]["payload"]["text"] == 'Test "quotes" and \\backslashes\\ and \n newlines \t tabs'


class TestHeadersPreservation:
    """Test that headers field is properly preserved through envelope processing."""

    def test_headers_preserved_in_payload_mode(self, socket_pair):
        """Test that headers are preserved when using payload mode."""
        server_sock, client_sock = socket_pair

        def simple_handler(payload):
            return {"result": payload["value"] * 2}

        envelope = {
            "payload": {"value": 42},
            "route": {"actors": ["doubler"], "current": 0},
            "headers": {"trace_id": "abc-123", "priority": "high"},
        }
        envelope_data = json.dumps(envelope).encode("utf-8")
        asya_runtime._send_envelope(client_sock, envelope_data)

        responses = asya_runtime._handle_request(server_sock, simple_handler)

        assert len(responses) == 1
        assert responses[0]["payload"] == {"result": 84}
        assert responses[0]["headers"] == {"trace_id": "abc-123", "priority": "high"}
        # Payload mode auto-increments current
        assert responses[0]["route"] == {"actors": ["doubler"], "current": 1}

    def test_headers_preserved_in_fanout_payload_mode(self, socket_pair):
        """Test that headers are preserved in fanout with payload mode."""
        server_sock, client_sock = socket_pair

        def fanout_handler(payload):
            return [{"id": 1}, {"id": 2}]

        envelope = {
            "payload": {"test": "data"},
            "route": {"actors": ["fan"], "current": 0},
            "headers": {"correlation_id": "xyz-789"},
        }
        envelope_data = json.dumps(envelope).encode("utf-8")
        asya_runtime._send_envelope(client_sock, envelope_data)

        responses = asya_runtime._handle_request(server_sock, fanout_handler)

        assert len(responses) == 2
        assert responses[0]["payload"] == {"id": 1}
        assert responses[0]["headers"] == {"correlation_id": "xyz-789"}
        assert responses[1]["payload"] == {"id": 2}
        assert responses[1]["headers"] == {"correlation_id": "xyz-789"}

    def test_headers_optional_in_payload_mode(self, socket_pair):
        """Test that headers are optional and don't break processing."""
        server_sock, client_sock = socket_pair

        def simple_handler(payload):
            return payload

        envelope = {
            "payload": {"test": "data"},
            "route": {"actors": ["echo"], "current": 0},
        }
        envelope_data = json.dumps(envelope).encode("utf-8")
        asya_runtime._send_envelope(client_sock, envelope_data)

        responses = asya_runtime._handle_request(server_sock, simple_handler)

        assert len(responses) == 1
        assert responses[0]["payload"] == {"test": "data"}
        assert "headers" not in responses[0]

    def test_headers_preserved_in_envelope_mode(self, socket_pair, mock_env):
        """Test that headers are preserved when using envelope mode."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def envelope_handler(msg):
                return msg

            envelope = {
                "payload": {"value": 100},
                "route": {"actors": ["passthrough"], "current": 0},
                "headers": {"request_id": "req-456"},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, envelope_handler)

            assert len(responses) == 1
            assert responses[0]["payload"] == {"value": 100}
            assert responses[0]["headers"] == {"request_id": "req-456"}

    def test_headers_validation_invalid_type(self, socket_pair):
        """Test that headers validation rejects non-dict types."""
        server_sock, client_sock = socket_pair

        def simple_handler(payload):
            return payload

        envelope = {
            "payload": {"test": "data"},
            "route": {"actors": ["echo"], "current": 0},
            "headers": "this should be a dict, not a string",
        }
        envelope_data = json.dumps(envelope).encode("utf-8")
        asya_runtime._send_envelope(client_sock, envelope_data)

        responses = asya_runtime._handle_request(server_sock, simple_handler)

        assert len(responses) == 1
        assert responses[0]["error"] == "msg_parsing_error"
        assert "Field 'headers' must be a dict" in responses[0]["details"]["message"]


class TestEnvelopeMode:
    """Test ASYA_HANDLER_MODE=envelope mode."""

    def test_envelope_mode_basic(self, socket_pair, mock_env):
        """Test envelope mode with basic handler."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def envelope_handler(envelope):
                return envelope

            envelope = {
                "payload": {"value": 123},
                "route": {"actors": ["passthrough"], "current": 0},
                "headers": {"trace_id": "test-123"},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, envelope_handler)

            assert len(responses) == 1
            assert responses[0]["payload"] == {"value": 123}
            assert responses[0]["headers"] == {"trace_id": "test-123"}
            assert responses[0]["route"] == {"actors": ["passthrough"], "current": 0}

    def test_envelope_mode_headers_access(self, socket_pair, mock_env):
        """Test that envelope mode gives access to headers."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def headers_reader(envelope):
                priority = envelope.get("headers", {}).get("priority", "low")
                return {
                    "payload": {
                        "priority": priority,
                        "value": envelope["payload"]["value"],
                    },
                    "route": envelope["route"],
                    "headers": envelope.get("headers", {}),
                }

            envelope = {
                "payload": {"value": 42},
                "route": {"actors": ["processor"], "current": 0},
                "headers": {"priority": "high", "trace_id": "xyz"},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, headers_reader)

            assert len(responses) == 1
            assert responses[0]["payload"] == {"priority": "high", "value": 42}
            assert responses[0]["headers"] == {"priority": "high", "trace_id": "xyz"}

    def test_envelope_mode_fanout(self, socket_pair, mock_env):
        """Test envelope mode with fanout."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def fanout_handler(envelope):
                return [
                    {
                        "payload": {"id": 1},
                        "route": envelope["route"],
                        "headers": envelope.get("headers", {}),
                    },
                    {
                        "payload": {"id": 2},
                        "route": envelope["route"],
                        "headers": envelope.get("headers", {}),
                    },
                ]

            envelope = {
                "payload": {"test": "data"},
                "route": {"actors": ["fan"], "current": 0},
                "headers": {"correlation_id": "abc"},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, fanout_handler)

            assert len(responses) == 2
            assert responses[0]["payload"] == {"id": 1}
            assert responses[0]["headers"] == {"correlation_id": "abc"}
            assert responses[1]["payload"] == {"id": 2}
            assert responses[1]["headers"] == {"correlation_id": "abc"}

    def test_envelope_mode_validation(self, socket_pair, mock_env):
        """Test envelope mode output validation."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def invalid_handler(envelope):
                return {"payload": {"result": "ok"}}  # Missing route

            envelope = {
                "payload": {"test": "data"},
                "route": {"actors": ["processor"], "current": 0},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, invalid_handler)

            assert len(responses) == 1
            assert responses[0]["error"] == "processing_error"
            assert "Missing required field 'route'" in responses[0]["details"]["message"]

    def test_envelope_mode_returns_none(self, socket_pair, mock_env):
        """Test envelope mode handler returning None."""
        with mock_env(ASYA_HANDLER_MODE="envelope"):
            server_sock, client_sock = socket_pair

            def none_handler(envelope):
                return None

            envelope = {
                "payload": {"test": "data"},
                "route": {"actors": ["processor"], "current": 0},
            }
            envelope_data = json.dumps(envelope).encode("utf-8")
            asya_runtime._send_envelope(client_sock, envelope_data)

            responses = asya_runtime._handle_request(server_sock, none_handler)

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
    """Test _setup_socket error handling."""

    def test_setup_socket_file_exists_and_is_directory(self, tmp_path):
        """Test socket setup when path exists as directory."""
        socket_path = tmp_path / "socket"
        socket_path.mkdir()

        with pytest.raises(OSError):
            asya_runtime._setup_socket(str(socket_path))


class TestConnectionErrors:
    """Test connection error handling in _handle_request."""

    def test_handle_request_recv_exact_error_path(self, socket_pair, monkeypatch):
        """Test error path when _recv_exact raises a generic exception."""
        server_sock, client_sock = socket_pair

        def mock_recv_exact(sock, n):
            raise RuntimeError("Unexpected error in recv_exact")

        monkeypatch.setattr(asya_runtime, "_recv_exact", mock_recv_exact)

        def dummy_handler(payload):
            return {"result": "ok"}

        responses = asya_runtime._handle_request(server_sock, dummy_handler)

        assert len(responses) == 1
        assert responses[0]["error"] == "connection_error"
        assert "Unexpected error in recv_exact" in str(responses[0]["details"])
