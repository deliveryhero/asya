#!/usr/bin/env python3
"""
Integration tests for the x-asya-route-override feature.

Tests the sidecar's ability to override routing targets at the header level,
verifying that messages are routed to alternate actor queues when override
headers are present, that normal routing works without overrides, and that
the x-asya-route-resolved audit trail is stamped correctly.
"""

import json
import logging

from asya_testing.config import get_env

log_level = get_env('ASYA_LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_route_override_routes_to_alternate_queue(transport_helper):
    """Test that x-asya-route-override routes messages to the override target queue.

    Pipeline: test-echo -> echo-v2-target (overridden to test-echo-v2) -> x-sink

    The override header maps the logical actor name 'echo-v2-target' to the
    physical actor 'test-echo-v2'. The test-echo sidecar applies the override
    when routing to the next actor, and the test-echo-v2 sidecar bypasses
    identity validation because the override maps route.curr to its own name.
    """
    transport_helper.purge_queue("asya-default-x-sink")

    envelope = {
        "id": "test-route-override-1",
        "route": {
            "prev": [],
            "curr": "test-echo",
            "next": ["echo-v2-target"],
        },
        "headers": {
            "x-asya-route-override": {
                "echo-v2-target": "test-echo-v2",
            },
        },
        "payload": {"test": "route_override", "data": "override_target"},
    }
    logger.info(f"Publishing envelope with route override: {json.dumps(envelope, indent=2)}")

    transport_helper.publish_envelope("asya-default-test-echo", envelope)
    logger.info("Envelope published, waiting for result in x-sink...")

    result = transport_helper.assert_envelope_in_queue("asya-default-x-sink", timeout=30)
    logger.info(f"Result from x-sink: {json.dumps(result, indent=2) if result else 'None'}")
    assert result is not None, "No message in x-sink queue after route override"

    payload = result.get("payload", {})
    assert payload.get("test") == "route_override", f"Payload not echoed correctly, got: {payload}"
    assert payload.get("data") == "override_target", f"Payload data missing, got: {payload}"

    # Verify route shows the message traversed both actors
    route = result.get("route", {})
    logger.info(f"Final route: {route}")
    assert "test-echo" in route.get("prev", []), (
        f"test-echo should be in prev, got: {route.get('prev')}"
    )
    logger.info("=== test_route_override_routes_to_alternate_queue: PASSED ===\n")


def test_no_override_normal_routing(transport_helper):
    """Test that without override headers, normal routing occurs.

    Pipeline: test-echo -> test-echo-v2 -> x-sink

    Without x-asya-route-override, the sidecar routes directly to the next
    actor named in the route, using the standard queue name resolution.
    """
    transport_helper.purge_queue("asya-default-x-sink")

    envelope = {
        "id": "test-no-override-1",
        "route": {
            "prev": [],
            "curr": "test-echo",
            "next": ["test-echo-v2"],
        },
        "payload": {"test": "no_override", "data": "normal_routing"},
    }
    logger.info(f"Publishing envelope without route override: {json.dumps(envelope, indent=2)}")

    transport_helper.publish_envelope("asya-default-test-echo", envelope)
    logger.info("Envelope published, waiting for result in x-sink...")

    result = transport_helper.assert_envelope_in_queue("asya-default-x-sink", timeout=30)
    logger.info(f"Result from x-sink: {json.dumps(result, indent=2) if result else 'None'}")
    assert result is not None, "No message in x-sink queue for normal routing"

    payload = result.get("payload", {})
    assert payload.get("test") == "no_override", f"Payload not echoed correctly, got: {payload}"
    assert payload.get("data") == "normal_routing", f"Payload data missing, got: {payload}"

    # Verify no x-asya-route-resolved header is present (no override applied)
    headers = result.get("headers", {})
    assert "x-asya-route-resolved" not in headers, (
        f"x-asya-route-resolved should not be present without override, got: {headers}"
    )

    # Verify route shows the message traversed both actors
    route = result.get("route", {})
    logger.info(f"Final route: {route}")
    assert "test-echo" in route.get("prev", []), (
        f"test-echo should be in prev, got: {route.get('prev')}"
    )
    logger.info("=== test_no_override_normal_routing: PASSED ===\n")


def test_route_override_audit_trail(transport_helper):
    """Test that x-asya-route-resolved audit trail is stamped when override is applied.

    Pipeline: test-echo -> echo-v2-target (overridden to test-echo-v2) -> x-sink

    When the sidecar applies a route override, it stamps
    headers['x-asya-route-resolved'] with an audit entry recording the
    original actor name, the override target, and which sidecar applied it.
    """
    transport_helper.purge_queue("asya-default-x-sink")

    envelope = {
        "id": "test-route-override-audit-1",
        "route": {
            "prev": [],
            "curr": "test-echo",
            "next": ["echo-v2-target"],
        },
        "headers": {
            "x-asya-route-override": {
                "echo-v2-target": "test-echo-v2",
            },
        },
        "payload": {"test": "audit_trail"},
    }
    logger.info(f"Publishing envelope for audit trail test: {json.dumps(envelope, indent=2)}")

    transport_helper.publish_envelope("asya-default-test-echo", envelope)
    logger.info("Envelope published, waiting for result in x-sink...")

    result = transport_helper.assert_envelope_in_queue("asya-default-x-sink", timeout=30)
    logger.info(f"Result from x-sink: {json.dumps(result, indent=2) if result else 'None'}")
    assert result is not None, "No message in x-sink queue for audit trail test"

    headers = result.get("headers", {})
    logger.info(f"Headers: {json.dumps(headers, indent=2)}")

    # Verify x-asya-route-resolved is present
    resolved = headers.get("x-asya-route-resolved")
    assert resolved is not None, (
        f"x-asya-route-resolved header missing, headers: {headers}"
    )

    # Verify the audit entry for the override
    assert "echo-v2-target" in resolved, (
        f"Audit trail should contain entry for 'echo-v2-target', got: {resolved}"
    )
    audit_entry = resolved["echo-v2-target"]
    assert audit_entry.get("target") == "test-echo-v2", (
        f"Audit trail target should be 'test-echo-v2', got: {audit_entry}"
    )
    assert audit_entry.get("by") == "test-echo", (
        f"Audit trail 'by' should be 'test-echo', got: {audit_entry}"
    )
    logger.info("=== test_route_override_audit_trail: PASSED ===\n")
