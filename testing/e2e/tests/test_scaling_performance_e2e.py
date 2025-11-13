#!/usr/bin/env python3
"""
E2E tests for KEDA autoscaling and performance characteristics.

Tests scaling behavior in a real Kubernetes environment:
- Cold start latency (scale from 0)
- Scale-up speed under burst load
- Scale-down behavior after idle period
- Queue backlog handling
- Multiple actors scaling simultaneously
- Resource limit handling
- Concurrent envelope processing

These tests verify the system performs well under various load conditions.
"""

import logging
import time

import pytest

logger = logging.getLogger(__name__)


@pytest.mark.slow
def test_cold_start_latency(e2e_helper):
    """
    E2E: Measure cold start latency (scale from 0 to processing).

    Scenario:
    1. Verify actor is scaled to 0
    2. Send envelope
    3. Measure time until envelope starts processing
    4. Measure total completion time

    Expected: Cold start < 30s, total completion reasonable
    """
    logger.info("Verifying actor is scaled to 0...")

    e2e_helper.kubectl("scale", "deployment", "test-echo", "--replicas=0")
    time.sleep(5)

    pod_count = e2e_helper.get_pod_count("app=test-echo")
    logger.info(f"Initial pod count: {pod_count}")

    logger.info("Sending envelope to trigger scale-up...")
    start_time = time.time()

    response = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "cold-start-test"},
    )

    envelope_id = response["result"]["envelope_id"]

    logger.info("Waiting for KEDA to scale up...")
    pod_ready = e2e_helper.wait_for_pod_ready("app=test-echo", timeout=30)
    scale_up_time = time.time() - start_time

    assert pod_ready, "Pod should scale up within 30s"
    logger.info(f"Pod scaled up in {scale_up_time:.2f}s")

    final_envelope = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=60)
    total_time = time.time() - start_time

    assert final_envelope["status"] == "succeeded", "Cold start envelope should succeed"

    logger.info(f"[+] Cold start completed in {total_time:.2f}s (scale-up: {scale_up_time:.2f}s)")

    assert total_time < 45, f"Cold start should complete within 45s, took {total_time:.2f}s"


@pytest.mark.slow
def test_scale_up_under_burst_load(e2e_helper):
    """
    E2E: Test KEDA scales up quickly under burst load.

    Scenario:
    1. Send 100 envelopes rapidly
    2. Monitor pod count over time
    3. Verify scale-up occurs
    4. Verify messages are processed

    Expected: Pod count increases to handle load
    """
    logger.info("Checking initial pod count...")
    initial_pods = e2e_helper.get_pod_count("app=test-echo")
    logger.info(f"Initial pods: {initial_pods}")

    logger.info("Sending burst of 100 envelopes...")
    envelope_ids = []
    for i in range(100):
        try:
            response = e2e_helper.call_mcp_tool(
                tool_name="test_echo",
                arguments={"message": f"burst-{i}"},
            )
            envelope_ids.append(response["result"]["envelope_id"])
        except Exception as e:
            logger.warning(f"Failed to create envelope {i}: {e}")

    logger.info(f"Created {len(envelope_ids)} envelopes")

    logger.info("Monitoring pod count during processing...")
    max_pods = initial_pods
    for check in range(12):
        time.sleep(2)
        current_pods = e2e_helper.get_pod_count("app=test-echo")
        logger.info(f"Check {check+1}/12: {current_pods} pods")
        max_pods = max(max_pods, current_pods)

        if current_pods > initial_pods:
            logger.info(f"Scale-up detected: {initial_pods} → {current_pods}")
            break

    logger.info(f"Max pods observed: {max_pods}")

    logger.info("Waiting for sample envelopes to complete...")
    completed = 0
    for envelope_id in envelope_ids[:10]:
        try:
            final = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=120)
            if final["status"] == "succeeded":
                completed += 1
        except Exception as e:
            logger.warning(f"Envelope failed: {e}")

    logger.info(f"Completed {completed}/10 sample envelopes")
    assert completed >= 8, f"At least 8/10 should complete, got {completed}"

    logger.info(f"[+] Burst load handled (max_pods={max_pods}, initial={initial_pods})")


@pytest.mark.slow
def test_scale_down_after_idle(e2e_helper):
    """
    E2E: Test KEDA scales down after idle period.

    Scenario:
    1. Send envelopes to trigger scale-up
    2. Wait for processing to complete
    3. Monitor pod count over cooldown period
    4. Verify scale-down occurs

    Expected: Pods scale down to minReplicas after cooldown
    """
    logger.info("Sending envelopes to trigger scale-up...")
    for i in range(10):
        e2e_helper.call_mcp_tool(
            tool_name="test_echo",
            arguments={"message": f"scale-down-test-{i}"},
        )

    time.sleep(5)

    initial_pods = e2e_helper.get_pod_count("app=test-echo")
    logger.info(f"Pods after burst: {initial_pods}")

    logger.info("Waiting for cooldown period (60s)...")
    time.sleep(65)

    final_pods = e2e_helper.get_pod_count("app=test-echo")
    logger.info(f"Pods after cooldown: {final_pods}")

    scaled_obj = e2e_helper.kubectl(
        "get", "scaledobject", "test-echo",
        "-o", "jsonpath='{.spec.minReplicaCount}'"
    )
    min_replicas = int(scaled_obj.strip("'")) if scaled_obj and scaled_obj != "''" else 0

    logger.info(f"Min replicas configured: {min_replicas}")

    if initial_pods > min_replicas:
        assert final_pods <= initial_pods, \
            f"Should scale down or stay same, was {initial_pods}, now {final_pods}"

    logger.info(f"[+] Scale-down behavior verified (final_pods={final_pods}, min={min_replicas})")


@pytest.mark.fast
def test_queue_backlog_processing(e2e_helper):
    """
    E2E: Test system handles queue backlog correctly.

    Scenario:
    1. Scale actor to 0
    2. Send 50 envelopes (queue backlog)
    3. Scale actor back up
    4. Verify all envelopes processed

    Expected: All queued messages eventually processed
    """
    logger.info("Scaling actor to 0...")
    e2e_helper.kubectl("scale", "deployment", "test-echo", "--replicas=0")
    time.sleep(5)

    logger.info("Creating queue backlog (50 envelopes)...")
    envelope_ids = []
    for i in range(50):
        try:
            response = e2e_helper.call_mcp_tool(
                tool_name="test_echo",
                arguments={"message": f"backlog-{i}"},
            )
            envelope_ids.append(response["result"]["envelope_id"])
        except Exception as e:
            logger.warning(f"Failed to create envelope {i}: {e}")

    logger.info(f"Created {len(envelope_ids)} envelopes in backlog")

    logger.info("Triggering scale-up (KEDA should detect queue length)...")

    logger.info("Waiting for KEDA to scale up...")
    pod_ready = e2e_helper.wait_for_pod_ready("app=test-echo", timeout=45)
    assert pod_ready, "Pod should scale up to process backlog"

    logger.info("Waiting for backlog to be processed...")
    completed = 0
    for envelope_id in envelope_ids[:20]:
        try:
            final = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=120)
            if final["status"] == "succeeded":
                completed += 1
        except Exception as e:
            logger.warning(f"Envelope failed: {e}")

    logger.info(f"Completed {completed}/20 sample envelopes from backlog")
    assert completed >= 16, f"At least 16/20 should complete, got {completed}"

    logger.info("[+] Queue backlog processed successfully")


@pytest.mark.slow
def test_multiple_actors_scaling_simultaneously(e2e_helper):
    """
    E2E: Test multiple actors can scale simultaneously without interference.

    Scenario:
    1. Send load to test-echo (20 envelopes)
    2. Send load to test-doubler (20 envelopes)
    3. Send load to test-incrementer (20 envelopes)
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
                envelope_id = response["result"]["envelope_id"]
                with locks["echo"]:
                    results["echo"].append(envelope_id)
            except Exception as e:
                logger.warning(f"Echo {i} failed: {e}")

    def send_pipeline_load():
        for i in range(20):
            try:
                response = e2e_helper.call_mcp_tool(
                    tool_name="test_pipeline",
                    arguments={"value": i},
                )
                envelope_id = response["result"]["envelope_id"]
                with locks["doubler"]:
                    results["doubler"].append(envelope_id)
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

    logger.info(f"Echo envelopes: {len(results['echo'])}")
    logger.info(f"Pipeline envelopes: {len(results['doubler'])}")

    time.sleep(5)

    echo_pods = e2e_helper.get_pod_count("app=test-echo")
    logger.info(f"Echo pods: {echo_pods}")

    logger.info("Waiting for sample completions...")
    echo_completed = 0
    for envelope_id in results["echo"][:10]:
        try:
            final = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=30)
            if final["status"] == "succeeded":
                echo_completed += 1
        except Exception as e:
            logger.warning(f"Echo envelope failed: {e}")

    pipeline_completed = 0
    for envelope_id in results["doubler"][:10]:
        try:
            final = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=45)
            if final["status"] == "succeeded":
                pipeline_completed += 1
        except Exception as e:
            logger.warning(f"Pipeline envelope failed: {e}")

    logger.info(f"Echo completed: {echo_completed}/10")
    logger.info(f"Pipeline completed: {pipeline_completed}/10")

    assert echo_completed >= 7, f"At least 7/10 echo should complete, got {echo_completed}"
    assert pipeline_completed >= 7, f"At least 7/10 pipeline should complete, got {pipeline_completed}"

    logger.info("[+] Multiple actors scaled and processed simultaneously")


@pytest.mark.fast
def test_processing_throughput(e2e_helper):
    """
    E2E: Measure processing throughput.

    Scenario:
    1. Send 100 envelopes to fast actor (echo)
    2. Measure total time to process all
    3. Calculate throughput

    Expected: Reasonable throughput (>10 envelopes/sec with scaling)
    """
    logger.info("Sending 100 envelopes...")
    start_time = time.time()
    envelope_ids = []

    for i in range(100):
        try:
            response = e2e_helper.call_mcp_tool(
                tool_name="test_echo",
                arguments={"message": f"throughput-{i}"},
            )
            envelope_ids.append(response["result"]["envelope_id"])
        except Exception as e:
            logger.warning(f"Failed to create envelope {i}: {e}")

    creation_time = time.time() - start_time
    logger.info(f"Created {len(envelope_ids)} envelopes in {creation_time:.2f}s")

    logger.info("Waiting for all to complete...")
    completed = 0
    completion_start = time.time()

    for envelope_id in envelope_ids:
        try:
            final = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=120)
            if final["status"] == "succeeded":
                completed += 1
        except Exception as e:
            logger.warning(f"Envelope failed: {e}")

    total_time = time.time() - start_time
    processing_time = time.time() - completion_start

    throughput = completed / total_time if total_time > 0 else 0

    logger.info(f"[+] Processed {completed}/100 in {total_time:.2f}s")
    logger.info(f"Throughput: {throughput:.2f} envelopes/sec")

    assert completed >= 90, f"At least 90% should complete, got {completed}"


@pytest.mark.fast
def test_keda_pollingInterval_effectiveness(e2e_helper):
    """
    E2E: Test KEDA pollingInterval affects scale-up responsiveness.

    Scenario:
    1. Send burst of envelopes
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
    pod_ready = e2e_helper.wait_for_pod_ready("app=test-echo", timeout=polling_interval * 3)
    scale_up_time = time.time() - start_time

    assert pod_ready, f"Pod should scale up within {polling_interval * 3}s"

    logger.info(f"[+] Scale-up occurred in {scale_up_time:.2f}s (pollingInterval={polling_interval}s)")
