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
    # After test-echo processes, sidecar shifts the route:
    #   prev becomes ["test-echo"], curr becomes "test-verify", next becomes ["test-timeout"]
    message = {
        "id": "test-basic-001",
        "route": {"prev": [], "curr": "test-echo", "next": ["test-verify", "test-timeout"]},
        "payload": {"message": "hello"},
    }

    transport.publish("test-echo", message)
    result = transport.consume("test-verify", timeout=10)

    assert result is not None, "Message should reach test-verify queue"
    assert result["id"] == message["id"]
    # Echo handler transforms payload: {"message": X} → {"echoed": X}
    assert result["payload"] == {"echoed": "hello"}
    assert result["route"]["prev"] == ["test-echo"]
    assert result["route"]["curr"] == "test-verify"
    assert result["route"]["next"] == ["test-timeout"]


def test_sidecar_multi_actor_routing(transport):
    """Test sidecar routes message through multiple actors."""
    transport.purge("test-echo")
    transport.purge("test-verify")

    message = {
        "id": "test-multi-001",
        "route": {"prev": [], "curr": "test-echo", "next": ["test-echo", "test-verify"]},
        "payload": {"message": "multi-hop"},
    }

    transport.publish("test-echo", message)

    # First hop: test-echo (curr) → test-echo (next[0] becomes curr)
    # Second hop: test-echo (curr) → test-verify (next[0] becomes curr)
    result = transport.consume("test-verify", timeout=15)

    assert result is not None, "Message should complete multi-actor route"
    assert result["id"] == message["id"]
    assert result["route"]["prev"] == ["test-echo", "test-echo"]
    assert result["route"]["curr"] == "test-verify"
    assert result["route"]["next"] == []
