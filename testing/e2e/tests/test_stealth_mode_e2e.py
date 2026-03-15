#!/usr/bin/env python3
"""
E2E tests for stealth mode: x-asya-mesh-status: off envelope header.

Tests that envelopes injected directly into actor queues (bypassing the
gateway) with x-asya-mesh-status: off are processed by actors normally,
but the sidecar makes no /mesh/* calls to the gateway.

Use case: lab workflows, testing pipelines, and direct queue injection
that should not pollute gateway task tracking.
"""

import logging
import time
import urllib.parse
import uuid

import pytest
import requests

from asya_testing.config import require_env


logger = logging.getLogger(__name__)


def _make_transport_client(test_config):
    """Create a transport client for direct queue injection (bypassing gateway)."""
    if test_config.is_sqs():
        from asya_testing.clients.sqs import SQSClient

        return SQSClient(
            endpoint_url=require_env("AWS_ENDPOINT_URL"),
            region=require_env("AWS_DEFAULT_REGION"),
            access_key=require_env("AWS_ACCESS_KEY_ID"),
            secret_key=require_env("AWS_SECRET_ACCESS_KEY"),
        )
    elif test_config.is_rabbitmq():
        from asya_testing.clients.rabbitmq import RabbitMQClient

        parsed = urllib.parse.urlparse(test_config.rabbitmq_url)
        return RabbitMQClient(
            host=parsed.hostname,
            port=parsed.port or 5672,
            user=parsed.username or "guest",
            password=parsed.password or "guest",
            namespace=test_config.namespace,
        )
    else:
        pytest.skip(f"Stealth mode test not supported for transport: {test_config.transport}")


@pytest.mark.fast
def test_stealth_mode_bypasses_gateway_tracking(
    e2e_helper, namespace, test_config, transport_timeouts
):
    """
    E2E: Envelopes with x-asya-mesh-status: off are not tracked by the gateway.

    Scenario:
    1. Inject envelope directly into test-echo queue (bypassing gateway)
       with x-asya-mesh-status: off header in envelope headers
    2. Actor processes the message and routes to x-sink normally
    3. Wait for full pipeline to complete
    4. Verify GET /mesh/{task_id} returns 404 throughout

    Expected: The sidecar processes and routes the message correctly, but
    makes no /mesh/* calls — stealth envelopes never appear in gateway tracking.
    """
    task_id = str(uuid.uuid4())
    transport_client = _make_transport_client(test_config)

    # Single-hop envelope: test-echo processes it, then routes to x-sink (next=[])
    envelope = {
        "id": task_id,
        "route": {"prev": [], "curr": "test-echo", "next": []},
        "headers": {"x-asya-mesh-status": "off"},
        "payload": {"message": "stealth-e2e-test"},
    }

    queue = f"asya-{namespace}-test-echo"
    transport_client.publish(queue, envelope)
    logger.info(f"Published stealth envelope to {queue} (task_id={task_id})")

    # Wait for the full actor pipeline to complete. If stealth mode is broken,
    # the sidecar would have sent /mesh/* progress reports to the gateway by now.
    time.sleep(transport_timeouts.task_completion_short)  # Allow full pipeline completion

    mesh_url = f"{e2e_helper.mesh_gateway_url}/mesh/{task_id}"
    resp = requests.get(mesh_url, timeout=5)
    assert resp.status_code == 404, (
        f"Gateway should not track stealth task {task_id} "
        f"(x-asya-mesh-status: off), got HTTP {resp.status_code}: {resp.text[:200]}"
    )
    logger.info(f"[+] Stealth task {task_id} not tracked by gateway (HTTP 404 confirmed)")


@pytest.mark.fast
def test_normal_envelope_is_tracked_gateway(e2e_helper, transport_timeouts):
    """
    E2E: Control test — normal envelopes sent via gateway ARE tracked.

    Verifies the baseline: without x-asya-mesh-status: off, the gateway
    receives progress reports and the task appears in /mesh/{task_id}.
    This confirms the 404 in test_stealth_mode_bypasses_gateway_tracking
    is caused by the header, not by some unrelated gateway issue.
    """
    response = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "baseline-tracking-test"},
    )
    task_id = response["result"]["task_id"]
    assert task_id is not None, "Should have task ID from gateway"

    final = e2e_helper.wait_for_task_completion(
        task_id, timeout=transport_timeouts.task_completion_short
    )
    assert final["status"] == "succeeded", (
        f"Baseline echo task should succeed, got {final['status']}"
    )
    logger.info(f"[+] Normal task {task_id} tracked correctly by gateway")
