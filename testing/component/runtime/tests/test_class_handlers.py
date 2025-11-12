#!/usr/bin/env python3
"""
Runtime component tests - Class handlers.

Tests class-based stateful handlers with realistic scenarios:
- Slow model initialization (simulates AI model loading)
- State preservation across requests (caching, counters)
- Large payload handling
- Envelope mode with class handlers
"""

import json
import logging
import socket
import struct
import time

import pytest
from asya_testing.fixtures import configure_logging

configure_logging()

logger = logging.getLogger(__name__)


class SocketClient:
    """
    Mock sidecar client for testing runtime socket protocol.

    Reused from test_socket_protocol.py for consistency.
    """

    def __init__(self, socket_path: str):
        self.socket_path = socket_path

    def _recv_exact(self, sock, n: int) -> bytes:
        """Receive exactly n bytes from socket."""
        data = b""
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Socket closed before receiving all data")
            data += chunk
        return data

    def send_envelope(self, envelope: dict, timeout: int = 10) -> list:
        """Send envelope to runtime and receive response list."""
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)

        try:
            sock.connect(self.socket_path)

            # Send envelope with length prefix
            data = json.dumps(envelope).encode()
            length_prefix = struct.pack(">I", len(data))
            sock.sendall(length_prefix + data)

            # Receive response with length prefix
            response_length_bytes = self._recv_exact(sock, 4)
            response_length = struct.unpack(">I", response_length_bytes)[0]
            response_data = self._recv_exact(sock, response_length)

            return json.loads(response_data.decode())
        finally:
            sock.close()


@pytest.fixture
def slow_model_client():
    """Socket client for slow model runtime."""
    return SocketClient("/var/run/asya/slow-model.sock")


@pytest.fixture
def caching_client():
    """Socket client for caching runtime."""
    return SocketClient("/var/run/asya/caching.sock")


@pytest.fixture
def large_payload_class_client():
    """Socket client for large payload class runtime."""
    return SocketClient("/var/run/asya/large-payload-class.sock")


@pytest.fixture
def counter_client():
    """Socket client for counter runtime."""
    return SocketClient("/var/run/asya/counter.sock")


@pytest.fixture
def envelope_class_client():
    """Socket client for envelope mode class runtime."""
    return SocketClient("/var/run/asya/envelope-class.sock")


def test_slow_model_init_once(slow_model_client):
    """Test that slow model initialization happens only once."""
    # First request - should complete after ~2s init
    envelope1 = {
        "id": "test-001",
        "route": {"actors": ["slow-model"], "current": 0},
        "payload": {"test": "first"}
    }

    start = time.time()
    response1 = slow_model_client.send_envelope(envelope1)
    duration1 = time.time() - start

    assert isinstance(response1, list)
    assert len(response1) == 1
    result1 = response1[0]

    assert "payload" in result1
    assert result1["payload"]["call_count"] == 1
    init_time_1 = result1["payload"]["init_time"]

    # Should take at least 2 seconds for first call (init + processing)
    logger.info(f"First request took {duration1:.2f}s")

    # Second request - should be fast (no re-init)
    envelope2 = {
        "id": "test-002",
        "route": {"actors": ["slow-model"], "current": 0},
        "payload": {"test": "second"}
    }

    start = time.time()
    response2 = slow_model_client.send_envelope(envelope2)
    duration2 = time.time() - start

    assert isinstance(response2, list)
    assert len(response2) == 1
    result2 = response2[0]

    assert result2["payload"]["call_count"] == 2
    init_time_2 = result2["payload"]["init_time"]

    # Same instance - init_time should be identical
    assert init_time_1 == init_time_2, "Init should happen only once"

    # Second request should be fast
    assert duration2 < 1.0, f"Second request took {duration2:.2f}s, expected <1s"
    logger.info(f"Second request took {duration2:.2f}s (no re-init)")


def test_caching_state_preserved(caching_client):
    """Test that cache state is preserved across requests."""
    # Send 20 requests with 5 unique keys (lots of duplicates)
    keys = [f"key_{i % 5}" for i in range(20)]
    results = []

    for idx, key in enumerate(keys):
        envelope = {
            "id": f"test-{idx:03d}",
            "route": {"actors": ["caching"], "current": 0},
            "payload": {"key": key}
        }

        response = caching_client.send_envelope(envelope)
        assert len(response) == 1
        results.append(response[0]["payload"])

    # Final result should show cache statistics
    final_result = results[-1]

    # Should have 5 cache misses (one per unique key)
    assert final_result["cache_misses"] == 5, f"Expected 5 misses, got {final_result['cache_misses']}"

    # Should have 15 cache hits (20 total - 5 misses)
    assert final_result["cache_hits"] == 15, f"Expected 15 hits, got {final_result['cache_hits']}"

    # Cache size should be 5
    assert final_result["cache_size"] == 5, f"Expected cache size 5, got {final_result['cache_size']}"

    logger.info(f"Cache test: {final_result['cache_misses']} misses, {final_result['cache_hits']} hits")


def test_large_payload_stateful(large_payload_class_client):
    """Test large payload handling with stateful counter."""
    # Request 10MB payload
    envelope = {
        "id": "test-large-001",
        "route": {"actors": ["large-payload"], "current": 0},
        "payload": {"size_mb": 10}
    }

    response = large_payload_class_client.send_envelope(envelope, timeout=30)

    assert isinstance(response, list)
    assert len(response) == 1

    result = response[0]["payload"]

    # Verify size
    expected_size = 10 * 1024 * 1024
    assert result["size"] == expected_size
    assert len(result["data"]) == expected_size

    # Verify request counter (stateful)
    assert result["request_count"] == 1

    # Second request to verify state
    envelope2 = {
        "id": "test-large-002",
        "route": {"actors": ["large-payload"], "current": 0},
        "payload": {"size_mb": 1}
    }

    response2 = large_payload_class_client.send_envelope(envelope2, timeout=30)
    result2 = response2[0]["payload"]

    # Counter should increment
    assert result2["request_count"] == 2, "Request counter should persist across calls"

    logger.info(f"Large payload test: handled {expected_size} bytes, counter at {result2['request_count']}")


def test_counter_sequential_requests(counter_client):
    """Test that counter increments correctly across sequential requests."""
    num_requests = 10

    for i in range(num_requests):
        envelope = {
            "id": f"test-counter-{i:03d}",
            "route": {"actors": ["counter"], "current": 0},
            "payload": {"request_id": i}
        }

        response = counter_client.send_envelope(envelope)
        assert len(response) == 1

        result = response[0]["payload"]
        expected_count = i + 1

        assert result["count"] == expected_count, f"Expected count {expected_count}, got {result['count']}"
        assert result["total_requests"] == expected_count
        assert result["request_id"] == i

    logger.info(f"Counter test: {num_requests} sequential requests, final count: {num_requests}")


def test_envelope_mode_class_handler(envelope_class_client):
    """Test class handler in envelope mode."""
    envelope = {
        "id": "test-env-001",
        "route": {"actors": ["envelope-class"], "current": 0},
        "headers": {"trace_id": "test-trace-123"},
        "payload": {"value": 42}
    }

    response = envelope_class_client.send_envelope(envelope)

    assert isinstance(response, list)
    assert len(response) == 1

    result = response[0]

    # Verify payload structure
    assert "payload" in result
    assert result["payload"]["prefix"] == "processed"
    assert result["payload"]["trace_id"] == "test-trace-123"
    assert result["payload"]["data"]["value"] == 42
    assert result["payload"]["envelope_count"] == 1

    # Verify headers preserved
    assert result["headers"]["trace_id"] == "test-trace-123"

    # Second request to verify envelope counter increments
    envelope2 = {
        "id": "test-env-002",
        "route": {"actors": ["envelope-class"], "current": 0},
        "headers": {"trace_id": "test-trace-456"},
        "payload": {"value": 100}
    }

    response2 = envelope_class_client.send_envelope(envelope2)
    result2 = response2[0]

    assert result2["payload"]["envelope_count"] == 2, "Envelope counter should increment"
    assert result2["payload"]["trace_id"] == "test-trace-456"

    logger.info(f"Envelope mode test: processed {result2['payload']['envelope_count']} envelopes")


def test_class_handler_error_handling(caching_client):
    """Test that class handlers handle errors correctly."""
    # Send request with empty payload (will use default key)
    envelope = {
        "id": "test-error-001",
        "route": {"actors": ["caching"], "current": 0},
        "payload": {}
    }

    response = caching_client.send_envelope(envelope)

    assert isinstance(response, list)
    assert len(response) == 1

    result = response[0]

    # Should handle gracefully with default key
    assert "payload" in result
    assert result["payload"]["result"] == "computed_default"
    # Cache may have items from previous tests (proves state persistence!)
    assert result["payload"]["cache_size"] >= 1

    logger.info(f"Error handling test: handled empty payload with defaults, cache size: {result['payload']['cache_size']}")
