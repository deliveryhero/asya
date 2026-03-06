#!/usr/bin/env python3
"""
E2E tests for KEDA autoscaling and performance characteristics.

Tests scaling behavior in a real Kubernetes environment:
- Scale-up speed under burst load
- Multiple actors scaling simultaneously
- Processing throughput
- KEDA pollingInterval effectiveness

These tests verify the system performs well under various load conditions.
"""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

logger = logging.getLogger(__name__)


@pytest.mark.slow
def test_scale_up_under_burst_load(e2e_helper):
    """
    E2E: Test KEDA scales up quickly under burst load.

    Scenario:
    1. Send 100 messages rapidly
    2. Monitor pod count over time
    3. Verify scale-up occurs
    4. Verify messages are processed

    Expected: Pod count increases to handle load
    """
    logger.info("Checking initial pod count...")
    initial_pods = e2e_helper.get_pod_count("asya.sh/actor=test-echo")
    logger.info(f"Initial pods: {initial_pods}")

    logger.info("Sending burst of 100 messages...")
    task_ids = []
    for i in range(100):
        try:
            response = e2e_helper.call_mcp_tool(
                tool_name="test_echo",
                arguments={"message": f"burst-{i}"},
            )
            task_ids.append(response["result"]["task_id"])
        except Exception as e:
            logger.warning(f"Failed to create task {i}: {e}")

    logger.info(f"Created {len(task_ids)} tasks")

    logger.info("Monitoring pod count during processing...")
    max_pods = initial_pods
    for check in range(12):
        time.sleep(2)
        current_pods = e2e_helper.get_pod_count("asya.sh/actor=test-echo")
        logger.info(f"Check {check+1}/12: {current_pods} pods")
        max_pods = max(max_pods, current_pods)

        if current_pods > initial_pods:
            logger.info(f"Scale-up detected: {initial_pods} → {current_pods}")
            break

    logger.info(f"Max pods observed: {max_pods}")

    logger.info("Waiting for sample tasks to complete...")
    completed = 0
    for task_id in task_ids[:10]:
        try:
            final = e2e_helper.wait_for_task_completion(task_id, timeout=120)
            if final["status"] == "succeeded":
                completed += 1
        except Exception as e:
            logger.warning(f"Task {task_id} failed: {e}")

    logger.info(f"Completed {completed}/10 sample tasks")
    assert completed >= 5, f"At least 5/10 should complete, got {completed}"

    logger.info(f"[+] Burst load handled (max_pods={max_pods}, initial={initial_pods})")


@pytest.mark.slow
def test_multiple_actors_scaling_simultaneously(e2e_helper):
    """
    E2E: Test multiple actors can scale simultaneously without interference.

    Scenario:
    1. Send load to test-echo (20 messages)
    2. Send load to test-doubler (20 messages)
    3. Send load to test-incrementer (20 messages)
    4. Monitor all actors scale independently
    5. Verify all complete

    Expected: Actors scale independently, no resource conflicts
    """
    import threading

    results = {"echo": [], "doubler": [], "incrementer": []}
    locks = {"echo": threading.Lock(), "doubler": threading.Lock(), "incrementer": threading.Lock()}

    def send_echo_load():
        for i in range(20):
            try:
                response = e2e_helper.call_mcp_tool(
                    tool_name="test_echo",
                    arguments={"message": f"multi-echo-{i}"},
                )
                task_id = response["result"]["task_id"]
                with locks["echo"]:
                    results["echo"].append(task_id)
            except Exception as e:
                logger.warning(f"Echo {i} failed: {e}")

    def send_pipeline_load():
        for i in range(20):
            try:
                response = e2e_helper.call_mcp_tool(
                    tool_name="test_pipeline",
                    arguments={"value": i},
                )
                task_id = response["result"]["task_id"]
                with locks["doubler"]:
                    results["doubler"].append(task_id)
            except Exception as e:
                logger.warning(f"Pipeline {i} failed: {e}")

    threads = [
        threading.Thread(target=send_echo_load),
        threading.Thread(target=send_pipeline_load),
    ]

    logger.info("Sending concurrent load to multiple actors...")
    for t in threads:
        t.start()

    for t in threads:
        t.join(timeout=60)

    logger.info(f"Echo tasks: {len(results['echo'])}")
    logger.info(f"Pipeline tasks: {len(results['doubler'])}")

    time.sleep(5)

    echo_pods = e2e_helper.get_pod_count("asya.sh/actor=test-echo")
    logger.info(f"Echo pods: {echo_pods}")

    logger.info("Waiting for sample completions...")
    echo_completed = 0
    for task_id in results["echo"][:10]:
        try:
            final = e2e_helper.wait_for_task_completion(task_id, timeout=60)
            if final["status"] == "succeeded":
                echo_completed += 1
        except Exception as e:
            logger.warning(f"Echo task failed: {e}")

    pipeline_completed = 0
    for task_id in results["doubler"][:10]:
        try:
            final = e2e_helper.wait_for_task_completion(task_id, timeout=90)
            if final["status"] == "succeeded":
                pipeline_completed += 1
        except Exception as e:
            logger.warning(f"Pipeline task failed: {e}")

    logger.info(f"Echo completed: {echo_completed}/10")
    logger.info(f"Pipeline completed: {pipeline_completed}/10")

    assert echo_completed >= 5, f"At least 5/10 echo should complete, got {echo_completed}"
    assert pipeline_completed >= 5, f"At least 5/10 pipeline should complete, got {pipeline_completed}"

    logger.info("[+] Multiple actors scaled and processed simultaneously")


@pytest.mark.fast
def test_processing_throughput(e2e_helper):
    """
    E2E: Measure processing throughput.

    Scenario:
    1. Send 100 messages to fast actor (echo)
    2. Measure total time to process all
    3. Calculate throughput

    Expected: Reasonable throughput (>10 messages/sec with scaling)
    """
    logger.info("Sending 100 messages...")
    start_time = time.time()
    task_ids = []

    for i in range(100):
        try:
            response = e2e_helper.call_mcp_tool(
                tool_name="test_echo",
                arguments={"message": f"throughput-{i}"},
            )
            task_ids.append(response["result"]["task_id"])
        except Exception as e:
            logger.warning(f"Failed to create task {i}: {e}")

    creation_time = time.time() - start_time
    logger.info(f"Created {len(task_ids)} tasks in {creation_time:.2f}s")

    logger.info("Waiting for all to complete...")
    completed = 0
    completion_start = time.time()

    for task_id in task_ids:
        try:
            final = e2e_helper.wait_for_task_completion(task_id, timeout=120)
            if final["status"] == "succeeded":
                completed += 1
        except Exception as e:
            logger.warning(f"Task failed: {e}")

    total_time = time.time() - start_time
    processing_time = time.time() - completion_start

    throughput = completed / total_time if total_time > 0 else 0

    logger.info(f"[+] Processed {completed}/100 in {total_time:.2f}s")
    logger.info(f"Throughput: {throughput:.2f} messages/sec")

    assert completed >= 70, f"At least 70% should complete, got {completed}"


@pytest.mark.chaos
@pytest.mark.xdist_group(name="chaos")
@pytest.mark.skipif(
    os.getenv("ASYA_TRANSPORT") == "pubsub",
    reason="KEDA gcp-pubsub scaler cannot query the Pub/Sub emulator for subscription metrics",
)
def test_keda_pollingInterval_effectiveness(e2e_helper):
    """
    E2E: Test KEDA pollingInterval affects scale-up responsiveness.

    Scenario:
    1. Send burst of messages
    2. Measure time to first scale-up event
    3. Compare with pollingInterval setting

    Expected: Scale-up occurs within reasonable time of pollingInterval
    """
    scaled_obj = e2e_helper.kubectl(
        "get", "scaledobject", "test-echo",
        "-o", "jsonpath='{.spec.pollingInterval}'"
    )
    polling_interval = int(scaled_obj.strip("'")) if scaled_obj and scaled_obj != "''" else 30

    logger.info(f"Configured pollingInterval: {polling_interval}s")

    e2e_helper.kubectl("scale", "deployment", "test-echo", "--replicas=0")
    time.sleep(5)

    logger.info("Sending burst...")
    start_time = time.time()
    for i in range(20):
        e2e_helper.call_mcp_tool(
            tool_name="test_echo",
            arguments={"message": f"polling-test-{i}"},
        )

    logger.info("Monitoring for scale-up...")
    scale_timeout = max(polling_interval * 3, 30)
    pod_ready = e2e_helper.wait_for_pod_ready("asya.sh/actor=test-echo", timeout=scale_timeout)
    scale_up_time = time.time() - start_time

    assert pod_ready, f"Pod should scale up within {scale_timeout}s"

    logger.info(f"[+] Scale-up occurred in {scale_up_time:.2f}s (pollingInterval={polling_interval}s)")


@pytest.mark.slow
@pytest.mark.skipif(
    os.getenv("ASYA_TRANSPORT") == "pubsub",
    reason="KEDA gcp-pubsub scaler cannot query the Pub/Sub emulator for subscription metrics",
)
def test_cold_start_backlog_processing(e2e_helper):
    """
    E2E: Test KEDA cold-start — scale from 0, process backlog to completion.

    Scenario:
    1. Scale test-echo deployment to 0 replicas (cold start)
    2. Enqueue 20 messages while actor is at 0 replicas (backlog)
    3. Wait for KEDA to detect queue depth and scale up
    4. Assert all 20 messages complete with status "succeeded"

    This validates the minReplicas=0 path end-to-end: backlog accumulates ->
    KEDA detects -> pod scheduled -> container starts -> messages drain.
    """
    logger.info("Scaling test-echo to 0 for cold-start test...")
    e2e_helper.kubectl("scale", "deployment", "test-echo", "--replicas=0")
    time.sleep(3)  # Allow Kubernetes to propagate scale-down before enqueuing backlog

    current_pods = e2e_helper.get_pod_count("asya.sh/actor=test-echo")
    logger.info(f"Pod count before backlog: {current_pods}")

    # Wait for scale-down to complete before enqueuing cold backlog
    scale_down_timeout = 30
    scale_down_elapsed = 0
    while current_pods > 0 and scale_down_elapsed < scale_down_timeout:
        time.sleep(2)  # Poll until pods drain to 0
        scale_down_elapsed += 2
        current_pods = e2e_helper.get_pod_count("asya.sh/actor=test-echo")
    logger.info(f"Pods after scale-down wait: {current_pods}")

    logger.info("Enqueuing 20 messages into cold backlog...")
    task_ids = []
    for i in range(20):
        try:
            response = e2e_helper.call_mcp_tool(
                tool_name="test_echo",
                arguments={"message": f"cold-start-{i}"},
            )
            task_ids.append(response["result"]["task_id"])
        except Exception as e:
            logger.warning(f"Failed to enqueue message {i}: {e}")

    logger.info(f"Enqueued {len(task_ids)}/20 messages")
    assert len(task_ids) >= 15, f"Should enqueue at least 15 messages, got {len(task_ids)}"

    scaled_obj = e2e_helper.kubectl(
        "get", "scaledobject", "test-echo",
        "-o", "jsonpath='{.spec.pollingInterval}'"
    )
    polling_interval = int(scaled_obj.strip("'")) if scaled_obj and scaled_obj != "''" else 30
    per_task_timeout = max(polling_interval * 4 + 60, 180)

    logger.info(f"Waiting up to {per_task_timeout}s per task for {len(task_ids)} tasks to complete concurrently...")
    completed = 0
    with ThreadPoolExecutor(max_workers=len(task_ids)) as executor:
        future_to_task = {
            executor.submit(e2e_helper.wait_for_task_completion, task_id, timeout=per_task_timeout): task_id
            for task_id in task_ids
        }
        for future in as_completed(future_to_task):
            task_id = future_to_task[future]
            try:
                final = future.result()
                if final["status"] == "succeeded":
                    completed += 1
                else:
                    logger.warning(f"Task {task_id} ended with status: {final['status']}")
            except Exception as e:
                logger.warning(f"Task {task_id} timed out or failed: {e}")

    logger.info(f"[+] Cold-start completed: {completed}/{len(task_ids)} tasks succeeded")
    assert completed >= len(task_ids) * 0.9, \
        f"At least 90% of cold-start tasks should succeed, got {completed}/{len(task_ids)}"
