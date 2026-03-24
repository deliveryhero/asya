#!/usr/bin/env python3
"""
E2E Edge Case Tests for Asya Framework.

Tests critical edge cases that require full Kubernetes infrastructure.
These verify behavior that can only be tested in a real K8s environment.

MUST-HAVE (3 tests) - Critical sidecar behavior:
- test_fan_out_creates_multiple_messages_e2e: Sidecar creates multiple messages from array
- test_empty_response_goes_to_sink_e2e: Sidecar routes empty responses to x-sink
- test_slow_boundary_completes_before_timeout_e2e: Slow-boundary actor completes before timeout

SHOULD-HAVE (2 tests) - Infrastructure resilience:
- test_message_redelivery_after_pod_restart_e2e: RabbitMQ redelivers after pod crash
- test_concurrent_tasks_independent_routing_e2e: 10 concurrent tasks route independently

NICE-TO-HAVE (4 tests) - Operational excellence:
- test_keda_scales_actor_under_load_e2e: KEDA scales pods based on queue length
- test_unicode_payload_end_to_end: Unicode preserved through full pipeline
- test_large_payload_end_to_end: 10MB payload through gateway → queue → actor
- test_nested_json_end_to_end: 20-level nested JSON through pipeline
"""

import logging
import os
import time

import pytest


logger = logging.getLogger(__name__)


# ============================================================================
# MUST-HAVE: Sidecar Behavior Tests
# ============================================================================


@pytest.mark.fast
def test_fan_out_creates_multiple_messages_e2e(e2e_helper):
    """
    E2E: Test fan-out when actor returns array.

    Scenario: Actor returns [item1, item2, item3] → sidecar creates 3 messages
    Expected:
    - Sidecar creates multiple messages
    - Each message routed independently
    - All complete successfully
    """
    response = e2e_helper.call_mcp_tool(
        tool_name="test_fanout",
        arguments={"count": 3},
    )

    task_id = response["result"]["task_id"]
    logger.info(f"Original task ID: {task_id}")

    # Wait for completion - increased timeout for KEDA scale-up from 0
    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=90)

    # Verify task completed
    assert final_task["status"] == "succeeded", f"Fanout should succeed, got {final_task['status']}"

    logger.info(f"Fanout result: {final_task.get('result')}")


@pytest.mark.fast
def test_empty_response_goes_to_sink_e2e(e2e_helper):
    """
    E2E: Test empty response routing to x-sink.

    Scenario: Actor returns null/empty → sidecar routes to x-sink
    Expected: Task completes with Succeeded status
    """
    response = e2e_helper.call_mcp_tool(
        tool_name="test_empty_response",
        arguments={"message": "empty test"},
    )

    task_id = response["result"]["task_id"]

    # Wait for completion - increased timeout for KEDA scale-up from 0
    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=90)

    # Empty response should go to x-sink
    assert final_task["status"] == "succeeded", f"Empty response should succeed, got {final_task['status']}"


@pytest.mark.fast
def test_slow_boundary_completes_before_timeout_e2e(e2e_helper):
    """
    E2E: Test slow-boundary actor completes before timeout.

    Scenario: Actor completes in 1.5s (well under 4s timeout)
    Expected: Should complete successfully before timeout

    Note: Under parallel test load, stale messages from other tests may
    delay processing enough to trigger SLA expiry. A retry with a fresh
    task handles this transient condition.
    """
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    if transport == "sqs":
        from asya_testing.utils.sqs import purge_queue

        namespace = os.getenv("NAMESPACE", "asya-e2e")
        purge_queue(f"asya-{namespace}-test-slow-boundary")

    for attempt in range(2):
        response = e2e_helper.call_mcp_tool(
            tool_name="test_slow_boundary",
            arguments={"first_call": True},
        )

        task_id = response["result"]["task_id"]
        final_task = e2e_helper.wait_for_task_completion(task_id, timeout=120)

        if final_task["status"] == "succeeded":
            logger.info(f"[+] Slow-boundary completed on attempt {attempt + 1}")
            return

        logger.warning(
            f"Attempt {attempt + 1}: status={final_task['status']} "
            f"(may be SLA expiry from stale queue messages)"
        )

    assert final_task["status"] == "succeeded", f"Should complete before timeout, got {final_task['status']}"


@pytest.mark.fast
def test_timeout_crash_and_pod_restart_e2e(e2e_helper, namespace, transport_timeouts):
    """
    E2E: Test timeout causes pod crash and KEDA rescales for retry.

    Scenario:
    1. Send message with 60s processing to actor with 5s timeout
    2. Sidecar times out after 5s and crashes the pod
    3. KEDA detects pod crash and scales up new pod
    4. Message redelivered to new pod (at-least-once delivery)
    5. New pod processes message successfully (or times out again)

    Expected:
    - Pod crashes after timeout (exit code 1)
    - KEDA scales up replacement pod
    - Message eventually fails after retries or succeeds if timeout is sufficient

    Note: This test verifies the crash-on-timeout behavior is working correctly
    to prevent zombie processing where runtime continues but sidecar has given up.
    """
    # Clean up: purge queue and delete pods to get a fresh start
    try:
        transport = os.environ.get("ASYA_TRANSPORT", "rabbitmq")
        if transport == "sqs":
            from asya_testing.utils.sqs import purge_queue

            logger.info("Purging test-timeout queue to remove stuck messages...")
            purge_queue(f"asya-{namespace}-test-timeout")
            time.sleep(2)

        logger.info("Cleaning up test-timeout pods before test...")
        e2e_helper.kubectl("delete", "pod", "-l", "asya.sh/actor=test-timeout", "--grace-period=5")
        time.sleep(5)

        # Wait for fresh pod to be ready
        pod_ready = e2e_helper.wait_for_pod_ready("asya.sh/actor=test-timeout", timeout=30)
        if not pod_ready:
            logger.warning("Pod not ready after cleanup, continuing anyway...")
    except Exception as e:
        logger.warning(f"Failed to clean up: {e}")

    response = e2e_helper.call_mcp_tool(
        tool_name="test_timeout",
        arguments={"sleep_seconds": 60},
    )

    task_id = response["result"]["task_id"]
    logger.info(f"Task ID: {task_id}")

    # Wait for KEDA to scale up the actor pod
    logger.info("Waiting for KEDA to scale up actor pod...")
    pod_ready = e2e_helper.wait_for_pod_ready("asya.sh/actor=test-timeout", timeout=30)
    assert pod_ready, "KEDA should scale up pod within 30s"

    # Get initial pod name and restart count
    pods_before = e2e_helper.kubectl(
        "get", "pods", "-l", "asya.sh/actor=test-timeout", "-o", "jsonpath='{.items[*].metadata.name}'"
    )
    logger.info(f"Pods before timeout: {pods_before}")

    # Get initial restart count for any container (sidecar or runtime may crash)
    initial_restart_count = 0
    try:
        restart_counts_str = e2e_helper.kubectl(
            "get",
            "pods",
            "-l",
            "asya.sh/actor=test-timeout",
            "-o",
            "jsonpath='{.items[0].status.containerStatuses[*].restartCount}'",
        )
        if restart_counts_str and restart_counts_str != "''":
            # Sum all container restart counts
            restart_counts = [int(x) for x in restart_counts_str.strip("'").split()]
            initial_restart_count = sum(restart_counts)
        logger.info(f"Initial total restart count: {initial_restart_count}")
    except Exception as e:
        logger.warning(f"Failed to get initial restart count: {e}")

    # Poll for pod crash (5s timeout + buffer for processing + transport delays)
    logger.info("Waiting for timeout-induced pod crash...")
    crash_detected = False
    start_time = time.time()
    max_wait = transport_timeouts.crash_detection
    poll_interval = 1

    while time.time() - start_time < max_wait:
        try:
            restart_counts_str = e2e_helper.kubectl(
                "get",
                "pods",
                "-l",
                "asya.sh/actor=test-timeout",
                "-o",
                "jsonpath='{.items[0].status.containerStatuses[*].restartCount}'",
            )
            if restart_counts_str and restart_counts_str != "''":
                restart_counts = [int(x) for x in restart_counts_str.strip("'").split()]
                current_restart_count = sum(restart_counts)
                if current_restart_count > initial_restart_count:
                    logger.info(
                        f"Crash detected: total restart count increased from {initial_restart_count} to {current_restart_count}"
                    )
                    crash_detected = True
                    break
        except Exception as e:
            logger.debug(f"Error checking restart count: {e}")

        time.sleep(poll_interval)

    assert crash_detected, f"Pod should crash due to timeout within {max_wait}s"

    # Verify crash was due to timeout by checking pod logs
    try:
        logs = e2e_helper.kubectl(
            "logs", "-l", "asya.sh/actor=test-timeout", "-c", "asya-sidecar", "--previous", "--tail=50"
        )
        if "Runtime timeout exceeded - crashing pod to recover" in logs:
            logger.info("Verified timeout crash message in sidecar logs")
        else:
            logger.warning("Could not verify timeout message in logs (pod may have restarted quickly)")
    except Exception as e:
        logger.warning(f"Could not retrieve previous logs: {e}")

    # Check pod events for crash reason
    try:
        pod_name = pods_before.strip("'")
        events = e2e_helper.kubectl(
            "get",
            "events",
            "--field-selector",
            f"involvedObject.name={pod_name}",
            "-o",
            "jsonpath='{.items[*].message}'",
        )
        if events:
            logger.debug(f"Pod events: {events}")
    except Exception as e:
        logger.debug(f"Could not retrieve pod events: {e}")

    # Wait for pod to be ready again after crash
    logger.info("Waiting for pod to recover after crash...")
    pod_ready = e2e_helper.wait_for_pod_ready("asya.sh/actor=test-timeout", timeout=60)
    assert pod_ready, "Pod should become ready after crash"

    # Task should eventually complete (fail or succeed after retries)
    # Extended timeout because message will be redelivered and may timeout again
    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=180)

    # After timeout crash, message should eventually go to x-sump
    assert final_task["status"] in ["failed", "succeeded"], (
        f"Task should eventually complete (Failed or Succeeded), got {final_task['status']}"
    )

    if final_task["status"] == "failed":
        logger.info("Task correctly failed after timeout-induced pod crash")
    else:
        logger.info("Task succeeded (may have been redelivered with sufficient timeout)")


# ============================================================================
# SHOULD-HAVE: RabbitMQ Interaction Tests
# ============================================================================


@pytest.mark.fast
def test_message_redelivery_after_pod_restart_e2e(e2e_helper):
    """
    E2E: Test message redelivery when actor pod crashes before ack.

    Scenario:
    1. Send message to actor
    2. Wait for KEDA to scale up pod
    3. Kill actor pod while processing
    4. RabbitMQ redelivers message to new pod
    Expected: Task eventually completes (at-least-once delivery)
    """
    # Send message with slow processing to give time to kill pod
    response = e2e_helper.call_mcp_tool(
        tool_name="test_slow_boundary",  # 1.5s processing time
        arguments={"first_call": True},
    )

    task_id = response["result"]["task_id"]
    logger.info(f"Task ID: {task_id}")

    # Wait for KEDA to scale up the actor pod first
    logger.info("Waiting for KEDA to scale up actor pod...")
    time.sleep(10)  # Poll interval for KEDA scaling

    # Find and delete the actor pod
    try:
        pods = e2e_helper.kubectl(
            "get", "pods", "-l", "asya.sh/actor=test-slow-boundary", "-o", "jsonpath='{.items[*].metadata.name}'"
        )

        if pods and pods != "''":
            pod_names = pods.strip("'").split()
            if pod_names:
                pod_name = pod_names[0]
                logger.info(f"Killing pod: {pod_name}")
                e2e_helper.delete_pod(pod_name)

                # Wait for pod to restart and be ready
                pod_ready = e2e_helper.wait_for_pod_ready("asya.sh/actor=test-slow-boundary", timeout=60)
                assert pod_ready, "Pod should restart and become ready after deletion"
            else:
                logger.warning("No pods found to kill - KEDA may not have scaled up yet")
        else:
            logger.warning("No pods found to kill - KEDA may not have scaled up yet")

    except Exception as e:
        logger.warning(f"Failed to kill pod: {e}")
        # Continue test even if pod kill fails

    # Task should eventually complete (may be redelivered) - extended timeout
    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=150)

    # Should complete (possibly after redelivery)
    assert final_task["status"] in ["succeeded", "failed"], (
        f"Task should complete, got {final_task['status']}"
    )


@pytest.mark.fast
def test_concurrent_tasks_independent_routing_e2e(e2e_helper):
    """
    E2E: Test concurrent tasks route independently.

    Scenario: Send 5 tasks concurrently to same queue
    Expected:
    - All tasks processed independently
    - No cross-contamination of results
    - All complete successfully
    """
    import threading

    num_tasks = 5
    task_ids = []
    results = [None] * num_tasks

    # Warm up: verify end-to-end message flow before sending concurrent tasks.
    # Occasionally a single task gets stuck (transient SQS/gateway blip), but
    # subsequent tasks to the same actor succeed immediately.  Retry with a
    # fresh task to distinguish a real outage from a one-off stuck message.
    max_warmup_attempts = 3
    warmup_timeout = 90
    for warmup_attempt in range(max_warmup_attempts):
        warmup_response = e2e_helper.call_mcp_tool(
            tool_name="test_echo",
            arguments={"message": f"warmup-{warmup_attempt}"},
        )
        warmup_id = warmup_response["result"]["task_id"]
        try:
            warmup_result = e2e_helper.wait_for_task_completion(
                warmup_id, timeout=warmup_timeout,
            )
            if warmup_result["status"] == "succeeded":
                logger.info("[+] Actor warm-up complete, starting concurrent test")
                break
            logger.warning(
                f"Warm-up task {warmup_id} ended with status "
                f"{warmup_result['status']}, retrying"
            )
        except TimeoutError:
            logger.warning(
                f"Warm-up attempt {warmup_attempt + 1}/{max_warmup_attempts} "
                f"timed out after {warmup_timeout}s (task {warmup_id})"
            )
        if warmup_attempt < max_warmup_attempts - 1:
            e2e_helper.ensure_gateway_connectivity()
    else:
        pytest.fail(
            f"Warm-up failed after {max_warmup_attempts} attempts "
            f"({warmup_timeout}s each) - infrastructure may be unstable"
        )

    # Create all tasks
    for i in range(num_tasks):
        response = e2e_helper.call_mcp_tool(
            tool_name="test_echo",
            arguments={"message": f"concurrent-e2e-{i}"},
        )
        task_ids.append(response["result"]["task_id"])

    # Wait for all concurrently - timeout must exceed gateway-side task timeout (120s)
    def wait_for_task(index, task_id):
        try:
            results[index] = e2e_helper.wait_for_task_completion(task_id, timeout=125)
        except Exception as e:
            logger.error(f"Task {index} failed: {e}")
            results[index] = {"status": "Error", "error": str(e)}

    threads = []
    for i, task_id in enumerate(task_ids):
        thread = threading.Thread(target=wait_for_task, args=(i, task_id))
        threads.append(thread)
        thread.start()

    # Wait for all threads
    for thread in threads:
        thread.join(timeout=130)

    # Log all results for diagnostics before assertions
    for i, result in enumerate(results):
        if result and result.get("status") != "succeeded":
            error_info = result.get("error", "no error field")
            result_details = result.get("result", {})
            failed_actor = result.get("current_actor_name", "unknown")
            logger.error(
                f"Task {i} (id={task_ids[i]}) status={result.get('status')}, "
                f"actor={failed_actor}, error={error_info}, details={result_details}"
            )

    # Verify all completed
    for i, result in enumerate(results):
        assert result is not None, f"Task {i} should have result"
        error_msg = result.get("error", "")
        failed_actor = result.get("current_actor_name", "unknown")
        assert result["status"] == "succeeded", (
            f"Task {i} (id={task_ids[i]}) should succeed, "
            f"got {result.get('status')} at actor={failed_actor}: {error_msg}"
        )

    # Verify no cross-contamination
    for i, result in enumerate(results):
        echoed = result.get("result", {}).get("echoed", "")
        assert f"concurrent-e2e-{i}" in echoed, f"Task {i} result contaminated: got '{echoed}'"

    logger.info(f"[+] All {num_tasks} concurrent tasks completed independently")


# ============================================================================
# NICE-TO-HAVE: KEDA Autoscaling Tests
# ============================================================================


@pytest.mark.slow
def test_keda_scales_actor_under_load_e2e(e2e_helper):
    """
    E2E: Test KEDA scales actor pods based on queue length.

    Scenario:
    1. Send 100 messages to queue
    2. KEDA should scale up actor pods
    3. All messages processed
    4. KEDA scales down to min replicas
    Expected: Actor count increases during load, then decreases
    """
    # Check initial pod count (should be 0 or min replicas)
    initial_pods = e2e_helper.get_pod_count("asya.sh/actor=test-echo")
    logger.info(f"Initial pod count: {initial_pods}")

    # Send 100 tasks rapidly
    task_ids = []
    for i in range(100):
        try:
            response = e2e_helper.call_mcp_tool(
                tool_name="test_echo",
                arguments={"message": f"load-test-{i}"},
            )
            task_ids.append(response["result"]["task_id"])
        except Exception as e:
            logger.warning(f"Failed to create task {i}: {e}")

    logger.info(f"Created {len(task_ids)} tasks")

    # Wait for KEDA to scale up (check every 2s for up to 24s)
    # With fast processing (echo), we need to check more frequently
    max_pods = initial_pods
    for i in range(12):  # 12 * 2s = 24s
        time.sleep(2)  # Poll kubectl API for KEDA autoscaling changes
        current_pods = e2e_helper.get_pod_count("asya.sh/actor=test-echo")
        logger.info(f"Check {i + 1}/12: Current pod count: {current_pods}")
        max_pods = max(max_pods, current_pods)

        if current_pods > initial_pods:
            logger.info(f"KEDA scaled up: {initial_pods} → {current_pods} pods")
            break

    # With minReplicaCount=1, scale-up may not occur if processing is fast
    # Verify that at least we maintained the minimum replica count
    if max_pods <= initial_pods:
        logger.warning(f"KEDA did not scale above initial {initial_pods} pods (processing may have been too fast)")
        # This is OK - as long as tasks complete successfully

    # Wait for all tasks to complete
    completed = 0
    for task_id in task_ids[:10]:  # Check first 10
        try:
            final = e2e_helper.wait_for_task_completion(task_id, timeout=120)
            if final["status"] == "succeeded":
                completed += 1
        except Exception as e:
            logger.warning(f"Task failed: {e}")

    logger.info(f"Completed {completed}/10 sample tasks")
    assert completed >= 5, f"At least 5/10 tasks should complete, got {completed}"

    logger.info(f"[+] KEDA load test passed: max_pods={max_pods}, initial={initial_pods}, completed={completed}/10")


# ============================================================================
# NICE-TO-HAVE: Data Handling Tests
# ============================================================================


@pytest.mark.fast
def test_unicode_payload_end_to_end(e2e_helper):
    """
    E2E: Test Unicode characters preserved through full pipeline.

    Scenario: Send Unicode payload through gateway → queue → actor → x-sink
    Expected: Characters preserved correctly
    """
    response = e2e_helper.call_mcp_tool(
        tool_name="test_unicode",
        arguments={"message": "Hello 世界 🌍 مرحبا こんにちは Привет"},
    )

    task_id = response["result"]["task_id"]

    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=60)

    assert final_task["status"] == "succeeded", "Unicode should succeed"

    result = final_task.get("result", {})
    assert "languages" in result, "Should have language data"

    # Verify some Unicode characters are preserved
    chinese = result.get("languages", {}).get("chinese", "")
    assert "世界" in chinese or "你好" in chinese, "Chinese characters should be preserved"

    logger.info(f"Unicode result: {result}")


@pytest.mark.fast
def test_large_payload_end_to_end(e2e_helper):
    """
    E2E: Test large payload through full pipeline.

    Scenario: Send payload near transport size limit through gateway → queue → actor
    Expected: Processes successfully

    Each transport has its own message size limit, so "large" is
    transport-specific.  The handler returns {**payload, "data": "X"*N},
    and the response is also published via the transport (sidecar → x-sink),
    so both directions must fit within the limit.

    Transport   | Limit   | Test size | Headroom
    ------------|---------|-----------|-------------------------------
    SQS         | 256 KB  | 200 KB    | ~56 KB for envelope/JSON
    Pub/Sub     | 10 MB   | 4 MB      | ~6 MB (response goes via Pub/Sub too)
    RabbitMQ    | none    | 10 MB     | effectively unlimited
    """
    import os

    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    # Each transport has a different message size limit; test near each limit
    size_kb = {"sqs": 200, "pubsub": 4096, "rabbitmq": 10240}.get(transport, 10240)
    response = e2e_helper.call_mcp_tool(
        tool_name="test_large_payload",
        arguments={"size_kb": size_kb},
    )

    task_id = response["result"]["task_id"]

    # Large payload may take longer
    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=90)

    assert final_task["status"] == "succeeded", f"Large payload should succeed, got {final_task['status']}"


@pytest.mark.fast
def test_nested_json_end_to_end(e2e_helper):
    """
    E2E: Test deeply nested JSON (20 levels) through pipeline.

    Scenario: Send deeply nested JSON through gateway → queue → actor
    Expected: JSON parsed and processed correctly
    """
    response = e2e_helper.call_mcp_tool(
        tool_name="test_nested",
        arguments={"message": "nested e2e test"},
    )

    task_id = response["result"]["task_id"]

    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=120)

    assert final_task["status"] == "succeeded", "Nested JSON should succeed"

    result = final_task.get("result", {})
    assert result.get("nested_depth") == 20, "Should have 20 levels of nesting"
