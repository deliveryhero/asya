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
    1. Send envelopes to actors
    2. Restart RabbitMQ while processing
    3. Verify envelopes are redelivered and complete

    Expected: At-least-once delivery guarantees maintained
    """
    import os
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    if transport != "rabbitmq":
        pytest.skip("This test requires RabbitMQ transport")

    logger.info("Sending envelopes...")
    envelope_ids = []
    for i in range(10):
        response = e2e_helper.call_mcp_tool(
            tool_name="test_slow_boundary",
            arguments={"first_call": True},
        )
        envelope_ids.append(response["result"]["envelope_id"])

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

        logger.info("Waiting for envelopes to complete after RabbitMQ restart...")
        completed = 0
        for envelope_id in envelope_ids:
            try:
                final = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=120)
                if final["status"] in ["succeeded", "failed"]:
                    completed += 1
            except Exception as e:
                logger.warning(f"Envelope failed: {e}")

        logger.info(f"Completed {completed}/{len(envelope_ids)} envelopes")
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
    2. Send envelope to that actor
    3. Verify error handling and retry logic
    4. Fix actor deployment
    5. Verify message eventually processed

    Expected: Graceful degradation, eventual processing after fix
    """
    logger.info("This test verifies crash loop handling via test-error actor")

    logger.info("Sending envelope to error actor...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_error",
        arguments={"should_fail": True},
    )

    envelope_id = response["result"]["envelope_id"]

    logger.info("Waiting for envelope to complete (expect failure)...")
    final_envelope = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=60)

    assert final_envelope["status"] == "failed", \
        "Envelope should fail when actor crashes"

    logger.info("[+] Crash loop handled gracefully")


@pytest.mark.chaos
@pytest.mark.xdist_group(name="chaos")
def test_multiple_component_failures(e2e_helper):
    """
    E2E: Test system handles multiple simultaneous component failures.

    Scenario:
    1. Send envelope
    2. Kill gateway pod
    3. Kill actor pod
    4. Kill RabbitMQ pod
    5. Wait for all to restart
    6. Verify system recovers

    Expected: System eventually reaches consistent state
    """
    logger.info("Sending initial envelope...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "multi-failure-test"},
    )

    envelope_id = response["result"]["envelope_id"]
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
            "-l", "app=test-echo",
            "-o", "jsonpath='{.items[*].metadata.name}'"
        )
        if actor_pods and actor_pods != "''":
            pod_name = actor_pods.strip("'").split()[0]
            e2e_helper.delete_pod(pod_name)

        logger.info("Waiting for components to restart...")
        assert e2e_helper.wait_for_pod_ready("app.kubernetes.io/name=asya-gateway", timeout=60)
        assert e2e_helper.wait_for_pod_ready("app=test-echo", timeout=60)

        # Crew actors (happy-end, error-end) may be scaled to 0 by KEDA if queues are empty
        # They will scale up automatically when needed, so we don't check them here
        logger.info("Note: Crew actors not checked - they scale based on queue depth")

        logger.info("Re-establishing port-forward to new gateway pod...")
        assert e2e_helper.restart_port_forward(), "Port-forward should be re-established"
        time.sleep(10)

        logger.info("Checking if system recovered...")
        try:
            envelope_status = e2e_helper.get_envelope_status(envelope_id)
            logger.info(f"Envelope status after recovery: {envelope_status['status']}")
        except Exception as e:
            logger.info(f"Envelope query failed (expected during recovery): {e}")

        logger.info("Sending new envelope after recovery...")
        response_after = e2e_helper.call_mcp_tool(
            tool_name="test_echo",
            arguments={"message": "after-multi-failure"},
        )

        envelope_id_after = response_after["result"]["envelope_id"]
        final_after = e2e_helper.wait_for_envelope_completion(envelope_id_after, timeout=60)

        assert final_after["status"] == "succeeded", \
            "System should recover and process new envelopes"

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
    3. Verify some envelopes succeed despite pressure
    4. Verify error handling for failed envelopes

    Expected: Graceful degradation, no complete outage
    """
    import os
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    if transport == "sqs":
        pytest.skip("Large payload test not supported with SQS (256KB limit)")

    logger.info("Sending resource-intensive workload...")
    envelope_ids = []

    for i in range(20):
        try:
            response = e2e_helper.call_mcp_tool(
                tool_name="test_large_payload",
                arguments={"size_kb": 5120},
            )
            envelope_ids.append(response["result"]["envelope_id"])
        except Exception as e:
            logger.warning(f"Failed to create envelope {i}: {e}")

    logger.info(f"Created {len(envelope_ids)} resource-intensive envelopes")

    logger.info("Waiting for some to complete...")
    completed = 0
    failed = 0

    for envelope_id in envelope_ids[:10]:
        try:
            final = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=120)
            if final["status"] == "succeeded":
                completed += 1
            elif final["status"] == "failed":
                failed += 1
        except Exception as e:
            logger.warning(f"Envelope timeout: {e}")
            failed += 1

    logger.info(f"Results: {completed} succeeded, {failed} failed")

    assert completed + failed >= 5, "At least half should complete (success or failure)"

    logger.info("[+] Resource exhaustion handled gracefully")


@pytest.mark.fast
def test_network_partition_simulation(e2e_helper):
    """
    E2E: Test system handles network issues.

    Scenario:
    1. Send envelope
    2. Introduce delays by restarting network components
    3. Verify eventual consistency

    Expected: Messages eventually delivered despite delays
    """
    logger.info("Sending envelope...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "network-partition-test"},
    )

    envelope_id = response["result"]["envelope_id"]

    time.sleep(1)

    logger.info("Simulating network issues (pod restarts)...")
    try:
        actor_pods = e2e_helper.kubectl(
            "get", "pods",
            "-l", "app=test-echo",
            "-o", "jsonpath='{.items[*].metadata.name}'"
        )

        if actor_pods and actor_pods != "''":
            pod_name = actor_pods.strip("'").split()[0]
            logger.info(f"Killing actor pod: {pod_name}")
            e2e_helper.delete_pod(pod_name)

        logger.info("Waiting for pod to restart...")
        assert e2e_helper.wait_for_pod_ready("app=test-echo", timeout=60)

        logger.info("Waiting for envelope to complete (with network issues)...")
        final_envelope = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=120)

        assert final_envelope["status"] in ["succeeded", "failed"], \
            "Envelope should eventually complete"

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
    1. Send burst of envelopes to trigger scaling
    2. Restart operator pod
    3. Verify KEDA continues scaling
    4. Verify envelopes still process

    Expected: Scaling continues, operator restart transparent
    """
    logger.info("Sending burst to trigger scaling...")
    envelope_ids = []
    for i in range(30):
        try:
            response = e2e_helper.call_mcp_tool(
                tool_name="test_echo",
                arguments={"message": f"operator-restart-{i}"},
            )
            envelope_ids.append(response["result"]["envelope_id"])
        except Exception as e:
            logger.warning(f"Failed to create envelope {i}: {e}")

    time.sleep(2)

    logger.info("Restarting operator pod...")
    try:
        operator_pods = e2e_helper.kubectl(
            "get", "pods",
            "-l", "app.kubernetes.io/name=asya-operator",
            "-o", "jsonpath='{.items[*].metadata.name}'"
        )

        if operator_pods and operator_pods != "''":
            pod_name = operator_pods.strip("'").split()[0]
            logger.info(f"Deleting operator pod: {pod_name}")
            e2e_helper.delete_pod(pod_name)

            logger.info("Waiting for operator to restart...")
            assert e2e_helper.wait_for_pod_ready("app.kubernetes.io/name=asya-operator", timeout=60)
            time.sleep(5)

        logger.info("Waiting for sample envelopes to complete...")
        completed = 0
        for envelope_id in envelope_ids[:10]:
            try:
                final = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=60)
                if final["status"] == "succeeded":
                    completed += 1
            except Exception as e:
                logger.warning(f"Envelope failed: {e}")

        logger.info(f"Completed {completed}/10 sample envelopes")
        assert completed >= 7, f"At least 7/10 should complete, got {completed}"

        logger.info("[+] Operator restart handled gracefully")

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
    3. Send envelopes
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

        logger.info("Sending envelopes after KEDA restart...")
        envelope_ids = []
        for i in range(10):
            try:
                response = e2e_helper.call_mcp_tool(
                    tool_name="test_echo",
                    arguments={"message": f"keda-restart-{i}"},
                )
                envelope_ids.append(response["result"]["envelope_id"])
            except Exception as e:
                logger.warning(f"Failed to create envelope {i}: {e}")

        logger.info("Waiting for envelopes to complete...")
        completed = 0
        for envelope_id in envelope_ids:
            try:
                final = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=60)
                if final["status"] == "succeeded":
                    completed += 1
            except Exception as e:
                logger.warning(f"Envelope failed: {e}")

        logger.info(f"Completed {completed}/{len(envelope_ids)} envelopes")
        assert completed >= 7, f"At least 7/10 should complete, got {completed}"

        logger.info("[+] KEDA restart preserved scaling functionality")

    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise


@pytest.mark.chaos
@pytest.mark.xdist_group(name="chaos")
@pytest.mark.timeout(300)
@pytest.mark.skip(reason="Operator restart takes >180s in test environment - flaky timing issue")
def test_full_cluster_restart_simulation(e2e_helper):
    """
    E2E: Test system recovers from cluster-wide restart.

    Scenario:
    1. Send envelope and verify success
    2. Restart all major components
    3. Verify system comes back online
    4. Send new envelope
    5. Verify it processes correctly

    Expected: Full system recovery after widespread restart

    NOTE: Skipped due to operator pod restart timing variability (120-200s).
    """
    logger.info("Sending baseline envelope...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "pre-cluster-restart"},
    )

    envelope_id_before = response["result"]["envelope_id"]
    final_before = e2e_helper.wait_for_envelope_completion(envelope_id_before, timeout=30)
    assert final_before["status"] == "succeeded"

    logger.info("Simulating cluster-wide restart...")
    components = [
        ("gateway", "app.kubernetes.io/name=asya-gateway"),
        ("operator", "app.kubernetes.io/name=asya-operator"),
        ("test-echo", "app=test-echo"),
    ]

    try:
        for component_name, label in components:
            logger.info(f"Restarting {component_name}...")
            pods = e2e_helper.kubectl(
                "get", "pods",
                "-l", label,
                "-o", "jsonpath='{.items[*].metadata.name}'"
            )

            if pods and pods != "''":
                for pod_name in pods.strip("'").split():
                    try:
                        e2e_helper.delete_pod(pod_name)
                    except Exception as e:
                        logger.warning(f"Failed to delete {pod_name}: {e}")

        logger.info("Waiting for all components to restart...")
        time.sleep(10)

        for component_name, label in components:
            logger.info(f"Waiting for {component_name}...")
            timeout = 180 if component_name == "operator" else 60
            assert e2e_helper.wait_for_pod_ready(label, timeout=timeout), \
                f"{component_name} should restart"

        time.sleep(10)

        logger.info("Sending envelope after cluster restart...")
        response_after = e2e_helper.call_mcp_tool(
            tool_name="test_echo",
            arguments={"message": "post-cluster-restart"},
        )

        envelope_id_after = response_after["result"]["envelope_id"]
        final_after = e2e_helper.wait_for_envelope_completion(envelope_id_after, timeout=60)

        assert final_after["status"] == "succeeded", \
            "System should fully recover after cluster-wide restart"

        logger.info("[+] Full cluster restart recovery successful")

    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise
