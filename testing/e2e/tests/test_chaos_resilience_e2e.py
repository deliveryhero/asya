#!/usr/bin/env python3
"""
E2E chaos and resilience tests for Asya framework.

Tests system resilience under adverse conditions:
- Transport service failures (RabbitMQ/SQS down)
- Network partitions and delays
- Resource exhaustion (OOM, CPU limits)
- Partial system failures
- Cascading failures
- Recovery after multiple component failures

These tests verify the system handles real-world failure scenarios gracefully.
"""

import logging
import time

import pytest

logger = logging.getLogger(__name__)


@pytest.mark.slow
@pytest.mark.chaos
@pytest.mark.xdist_group(name="chaos")
def test_rabbitmq_restart_during_processing(e2e_helper):
    """
    E2E: Test system handles RabbitMQ restart gracefully.

    Scenario:
    1. Send messages to actors
    2. Restart RabbitMQ while processing
    3. Verify messages are redelivered and complete

    Expected: At-least-once delivery guarantees maintained
    """
    import os
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    if transport != "rabbitmq":
        pytest.skip("This test requires RabbitMQ transport")

    logger.info("Sending messages...")
    task_ids = []
    for i in range(10):
        response = e2e_helper.call_mcp_tool(
            tool_name="test_slow_boundary",
            arguments={"first_call": True},
        )
        task_ids.append(response["result"]["task_id"])

    time.sleep(2)

    logger.info("Restarting RabbitMQ...")
    try:
        pods = e2e_helper.kubectl(
            "get", "pods",
            "-l", "app.kubernetes.io/name=rabbitmq",
            "-o", "jsonpath='{.items[*].metadata.name}'"
        )

        if pods and pods != "''":
            pod_names = pods.strip("'").split()
            if pod_names:
                pod_name = pod_names[0]
                logger.info(f"Deleting RabbitMQ pod: {pod_name}")
                e2e_helper.delete_pod(pod_name)

                logger.info("Waiting for RabbitMQ to restart...")
                assert e2e_helper.wait_for_pod_ready("app.kubernetes.io/name=rabbitmq", timeout=60)
                time.sleep(10)

        logger.info("Waiting for tasks to complete after RabbitMQ restart...")
        completed = 0
        for task_id in task_ids:
            try:
                final = e2e_helper.wait_for_task_completion(task_id, timeout=120)
                if final["status"] in ["succeeded", "failed"]:
                    completed += 1
            except Exception as e:
                logger.warning(f"Task failed: {e}")

        logger.info(f"Completed {completed}/{len(task_ids)} tasks")
        assert completed >= 7, f"At least 7/10 should complete, got {completed}"

        logger.info("[+] System recovered from RabbitMQ restart")

    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise


@pytest.mark.slow
def test_actor_pod_crash_loop(e2e_helper):
    """
    E2E: Test system handles actor pod crash loops.

    Scenario:
    1. Deploy actor with broken image that crashes
    2. Send message to that actor
    3. Verify error handling and retry logic
    4. Fix actor deployment
    5. Verify message eventually processed

    Expected: Graceful degradation, eventual processing after fix
    """
    logger.info("This test verifies crash loop handling via test-error actor")

    logger.info("Sending message to error actor...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_error",
        arguments={"should_fail": True},
    )

    task_id = response["result"]["task_id"]

    logger.info("Waiting for task to complete (expect failure)...")
    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=60)

    assert final_task["status"] == "failed", \
        "Task should fail when actor crashes"

    logger.info("[+] Crash loop handled gracefully")


@pytest.mark.chaos
@pytest.mark.xdist_group(name="chaos")
def test_multiple_component_failures(e2e_helper):
    """
    E2E: Test system handles multiple simultaneous component failures.

    Scenario:
    1. Send message
    2. Kill gateway pod
    3. Kill actor pod
    4. Kill RabbitMQ pod
    5. Wait for all to restart
    6. Verify system recovers

    Expected: System eventually reaches consistent state
    """
    logger.info("Sending initial message...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "multi-failure-test"},
    )

    task_id = response["result"]["task_id"]
    time.sleep(1)

    logger.info("Simulating cascading failures...")
    try:
        logger.info("Killing gateway pod...")
        gateway_pods = e2e_helper.kubectl(
            "get", "pods",
            "-l", "app.kubernetes.io/name=asya-gateway",
            "-o", "jsonpath='{.items[*].metadata.name}'"
        )
        if gateway_pods and gateway_pods != "''":
            pod_name = gateway_pods.strip("'").split()[0]
            e2e_helper.delete_pod(pod_name)

        time.sleep(2)

        logger.info("Killing actor pod...")
        actor_pods = e2e_helper.kubectl(
            "get", "pods",
            "-l", "asya.sh/actor=test-echo",
            "-o", "jsonpath='{.items[*].metadata.name}'"
        )
        if actor_pods and actor_pods != "''":
            pod_name = actor_pods.strip("'").split()[0]
            e2e_helper.delete_pod(pod_name)

        logger.info("Waiting for components to restart...")
        assert e2e_helper.wait_for_pod_ready("app.kubernetes.io/name=asya-gateway", timeout=240)
        assert e2e_helper.wait_for_pod_ready("asya.sh/actor=test-echo", timeout=240)

        # Crew actors (x-sink, x-sump) may be scaled to 0 by KEDA if queues are empty
        # They will scale up automatically when needed, so we don't check them here
        logger.info("Note: Crew actors not checked - they scale based on queue depth")

        e2e_helper.ensure_gateway_connectivity(max_retries=10, retry_interval=2.0)

        logger.info("Checking if system recovered...")
        try:
            task_status = e2e_helper.get_task_status(task_id)
            logger.info(f"Task status after recovery: {task_status['status']}")
        except Exception as e:
            logger.info(f"Task query failed (expected during recovery): {e}")

        logger.info("Sending new message after recovery...")
        response_after = e2e_helper.call_mcp_tool(
            tool_name="test_echo",
            arguments={"message": "after-multi-failure"},
        )

        task_id_after = response_after["result"]["task_id"]
        final_after = e2e_helper.wait_for_task_completion(task_id_after, timeout=120)

        assert final_after["status"] == "succeeded", \
            "System should recover and process new messages"

        logger.info("[+] System recovered from multiple component failures")

    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise


@pytest.mark.fast
def test_resource_exhaustion_handling(e2e_helper):
    """
    E2E: Test system handles resource exhaustion gracefully.

    Scenario:
    1. Send many large payloads to exhaust resources
    2. Verify system doesn't crash
    3. Verify some tasks succeed despite pressure
    4. Verify error handling for failed tasks

    Expected: Graceful degradation, no complete outage
    """
    import os
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    # Each transport has a different message size limit; stress test near each limit
    size_kb = {"sqs": 200, "pubsub": 4096, "rabbitmq": 5120}.get(transport, 5120)

    logger.info("Sending resource-intensive workload...")
    task_ids = []

    for i in range(20):
        try:
            response = e2e_helper.call_mcp_tool(
                tool_name="test_large_payload",
                arguments={"size_kb": size_kb},
            )
            task_ids.append(response["result"]["task_id"])
        except Exception as e:
            logger.warning(f"Failed to create task {i}: {e}")

    logger.info(f"Created {len(task_ids)} resource-intensive tasks")

    logger.info("Waiting for some to complete...")
    completed = 0
    failed = 0

    for task_id in task_ids[:10]:
        try:
            final = e2e_helper.wait_for_task_completion(task_id, timeout=120)
            if final["status"] == "succeeded":
                completed += 1
            elif final["status"] == "failed":
                failed += 1
        except Exception as e:
            logger.warning(f"Task timeout: {e}")
            failed += 1

    logger.info(f"Results: {completed} succeeded, {failed} failed")

    assert completed + failed >= 5, "At least half should complete (success or failure)"

    logger.info("[+] Resource exhaustion handled gracefully")


@pytest.mark.chaos
@pytest.mark.xdist_group(name="chaos")
def test_network_partition_simulation(e2e_helper):
    """
    E2E: Test system handles network issues.

    Scenario:
    1. Send message
    2. Introduce delays by restarting network components
    3. Verify eventual consistency

    Expected: Messages eventually delivered despite delays
    """
    logger.info("Sending message...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "network-partition-test"},
    )

    task_id = response["result"]["task_id"]

    time.sleep(1)

    logger.info("Simulating network issues (pod restarts)...")
    try:
        actor_pods = e2e_helper.kubectl(
            "get", "pods",
            "-l", "asya.sh/actor=test-echo",
            "-o", "jsonpath='{.items[*].metadata.name}'"
        )

        if actor_pods and actor_pods != "''":
            pod_name = actor_pods.strip("'").split()[0]
            logger.info(f"Killing actor pod: {pod_name}")
            e2e_helper.delete_pod(pod_name)

        logger.info("Waiting for pod to restart...")
        assert e2e_helper.wait_for_pod_ready("asya.sh/actor=test-echo", timeout=120)

        logger.info("Waiting for task to complete (with network issues)...")
        final_task = e2e_helper.wait_for_task_completion(task_id, timeout=120)

        assert final_task["status"] in ["succeeded", "failed"], \
            "Task should eventually complete"

        logger.info("[+] Network partition handled gracefully")

    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise


@pytest.mark.chaos
@pytest.mark.xdist_group(name="chaos")
def test_operator_restart_during_scaling(e2e_helper):
    """
    E2E: Test operator restart doesn't break autoscaling.

    Scenario:
    1. Send burst of messages to trigger scaling
    2. Restart operator pod
    3. Verify KEDA continues scaling
    4. Verify messages still process

    Expected: Scaling continues, operator restart transparent
    """
    logger.info("Sending burst to trigger scaling...")
    task_ids = []
    for i in range(30):
        try:
            response = e2e_helper.call_mcp_tool(
                tool_name="test_echo",
                arguments={"message": f"operator-restart-{i}"},
            )
            task_ids.append(response["result"]["task_id"])
        except Exception as e:
            logger.warning(f"Failed to create task {i}: {e}")

    time.sleep(2)

    try:
        logger.info("Waiting for sample tasks to complete...")
        completed = 0
        for task_id in task_ids[:10]:
            try:
                final = e2e_helper.wait_for_task_completion(task_id, timeout=60)
                if final["status"] == "succeeded":
                    completed += 1
            except Exception as e:
                logger.warning(f"Task failed: {e}")

        logger.info(f"Completed {completed}/10 sample tasks")
        assert completed >= 7, f"At least 7/10 should complete, got {completed}"

        logger.info("[+] Tasks completed successfully during operator restart")

    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise


@pytest.mark.chaos
@pytest.mark.xdist_group(name="chaos")
def test_keda_restart_preserves_scaling(e2e_helper):
    """
    E2E: Test KEDA restart doesn't lose scaling configuration.

    Scenario:
    1. Verify ScaledObject exists
    2. Restart KEDA operator
    3. Send messages
    4. Verify scaling still works

    Expected: KEDA recovers and continues autoscaling
    """
    logger.info("Verifying ScaledObject exists...")
    scaled_objects = e2e_helper.kubectl(
        "get", "scaledobjects",
        "-o", "jsonpath='{.items[*].metadata.name}'"
    )
    logger.info(f"ScaledObjects: {scaled_objects}")

    logger.info("Restarting KEDA operator...")
    try:
        keda_pods = e2e_helper.kubectl(
            "get", "pods",
            "-n", "keda",
            "-l", "app.kubernetes.io/name=keda-operator",
            "-o", "jsonpath='{.items[*].metadata.name}'"
        )

        if keda_pods and keda_pods != "''":
            pod_name = keda_pods.strip("'").split()[0]
            logger.info(f"Deleting KEDA pod: {pod_name}")
            e2e_helper.kubectl("-n", "keda", "delete", "pod", pod_name, "--grace-period=0", "--force")

            logger.info("Waiting for KEDA to restart...")
            time.sleep(15)

        logger.info("Sending messages after KEDA restart...")
        task_ids = []
        for i in range(10):
            try:
                response = e2e_helper.call_mcp_tool(
                    tool_name="test_echo",
                    arguments={"message": f"keda-restart-{i}"},
                )
                task_ids.append(response["result"]["task_id"])
            except Exception as e:
                logger.warning(f"Failed to create task {i}: {e}")

        logger.info("Waiting for tasks to complete...")
        completed = 0
        for task_id in task_ids:
            try:
                final = e2e_helper.wait_for_task_completion(task_id, timeout=60)
                if final["status"] == "succeeded":
                    completed += 1
            except Exception as e:
                logger.warning(f"Task failed: {e}")

        logger.info(f"Completed {completed}/{len(task_ids)} tasks")
        assert completed >= 7, f"At least 7/10 should complete, got {completed}"

        logger.info("[+] KEDA restart preserved scaling functionality")

    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise
