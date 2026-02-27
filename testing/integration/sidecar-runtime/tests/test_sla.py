"""
SLA enforcement integration tests for sidecar-runtime.

Tests the sidecar's deadline_at-based SLA enforcement mechanisms:
1. SLA pre-check: expired deadlines route to x-sink before processing
2. Effective timeout: effectiveTimeout = min(ACTOR_TIMEOUT, remaining_SLA)
3. Retry + SLA interaction: SLA pre-check takes precedence over retry logic

IMPORTANT: TestSLAEffectiveTimeout must run last because it causes the
test-sla-slow sidecar to os.Exit(1) after runtime timeout. Other tests
are non-destructive and must complete before the sidecar crash.

Test actors:
- test-sla-slow: timeout_handler (sleeps 120s), ACTOR_TIMEOUT=30s
- test-sla-retry: error_handler (raises ValueError), max_attempts=5, interval=2s
"""

import json
import logging
import time
from datetime import datetime, timedelta, timezone

import pytest

from asya_testing.config import get_env

log_level = get_env("ASYA_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

UTC = timezone.utc


def _make_deadline(seconds_from_now: float) -> str:
    """Create an RFC3339 deadline_at timestamp."""
    deadline = datetime.now(tz=UTC) + timedelta(seconds=seconds_from_now)
    return deadline.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestSLAPreCheck:
    """SLA pre-check rejects expired messages before calling runtime.

    When a message arrives with an already-expired deadline_at, the sidecar
    routes it directly to x-sink with phase=failed, reason=Timeout.
    The runtime is never called — no handler execution overhead.
    """

    def test_expired_deadline_routes_to_sink(self, transport_helper):
        """Message with expired deadline goes to x-sink without runtime processing.

        Setup:
        - Actor: test-sla-slow (timeout_handler, ACTOR_TIMEOUT=30s)
        - Deadline: 60s in the past

        The sidecar's SLA pre-check at the top of ProcessMessage() detects the
        expired deadline and routes directly to x-sink. The handler never runs.
        """
        transport_helper.purge_queue("asya-default-x-sink")

        deadline_at = _make_deadline(-60)
        message = {
            "id": "test-sla-precheck-expired-1",
            "route": {"prev": [], "curr": "test-sla-slow", "next": []},
            "payload": {"sleep": 120},
            "status": {"deadline_at": deadline_at},
        }
        logger.info(
            f"Publishing message with expired deadline (deadline_at={deadline_at}): "
            f"{json.dumps(message, indent=2)}"
        )

        start = time.monotonic()
        transport_helper.publish_message("asya-default-test-sla-slow", message)

        # SLA pre-check should reject immediately — message in x-sink within seconds
        result = transport_helper.get_message("asya-default-x-sink", timeout=10)
        elapsed = time.monotonic() - start

        logger.info(
            f"Result from x-sink after {elapsed:.1f}s: "
            f"{json.dumps(result, indent=2) if result else 'None'}"
        )

        assert result is not None, (
            "No message in x-sink after 10s. "
            "SLA pre-check should route expired messages to x-sink immediately."
        )

        # Verify status indicates SLA timeout (not a runtime error)
        status = result.get("status", {})
        assert status.get("phase") == "failed", (
            f"Expected status.phase='failed', got '{status.get('phase')}'"
        )
        assert status.get("reason") == "Timeout", (
            f"Expected status.reason='Timeout' (SLA pre-check), got '{status.get('reason')}'"
        )

        # Payload should be preserved unchanged (handler never ran)
        payload = result.get("payload", {})
        assert payload.get("sleep") == 120, (
            f"Original payload not preserved, got: {payload}"
        )

        # Should complete well under ACTOR_TIMEOUT (30s)
        assert elapsed < 10, (
            f"SLA pre-check took {elapsed:.1f}s — expected well under ACTOR_TIMEOUT (30s)."
        )

        logger.info(
            f"=== test_expired_deadline_routes_to_sink: PASSED ({elapsed:.1f}s) ==="
        )


class TestRetrySLAInteraction:
    """SLA pre-check takes precedence over retry logic.

    When a message has a deadline and the actor is configured with retries,
    the SLA pre-check fires before each attempt. Once the deadline expires,
    the message routes directly to x-sink with reason=Timeout — even if
    max_attempts hasn't been exhausted.

    Requires SQS transport (SendWithDelay not supported on RabbitMQ).
    """

    def test_sla_precheck_stops_retries(self, transport_helper):
        """SLA expiry routes to x-sink before max_attempts is exhausted.

        Setup:
        - Actor: test-sla-retry (error_handler, max_attempts=5, interval=2s)
        - Deadline: 5s from now

        Expected timeline:
        - Attempt 1 (t=0s): SLA check ok (5s left), handler raises ValueError → retry
        - Attempt 2 (t=2s): SLA check ok (3s left), handler raises ValueError → retry
        - Attempt 3 (t=4s): SLA check ok (1s left), handler raises ValueError → retry
        - Attempt 4 (t=6s): SLA pre-check → deadline expired → x-sink (reason=Timeout)

        Only 3 of 5 attempts execute. SLA takes precedence.
        """
        transport = get_env("ASYA_TRANSPORT", "rabbitmq")
        if transport != "sqs":
            pytest.skip("Retry with delay requires SQS transport (RabbitMQ lacks SendWithDelay)")

        transport_helper.purge_queue("asya-default-x-sink")
        transport_helper.purge_queue("asya-default-x-sump")

        deadline_at = _make_deadline(5)
        message = {
            "id": "test-sla-retry-1",
            "route": {"prev": [], "curr": "test-sla-retry", "next": []},
            "payload": {"test": "sla_retry_interaction"},
            "status": {"deadline_at": deadline_at},
        }
        logger.info(
            f"Publishing SLA retry message (deadline_at={deadline_at}): "
            f"{json.dumps(message, indent=2)}"
        )

        start = time.monotonic()
        transport_helper.publish_message("asya-default-test-sla-retry", message)

        # SLA should expire and route to x-sink within ~6-8s.
        # Use 15s timeout as generous upper bound.
        result = transport_helper.get_message("asya-default-x-sink", timeout=15)
        elapsed = time.monotonic() - start

        logger.info(f"Result from x-sink after {elapsed:.1f}s: {json.dumps(result, indent=2) if result else 'None'}")

        assert result is not None, (
            f"No message in x-sink after 15s — SLA pre-check may not be stopping retries. "
            f"Expected message in x-sink (not x-sump) when deadline expires."
        )

        # Verify status indicates timeout, not max retries exhausted
        status = result.get("status", {})
        logger.info(f"Status: {json.dumps(status, indent=2)}")
        assert status.get("reason") == "Timeout", (
            f"Expected status.reason='Timeout' (SLA pre-check), got '{status.get('reason')}'. "
            f"If reason is 'MaxRetriesExhausted', SLA didn't take precedence."
        )
        assert status.get("phase") == "failed", (
            f"Expected status.phase='failed', got '{status.get('phase')}'"
        )

        # Verify no message went to x-sump (SLA pre-check routes to x-sink, not x-sump)
        sump_msg = transport_helper.get_message("asya-default-x-sump", timeout=3)
        assert sump_msg is None, (
            "Message found in x-sump — SLA pre-check should route to x-sink, "
            "not x-sump. x-sump is for runtime errors, not SLA expiry."
        )

        logger.info(f"=== test_sla_precheck_stops_retries: PASSED ({elapsed:.1f}s) ===")


@pytest.mark.order("last")
class TestSLAEffectiveTimeout:
    """SLA deadline constrains the sidecar's effective timeout.

    The sidecar computes effectiveTimeout = min(ACTOR_TIMEOUT, remaining_SLA).
    When remaining_SLA < ACTOR_TIMEOUT, the runtime context deadline fires
    earlier than ACTOR_TIMEOUT would, proving the SLA constrains the timeout.

    WARNING: This test causes the test-sla-slow sidecar to os.Exit(1) after
    runtime timeout, killing the container. Ordered last via @pytest.mark.order
    so all non-destructive tests complete first.
    """

    def test_sla_constrains_effective_timeout(self, transport_helper):
        """Deadline tighter than ACTOR_TIMEOUT causes earlier runtime timeout.

        Setup:
        - Actor: test-sla-slow (timeout_handler sleeps 120s, ACTOR_TIMEOUT=30s)
        - Deadline: 5s from now

        Without SLA: effective timeout = 30s (ACTOR_TIMEOUT)
        With SLA: effective timeout = min(30s, 5s) = 5s

        Handler exceeds effective timeout at ~5s → runtime context deadline → x-sump.
        Wall time should be ~5-8s, NOT 30s.
        """
        transport_helper.purge_queue("asya-default-x-sump")

        deadline_at = _make_deadline(5)
        message = {
            "id": "test-sla-effective-timeout-1",
            "route": {"prev": [], "curr": "test-sla-slow", "next": []},
            "payload": {"sleep": 120},
            "status": {"deadline_at": deadline_at},
        }
        logger.info(
            f"Publishing message with 5s SLA deadline (deadline_at={deadline_at}): "
            f"{json.dumps(message, indent=2)}"
        )

        start = time.monotonic()
        transport_helper.publish_message("asya-default-test-sla-slow", message)

        # With SLA: effective timeout ~5s, message in x-sump by ~8s.
        # Without SLA: timeout at 30s (ACTOR_TIMEOUT), would fail this 15s poll.
        result = transport_helper.get_message("asya-default-x-sump", timeout=15)
        elapsed = time.monotonic() - start

        logger.info(
            f"Result from x-sump after {elapsed:.1f}s: "
            f"{json.dumps(result, indent=2) if result else 'None'}"
        )

        assert result is not None, (
            f"No message in x-sump after 15s. "
            f"effectiveTimeout should be ~5s (SLA), not 30s (ACTOR_TIMEOUT)."
        )

        # Verify the failure is a timeout (context deadline exceeded)
        payload = result.get("payload", {})
        error_msg = payload.get("error", "")
        logger.info(f"Error: {error_msg}")
        assert "deadline" in error_msg.lower() or "timeout" in error_msg.lower(), (
            f"Expected context deadline / timeout error, got: {error_msg}"
        )

        # Wall time should be well under 30s (the ACTOR_TIMEOUT).
        # SLA effective timeout is ~5s, so total with overhead should be <12s.
        assert elapsed < 12, (
            f"Message took {elapsed:.1f}s — expected <12s with 5s SLA deadline. "
            f"Without SLA enforcement, timeout would be ~30s."
        )

        logger.info(
            f"=== test_sla_constrains_effective_timeout: PASSED ({elapsed:.1f}s) ==="
        )
