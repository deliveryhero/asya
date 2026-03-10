#!/usr/bin/env python3
"""
E2E SLA and timeout tests.

Tests three scenarios involving per-task deadline enforcement:

1. test_pipeline_completes_within_sla
   Happy path: 2-actor pipeline finishes before gateway-set deadline.
   Verifies the gateway stamps a non-zero deadline in the task status.

2. test_slow_actor_exceeds_sla
   Actor sleeps 60s; actorTimeout=5s kills it first.
   Verifies task fails, deadline was stamped, pod restarts (crash-on-timeout).

3. test_gateway_backstop_race
   Actor is at minReplicaCount=0; gateway timeout=5s fires before KEDA can scale.
   Verifies first-write-wins: task stays failed even after stale actor processes.
"""

import datetime
import logging
import os
import time

import pytest
from asya_testing.fixtures.e2e import wait_for_actors_factory

logger = logging.getLogger(__name__)

SLA_ACTOR_NAMES = ["test-timeout", "test-timeout-cold"]


@pytest.fixture(scope="module")
def sla_actors(kubectl, namespace):
    """Ensure SLA test actors are deployed and their queues are ready."""
    return wait_for_actors_factory(kubectl, namespace, SLA_ACTOR_NAMES)


def _get_pod_restart_count(e2e_helper, actor_name: str) -> int:
    """Return total container restart count for pods matching the actor label."""
    try:
        result = e2e_helper.kubectl(
            "get", "pods",
            "-l", f"asya.sh/actor={actor_name}",
            "-o", "jsonpath={.items[0].status.containerStatuses[*].restartCount}",
        )
        if result:
            return sum(int(c) for c in result.split() if c.isdigit())
    except Exception as e:
        logger.warning(f"Could not get pod restart count for {actor_name}: {e}")
    return 0


@pytest.mark.slow
def test_pipeline_completes_within_sla(e2e_helper):
    """
    E2E: 2-actor pipeline completes within the gateway-set SLA.

    Scenario:
    1. Call test_pipeline (doubler -> incrementer, gateway timeout=45s)
    2. Gateway stamps deadline = now + 45s in task status
    3. Pipeline processes in ~1s total
    4. Task succeeds; deadline was non-zero and ~45s after creation

    Expected:
    - task.status == "succeeded"
    - task.deadline is a non-empty RFC3339 timestamp
    - (deadline - created_at) is approximately the configured timeout (45s +/- 5s)
    """
    logger.info("Testing 2-actor pipeline completes within gateway SLA")

    response = e2e_helper.call_mcp_tool(
        tool_name="test_pipeline",
        arguments={"value": 10},
    )
    task_id = response["result"]["task_id"]
    logger.info(f"Task ID: {task_id}")

    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=60)

    assert final_task["status"] == "succeeded", (
        f"Pipeline should succeed within SLA, "
        f"got status={final_task['status']}, error={final_task.get('error')}"
    )
    logger.info(f"[+] Task succeeded: result={final_task.get('result')}")

    # Gateway stamps deadline when tool has timeout configured
    deadline_raw = final_task.get("deadline")
    assert deadline_raw, (
        "Gateway should stamp task.deadline when tool has timeout configured. "
        "This indicates the gateway is not setting up the backstop timer correctly."
    )
    logger.info(f"[+] Deadline was stamped: {deadline_raw}")

    # Verify deadline duration matches the configured tool timeout (~45s)
    created_at_raw = final_task.get("created_at")
    if created_at_raw:
        created_at = datetime.datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
        deadline = datetime.datetime.fromisoformat(deadline_raw.replace("Z", "+00:00"))
        duration = (deadline - created_at).total_seconds()
        assert 40 <= duration <= 50, (
            f"Deadline should be ~45s after creation (configured timeout), "
            f"got {duration:.1f}s. Check that tool timeout=45 is reflected in gateway."
        )
        logger.info(f"[+] Deadline set {duration:.1f}s after task creation (expected ~45s)")

    logger.info("[+] Pipeline SLA test passed")


@pytest.mark.slow
def test_slow_actor_exceeds_sla(e2e_helper, namespace):
    """
    E2E: Actor sleeping 60s gets killed by actorTimeout=5s.

    Scenario:
    1. test-timeout actor has actorTimeout=5s
    2. Send task with sleep_seconds=60 (60s >> 5s actorTimeout)
    3. Sidecar enforces actorTimeout: kills runtime after 5s, pod crashes
    4. KEDA detects crash, rescales pod
    5. Task eventually marked failed (via x-sump or gateway backstop at 30s)

    Expected:
    - task.status == "failed"
    - task.deadline is non-empty (gateway stamped it for the 30s tool timeout)
    - Pod restart count increased (crash-on-timeout)
    """
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    logger.info(f"Testing slow actor SLA violation (transport={transport})")

    # Purge queue to avoid interference with concurrent tests
    try:
        if transport == "sqs":
            from asya_testing.utils.sqs import purge_queue  # type: ignore[import]
            queue_name = f"asya-{namespace}-test-timeout"
            logger.info(f"Purging SQS queue: {queue_name}")
            purge_queue(queue_name)
            time.sleep(2)  # Wait for purge to propagate
    except Exception as exc:
        logger.warning(f"Queue purge failed (non-fatal): {exc}")

    initial_restarts = _get_pod_restart_count(e2e_helper, "test-timeout")
    logger.info(f"Initial pod restart count: {initial_restarts}")

    response = e2e_helper.call_mcp_tool(
        tool_name="test_timeout",
        arguments={"sleep_seconds": 60},
    )
    task_id = response["result"]["task_id"]
    logger.info(f"Task ID: {task_id}")

    # actorTimeout=5s kills runtime, then sidecar routes to x-sump.
    # Gateway backstop fires at 30s if x-sump doesn't report first.
    # Either way task must fail within 60s.
    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=60)

    assert final_task["status"] == "failed", (
        f"Task should fail when actor exceeds actorTimeout, "
        f"got status={final_task['status']}"
    )
    logger.info(f"[+] Task failed as expected: error={final_task.get('error')!r}")

    # Gateway should have stamped a deadline (test_timeout has timeout=30)
    deadline_raw = final_task.get("deadline")
    assert deadline_raw, (
        "Gateway should stamp task.deadline when tool has timeout configured. "
        "Got empty/missing deadline — check gateway tool config."
    )
    logger.info(f"[+] Deadline was stamped: {deadline_raw}")

    # Verify pod crashed and was restarted by KEDA
    logger.info("Waiting for pod to restart after crash-on-timeout...")
    time.sleep(5)  # Brief wait for crash to register in Kubernetes
    pod_ready = e2e_helper.wait_for_pod_ready("asya.sh/actor=test-timeout", timeout=60)
    assert pod_ready, "KEDA should rescale test-timeout pod after crash-on-timeout"

    final_restarts = _get_pod_restart_count(e2e_helper, "test-timeout")
    logger.info(f"Final pod restart count: {final_restarts}")
    assert final_restarts > initial_restarts, (
        f"Pod restart count should increase after crash-on-timeout. "
        f"Initial={initial_restarts}, final={final_restarts}. "
        f"Check that actorTimeout is configured on the actor."
    )
    logger.info(f"[+] Pod restarted ({initial_restarts} -> {final_restarts} restarts)")

    logger.info("[+] Slow actor SLA test passed")


@pytest.mark.slow
def test_gateway_backstop_race(e2e_helper, sla_actors, namespace):
    """
    E2E: Gateway backstop fires before cold-start actor processes stale message.

    Scenario:
    1. test-timeout-cold actor has minReplicaCount=0 (KEDA scale-to-zero)
    2. Call test_timeout_cold (gateway timeout=15s) with sleep_seconds=60
    3. Gateway publishes message with status.deadline_at=now+15s, starts 15s timer
    4. Message sits in queue; KEDA detects it and starts scaling (takes 30-60s)
    5. Gateway backstop fires at 15s -> task=failed, error="task timed out"
       (15s < 60s sleep, so the handler cannot complete before the backstop)
    6. KEDA eventually scales up pod; sidecar picks up stale message
    7. Sidecar detects expired deadline_at, routes via SLA pre-check
    8. x-sink/x-sump reports; gateway ignores (first-write-wins, task remains failed)
    9. Task status is still "failed" after 45s (stale processing complete)

    Expected:
    - Within 30s: task.status == "failed" (backstop fired at ~15s)
    - task.deadline is non-empty (15s after task creation)
    - After pod ready + 45s: task.status still "failed" (NOT overwritten)
    """
    logger.info("Testing gateway backstop race with cold-start actor")

    response = e2e_helper.call_mcp_tool(
        tool_name="test_timeout_cold",
        arguments={"sleep_seconds": 60},
    )
    task_id = response["result"]["task_id"]
    logger.info(f"Task ID: {task_id}")

    # Gateway backstop is 15s; wait up to 30s to absorb clock jitter
    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=30)

    assert final_task["status"] == "failed", (
        f"Gateway backstop should fire after 15s; "
        f"got status={final_task['status']}, error={final_task.get('error')!r}. "
        f"Check that test_timeout_cold tool has timeout=15 configured."
    )
    error_msg = final_task.get("error", "").lower()
    assert "timed out" in error_msg or "timeout" in error_msg, (
        f"Task should fail with a timeout error, got: {final_task.get('error')!r}"
    )
    logger.info(f"[+] Backstop fired at ~5s: {final_task.get('error')!r}")

    deadline_raw = final_task.get("deadline")
    assert deadline_raw, (
        "Gateway should stamp task.deadline for test_timeout_cold (timeout=15). "
        "Got empty/missing deadline."
    )
    logger.info(f"[+] Deadline was stamped: {deadline_raw}")

    # Wait for the cold actor to become ready, then allow time for stale message processing.
    # Scale-up from zero takes ~30-60s; the sidecar SLA pre-check detects the expired deadline
    # and routes to x-sump without running the handler, so processing is near-instant.
    logger.info("Waiting for cold-start actor to scale up and process stale message...")

    # 1. Wait for the pod to scale up and become ready.
    pod_ready = e2e_helper.wait_for_pod_ready("asya.sh/actor=test-timeout-cold", timeout=90)
    assert pod_ready, "Cold-start actor pod did not become ready within 90s after backstop fired."
    logger.info("[+] Cold-start actor pod scaled up")

    # 2. Wait for the stale message to flow through: sidecar SLA pre-check → x-sump → gateway.
    # We do not wait for KEDA scale-down (requires 60s cooldown + pod termination) because
    # scale-down is KEDA infrastructure behavior, not the gateway's first-write-wins guarantee.
    # 45s is sufficient for: SQS visibility (2s) + sidecar processing + x-sump → gateway report.
    logger.info("Waiting 45s for stale message to be processed by sidecar SLA pre-check...")
    time.sleep(45)  # Allow stale message processing via sidecar SLA pre-check and x-sump

    # Task must remain failed — not overwritten to succeeded by stale actor result
    post_wait = e2e_helper.get_task_status(task_id)
    assert post_wait["status"] == "failed", (
        f"Task should remain 'failed' after stale actor processes expired message, "
        f"got status={post_wait['status']!r}. "
        f"The gateway may be incorrectly accepting late actor reports on terminal tasks."
    )
    logger.info("[+] Task still 'failed' after stale message processed")

    logger.info("[+] Gateway backstop race test passed")
