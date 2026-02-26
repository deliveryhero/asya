"""
SLA enforcement integration tests for gateway-actors.

Tests the gateway timeout mechanism: the gateway tool has a configured timeout.
The gateway sets a deadline_at on the message and starts a backstop timer.
The sidecar computes effectiveTimeout = min(ACTOR_TIMEOUT, remaining_SLA).

Since the gateway passes deadline_at, the sidecar's effective timeout
approximates the gateway timeout — both the backstop and sidecar timeout
fire at roughly the same time. Either can win the race. What matters is:
1. The task is marked as failed due to timeout
2. Once failed, duplicate reports are ignored (isFinal check)
"""

import logging
import time

import pytest

from asya_testing.config import get_env
from asya_testing.fixtures.gateway import gateway_helper

log_level = get_env("ASYA_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@pytest.mark.order("last")
class TestSLABackstop:
    """Gateway backstop marks task as failed before actor completes.

    The gateway sets a 3s backstop (test_sla_backstop tool) and passes
    deadline_at in the message. The sidecar computes
    effectiveTimeout = min(ACTOR_TIMEOUT=5s, ~3s) = ~3s.

    Either the gateway backstop or the sidecar effective timeout may fire
    first — both arrive at roughly ~3s. What matters:
    1. The task is marked as failed due to a timeout-related cause
    2. Once failed, duplicate reports are ignored (isFinal check)

    Ordering: runs last because the test-timeout sidecar may already be
    dead (crashed by other tests that also use test-timeout actor).
    The test still passes — the gateway backstop alone is sufficient
    to mark the task as failed.
    """

    def test_backstop_marks_task_failed(self, gateway_helper):
        """Task is marked failed due to backstop; duplicate reports are ignored.

        Setup:
        - Tool: test_sla_backstop (gateway backstop=3s, route=[test-timeout])
        - Actor: test-timeout (handler sleeps 60s, ACTOR_TIMEOUT=5s)

        Timeline:
        - t=0s: Gateway creates task, sends message with deadline_at, starts 3s backstop
        - t~3s: Gateway backstop fires AND/OR sidecar effective timeout fires
        - Whichever arrives first marks task as failed
        - The other is ignored via isFinal() check
        """
        response = gateway_helper.call_mcp_tool(
            tool_name="test_sla_backstop",
            arguments={"sleep_seconds": 60},
        )

        assert "result" in response, f"MCP call failed: {response}"
        task_id = response["result"]["id"]
        logger.info(f"Task ID: {task_id}")

        # Wait for task to reach terminal state (~3s timeout + buffer)
        start = time.monotonic()
        task = gateway_helper.wait_for_task_completion(task_id, timeout=10)
        elapsed = time.monotonic() - start

        logger.info(f"Task reached terminal state after {elapsed:.1f}s: {task}")

        assert task["status"] == "failed", (
            f"Expected task status 'failed', got '{task['status']}'"
        )

        # Verify the failure is timeout-related (from either gateway backstop or sidecar)
        # Gateway backstop: "task timed out"
        # Sidecar report: "Runtime timeout exceeded after Ns"
        error_info = str(task.get("error") or task.get("error_message") or "")
        logger.info(f"Error info: {error_info}")
        assert "timeout" in error_info.lower() or "timed out" in error_info.lower(), (
            f"Expected timeout-related error, got: {error_info}"
        )

        # Task should fail at ~3s (gateway timeout), not 60s (handler sleep)
        assert elapsed < 8, (
            f"Task took {elapsed:.1f}s to fail — expected ~3s (gateway timeout)"
        )

        # Wait for both timeout sources to have reported.
        # Gateway backstop fires at ~3s, sidecar effective timeout at ~3s.
        # By ~8s from start, both should have reported.
        remaining_wait = max(0, 8 - elapsed)
        if remaining_wait > 0:
            logger.info(f"Waiting {remaining_wait:.1f}s for all timeout reports to arrive...")
            time.sleep(remaining_wait)  # Wait for potential duplicate reports

        # Verify task is STILL failed (gateway ignored duplicate reports via isFinal)
        final_task = gateway_helper.get_task_status(task_id)
        logger.info(f"Final task after timeout window: {final_task}")

        assert final_task["status"] == "failed", (
            f"Task status changed from 'failed' to '{final_task['status']}' — "
            f"gateway should ignore duplicate reports after task reaches terminal state"
        )

        logger.info(f"=== test_backstop_marks_task_failed: PASSED ({elapsed:.1f}s) ===")
