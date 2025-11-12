#!/usr/bin/env python3
"""
Sidecar component tests - routing behavior.

Tests sidecar message routing with testing runtimes:
- Basic routing (queue → sidecar → runtime → next queue)
- Multi-actor routing (message passes through multiple actors)

Note: Error and timeout handling are tested in integration tests where S3 persistence can be verified.
"""

import logging

import pytest

from asya_testing.fixtures import configure_logging
from asya_testing.fixtures.transport import transport_client

configure_logging()

logger = logging.getLogger(__name__)


# Use shared transport fixture from asya_testing
transport = transport_client


def test_sidecar_basic_routing(transport):
    """Test sidecar routes message from input queue through runtime to next queue."""
    transport.purge("test-echo")
    transport.purge("test-verify")

    # Route: test-echo → test-verify → test-timeout
    # After test-echo processes (current 0→1), sidecar routes to test-verify
    # test-verify has no consumer, so we can read the message there
    envelope = {
        "id": "test-basic-001",
        "route": {"actors": ["test-echo", "test-verify", "test-timeout"], "current": 0},
        "payload": {"message": "hello"},
    }

    transport.publish("test-echo", envelope)
    result = transport.consume("test-verify", timeout=10)

    assert result is not None, "Message should reach test-verify queue"
    assert result["id"] == envelope["id"]
    # Echo handler transforms payload: {"message": X} → {"echoed": X}
    assert result["payload"] == {"echoed": "hello"}
    assert result["route"]["current"] == 1


def test_sidecar_multi_actor_routing(transport):
    """Test sidecar routes message through multiple actors."""
    transport.purge("test-echo")
    transport.purge("test-verify")

    envelope = {
        "id": "test-multi-001",
        "route": {"actors": ["test-echo", "test-echo", "test-verify"], "current": 0},
        "payload": {"message": "multi-hop"},
    }

    transport.publish("test-echo", envelope)

    # First hop: test-echo (current=0) → test-echo (current=1)
    # Second hop: test-echo (current=1) → test-verify (current=2)
    result = transport.consume("test-verify", timeout=15)

    assert result is not None, "Message should complete multi-actor route"
    assert result["id"] == envelope["id"]
    assert result["route"]["current"] == 2
