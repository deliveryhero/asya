#!/usr/bin/env python3
"""
Sidecar component tests - SLA enforcement.

Tests sidecar SLA deadline enforcement against real transports:
- Expired messages routed to x-sink (runtime never called)
- Tight SLA deadlines limit effective timeout via min(actor_timeout, remaining_SLA)
"""

import logging
import os
from datetime import datetime, timedelta, timezone

import pytest

from asya_testing.fixtures import configure_logging
from asya_testing.fixtures.transport import transport_client

configure_logging()

logger = logging.getLogger(__name__)

# Use shared transport fixture from asya_testing
transport = transport_client


_RFC3339_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _now_rfc3339() -> str:
    return datetime.now(timezone.utc).strftime(_RFC3339_FMT)


def _deadline_rfc3339(delta_seconds: int) -> str:
    dt = datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)
    return dt.strftime(_RFC3339_FMT)


def _is_sqs() -> bool:
    return os.getenv("ASYA_TRANSPORT", "rabbitmq") == "sqs"


def test_sla_expired_routes_to_sink(transport):
    """Expired SLA deadline routes message to x-sink without calling runtime.

    When status.deadline_at is in the past, the sidecar:
    1. Detects the expired deadline in the SLA pre-check
    2. Stamps status with phase=failed, reason=Timeout
    3. Routes directly to x-sink (never calls runtime)
    """
    transport.purge("test-echo")
    transport.purge("x-sink")

    now = _now_rfc3339()
    expired_deadline = _deadline_rfc3339(-60)

    message = {
        "id": "test-sla-expired-001",
        "route": {"prev": [], "curr": "test-echo", "next": ["test-verify"]},
        "payload": {"message": "should not reach runtime"},
        "status": {
            "phase": "pending",
            "reason": "",
            "actor": "",
            "attempt": 1,
            "max_attempts": 1,
            "created_at": now,
            "updated_at": now,
            "deadline_at": expired_deadline,
        },
    }

    transport.publish("test-echo", message)

    # SQS has 20s long-polling; RabbitMQ is near-instant
    consume_timeout = 60 if _is_sqs() else 15
    result = transport.consume("x-sink", timeout=consume_timeout)

    assert result is not None, "Expired message should reach x-sink"
    assert result["id"] == "test-sla-expired-001"

    # Status stamped with failed/Timeout
    assert result["status"]["phase"] == "failed"
    assert result["status"]["reason"] == "Timeout"
    assert result["status"]["actor"] == "test-echo"
    assert result["status"]["deadline_at"] == expired_deadline

    # Original payload unchanged (runtime was never called)
    assert result["payload"] == {"message": "should not reach runtime"}

    # Message did NOT reach next actor in the route
    no_result = transport.consume("test-verify", timeout=3)
    assert no_result is None, "Expired message should NOT reach next actor in route"


@pytest.mark.timeout(120)
def test_sla_tight_deadline_triggers_timeout(transport):
    """Tight SLA deadline limits effective timeout, causing runtime timeout.

    With ASYA_RESILIENCY_ACTOR_TIMEOUT=120s and a short deadline, the sidecar
    computes effective_timeout = min(120s, remaining_SLA). The runtime handler
    sleeps far longer than remaining_SLA, so the effective timeout fires.

    Expected flow:
    1. Sidecar receives message (SLA not yet expired -> passes pre-check)
    2. effective_timeout = min(120s, remaining_SLA) = remaining_SLA
    3. Runtime sleeps 120s > remaining_SLA -> context.DeadlineExceeded
    4. Sidecar sends to x-sump with timeout error
    5. Sidecar crashes pod (os.Exit(1)) to prevent zombie processing
    """
    transport.purge("test-timeout")
    transport.purge("x-sump")
    transport.purge("test-verify")

    # Transport-aware deadline: SQS needs buffer for 20s long-polling
    if _is_sqs():
        deadline_seconds = 40  # 20s SQS polling + 20s remaining SLA
        consume_timeout = 90
    else:
        deadline_seconds = 5  # RabbitMQ: near-instant delivery
        consume_timeout = 30

    now = _now_rfc3339()
    deadline = _deadline_rfc3339(deadline_seconds)

    message = {
        "id": "test-sla-tight-001",
        "route": {"prev": [], "curr": "test-timeout", "next": ["test-verify"]},
        "payload": {"sleep_seconds": 120},
        "status": {
            "phase": "pending",
            "reason": "",
            "actor": "",
            "attempt": 1,
            "max_attempts": 1,
            "created_at": now,
            "updated_at": now,
            "deadline_at": deadline,
        },
    }

    transport.publish("test-timeout", message)

    # Message should arrive in x-sump (runtime timeout, not SLA pre-check)
    result = transport.consume("x-sump", timeout=consume_timeout)

    assert result is not None, "Timed-out message should reach x-sump"
    assert result["id"] == "test-sla-tight-001"

    # x-sump wraps original payload in error structure
    assert "error" in result["payload"], "x-sump message should have error field"
    assert "timeout" in result["payload"]["error"].lower(), (
        f"Error should mention timeout, got: {result['payload']['error']}"
    )
    assert result["payload"]["original_payload"]["sleep_seconds"] == 120

    # Status should be failed
    assert result["status"]["phase"] == "failed"

    # Message should NOT reach the next queue
    no_result = transport.consume("test-verify", timeout=3)
    assert no_result is None, "Timed-out message should NOT reach next actor"
