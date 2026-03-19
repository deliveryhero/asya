#!/usr/bin/env python3
"""
E2E tests for policy-based resiliency (retry/exhaustion).

Covers the full stack from AsyncActor CRD → Crossplane composition →
sidecar env var injection → policy matching → retry/exhaust behavior →
x-sink recording → gateway task status.

Tests:

1. test_resiliency_policy_rendered_to_sidecar_env
   Verifies that Crossplane correctly serializes spec.resiliency.policies
   and spec.resiliency.rules into ASYA_RESILIENCY_POLICIES /
   ASYA_RESILIENCY_RULES env vars on the sidecar container.
   Applies an AsyncActor inline (kubectl apply), waits for the pod, checks
   the env vars, then cleans up. Works on all transports.

2. test_retry_exhaustion_fails_to_sink (SQS only)
   Sends a message to test-retry-exhaustion (error_handler, maxAttempts=3,
   delay=1s). The actor always raises ValueError. After 3 SQS-delayed
   retries the sidecar sends to x-sink. The gateway task reaches failed.

3. test_nonretryable_policy_fails_immediately (all transports)
   Sends a message to test-retry-nonretryable (error_handler, ValueError →
   nonretryable policy with maxAttempts=1). No retry delay is attempted;
   the task fails quickly.
"""

import json
import logging
import os
import subprocess
import time

import pytest

from asya_testing.utils.kubectl import (
    kubectl_apply_raw,
    kubectl_delete,
    wait_for_asyncactor_ready,
    wait_for_deletion,
)
from asya_testing.fixtures.e2e import wait_for_actors_factory

logger = logging.getLogger(__name__)

TRANSPORT = os.getenv("ASYA_TRANSPORT", "sqs")

RETRY_ACTOR_NAMES = ["test-retry-exhaustion", "test-retry-nonretryable"]


@pytest.fixture(scope="module")
def retry_actors(kubectl, namespace):
    """Ensure retry test actors are deployed and their queues are ready."""
    return wait_for_actors_factory(kubectl, namespace, RETRY_ACTOR_NAMES)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_sidecar_env(actor_name: str, namespace: str, env_var: str) -> str | None:
    """Return the value of env_var on the asya-sidecar container of an actor pod."""
    result = subprocess.run(
        [
            "kubectl",
            "get", "pods",
            "-n", namespace,
            "-l", f"asya.sh/actor={actor_name}",
            "-o",
            "jsonpath={.items[0].spec.containers[?(@.name==\"asya-sidecar\")].env}",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if not result.stdout.strip():
        return None
    env_list = json.loads(result.stdout)
    for entry in env_list:
        if entry.get("name") == env_var:
            return entry.get("value")
    return None


# ---------------------------------------------------------------------------
# Test 1: Crossplane rendering verification
# ---------------------------------------------------------------------------

def test_resiliency_policy_rendered_to_sidecar_env(namespace):
    """
    Verify Crossplane serializes spec.resiliency.policies / rules into
    ASYA_RESILIENCY_POLICIES / ASYA_RESILIENCY_RULES on the sidecar container.

    Applies a temporary AsyncActor with an inline manifest. After Crossplane
    reconciles and the pod is running, asserts the env vars are present and
    contain valid JSON matching the configured values. Cleans up on exit.
    """
    actor_name = "test-resiliency-rendering"
    manifest = f"""
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: {actor_name}
  namespace: {namespace}
spec:
  actor: {actor_name}
  resiliency:
    actorTimeout: "30s"
    policies:
      default:
        maxAttempts: 4
        backoff: exponential
        initialDelay: "2s"
        maxInterval: "30s"
        jitter: true
      fast-fail:
        maxAttempts: 1
    rules:
      - errors:
          - ValueError
        policy: fast-fail
  scaling:
    enabled: false
  image: ghcr.io/deliveryhero/asya-testing:latest
  imagePullPolicy: IfNotPresent
  handler: asya_testing.handlers.payload.echo_handler
"""
    try:
        kubectl_apply_raw(manifest, namespace=namespace)
        wait_for_asyncactor_ready(actor_name, namespace=namespace, timeout=90)

        # Wait for the pod to be running so env vars are accessible
        for _ in range(30):
            policies_val = _get_sidecar_env(actor_name, namespace, "ASYA_RESILIENCY_POLICIES")
            if policies_val:
                break
            time.sleep(3)  # Wait for pod to start and env to be readable
        else:
            pytest.fail(
                f"ASYA_RESILIENCY_POLICIES not found on sidecar of {actor_name} after 90s. "
                f"Crossplane may not have rendered the resiliency.policies block."
            )

        policies = json.loads(policies_val)
        assert "default" in policies, f"Expected 'default' policy key, got: {list(policies.keys())}"
        assert policies["default"]["maxAttempts"] == 4
        assert policies["default"]["backoff"] == "exponential"
        assert policies["default"]["initialDelay"] == "2s"
        assert policies["default"]["jitter"] is True
        assert "fast-fail" in policies, f"Expected 'fast-fail' policy key, got: {list(policies.keys())}"
        assert policies["fast-fail"]["maxAttempts"] == 1

        rules_val = _get_sidecar_env(actor_name, namespace, "ASYA_RESILIENCY_RULES")
        assert rules_val is not None, "ASYA_RESILIENCY_RULES not found on sidecar"
        rules = json.loads(rules_val)
        assert len(rules) == 1
        assert rules[0]["errors"] == ["ValueError"]
        assert rules[0]["policy"] == "fast-fail"

        logger.info("[+] test_resiliency_policy_rendered_to_sidecar_env: PASSED")

    finally:
        kubectl_delete("asyncactor", actor_name, namespace=namespace)
        kubectl_delete("deployment", actor_name, namespace=namespace)
        kubectl_delete("scaledobject", actor_name, namespace=namespace)
        wait_for_deletion("asyncactor", actor_name, namespace=namespace, timeout=60)


# ---------------------------------------------------------------------------
# Test 2: Retry exhaustion (SQS only — needs SendWithDelay)
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_retry_exhaustion_fails_to_sink(e2e_helper, retry_actors):
    """
    Send a message to test-retry-exhaustion (error_handler, maxAttempts=3,
    constant 1s delay). Actor always raises ValueError. After 3 SQS-delayed
    attempts the sidecar exhausts the policy and routes to x-sink. Gateway
    reports task as failed.

    Skipped on non-SQS transports (RabbitMQ lacks SendWithDelay).
    """
    if TRANSPORT != "sqs":
        pytest.skip("Retry with delay requires SQS transport (SendWithDelay)")

    logger.info("Calling test-retry-exhaustion actor — expecting 3 attempts then failure")
    response = e2e_helper.call_mcp_tool(
        tool_name="test-retry-exhaustion",
        arguments={"message": "retry-exhaustion-e2e"},
    )
    task_id = response["result"]["task_id"]
    logger.info(f"Task ID: {task_id}")

    # 3 attempts × 1s delay + processing overhead — allow generous margin
    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=60)
    assert final_task is not None, "Task did not complete within 60s"

    status = final_task.get("status", "")
    logger.info(f"Final task status: {status}")
    assert status == "failed", (
        f"Expected task status='failed' after policy exhaustion, got '{status}'. "
        f"Full task: {json.dumps(final_task, indent=2)}"
    )
    logger.info("[+] test_retry_exhaustion_fails_to_sink: PASSED")


# ---------------------------------------------------------------------------
# Test 3: Non-retryable policy (all transports)
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_nonretryable_policy_fails_immediately(e2e_helper, retry_actors):
    """
    Send a message to test-retry-nonretryable (error_handler raises ValueError,
    matched by rules to the nonretryable policy with maxAttempts=1). No SQS
    delayed send is attempted; the task fails quickly on all transports.
    """
    logger.info("Calling test-retry-nonretryable actor — expecting immediate failure")
    t0 = time.monotonic()

    response = e2e_helper.call_mcp_tool(
        tool_name="test-retry-nonretryable",
        arguments={"message": "nonretryable-e2e"},
    )
    task_id = response["result"]["task_id"]
    logger.info(f"Task ID: {task_id}")

    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=20)
    elapsed = time.monotonic() - t0
    assert final_task is not None, "Task did not complete within 20s"

    status = final_task.get("status", "")
    logger.info(f"Final task status: {status}, elapsed: {elapsed:.1f}s")
    assert status == "failed", (
        f"Expected task status='failed' (nonretryable policy), got '{status}'. "
        f"Full task: {json.dumps(final_task, indent=2)}"
    )
    logger.info("[+] test_nonretryable_policy_fails_immediately: PASSED")
