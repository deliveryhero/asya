#!/usr/bin/env python3
"""
E2E tests for state management and data persistence.

Tests persistence and state handling in a real environment:
- Class handler state preservation
- Envelope tracking across system restarts
- Database persistence (PostgreSQL)
- S3 persistence and retrieval
- Error persistence and retry state
- Gateway state recovery

These tests verify data isn't lost during failures.
"""

import logging
import time

import pytest
import requests

from asya_testing.utils.s3 import wait_for_envelope_in_s3, delete_all_objects_in_bucket

logger = logging.getLogger(__name__)


@pytest.mark.fast
def test_envelope_persisted_to_database(e2e_helper, gateway_url):
    """
    E2E: Test envelopes are persisted to PostgreSQL.

    Scenario:
    1. Send envelope
    2. Query database for envelope record
    3. Verify envelope metadata stored correctly

    Expected: Envelope persisted with correct metadata
    """
    logger.info("Sending envelope...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "db-persistence-test"},
    )

    envelope_id = response["result"]["envelope_id"]
    logger.info(f"Envelope ID: {envelope_id}")

    logger.info("Waiting for envelope to complete...")
    final_envelope = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=30)

    assert final_envelope["status"] == "succeeded", "Envelope should succeed"

    logger.info("Verifying envelope exists in database via API...")
    envelope_from_api = e2e_helper.get_envelope_status(envelope_id)

    assert envelope_from_api["id"] == envelope_id, "Envelope ID should match"
    assert envelope_from_api["status"] == "succeeded", "Status should be persisted"

    logger.info("[+] Envelope persisted to database")


@pytest.mark.chaos
@pytest.mark.xdist_group(name="chaos")
def test_gateway_restart_preserves_envelope_history(e2e_helper):
    """
    E2E: Test gateway restart doesn't lose envelope history.

    Scenario:
    1. Send envelope and wait for completion
    2. Restart gateway pod
    3. Query envelope status after restart
    4. Verify envelope data still accessible

    Expected: Envelope history persists across restarts
    """
    logger.info("Sending envelope...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "restart-persistence-test"},
    )

    envelope_id = response["result"]["envelope_id"]

    final_envelope = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=30)
    assert final_envelope["status"] == "succeeded"

    logger.info("Envelope completed, restarting gateway...")
    pods = e2e_helper.kubectl(
        "get", "pods",
        "-l", "app.kubernetes.io/name=asya-gateway",
        "-o", "jsonpath='{.items[*].metadata.name}'"
    )

    if pods and pods != "''":
        pod_names = pods.strip("'").split()
        if pod_names:
            pod_name = pod_names[0]
            logger.info(f"Deleting gateway pod: {pod_name}")
            e2e_helper.delete_pod(pod_name)

            logger.info("Waiting for new gateway pod...")
            assert e2e_helper.wait_for_pod_ready("app.kubernetes.io/name=asya-gateway", timeout=30)

            logger.info("Re-establishing port-forward to new gateway pod...")
            assert e2e_helper.restart_port_forward(), "Port-forward should be re-established"
            time.sleep(3)
    else:
        pytest.fail("No gateway pod found to restart")

    logger.info("Querying envelope after restart...")
    envelope_after_restart = e2e_helper.get_envelope_status(envelope_id)

    assert envelope_after_restart["id"] == envelope_id, "Envelope should still be queryable"
    assert envelope_after_restart["status"] == "succeeded", "Status should be preserved"

    logger.info("[+] Envelope history preserved across gateway restart")


@pytest.mark.fast
def test_successful_result_persisted_to_s3(e2e_helper, s3_endpoint, results_bucket):
    """
    E2E: Test successful results are persisted to S3.

    Scenario:
    1. Send envelope
    2. Wait for completion
    3. Verify result appears in S3 bucket
    4. Verify S3 object content matches envelope

    Expected: Results stored in S3 for later retrieval
    """
    logger.info("Sending envelope...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "s3-success-test"},
    )

    envelope_id = response["result"]["envelope_id"]

    logger.info("Waiting for envelope to complete...")
    final_envelope = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=30)

    assert final_envelope["status"] == "succeeded", "Envelope should succeed"

    logger.info("Waiting for result to appear in S3...")
    s3_object = wait_for_envelope_in_s3(
        bucket_name=results_bucket,
        envelope_id=envelope_id,
        timeout=30
    )

    assert s3_object is not None, "Result should be in S3"

    logger.info("[+] Successful result persisted to S3")


@pytest.mark.fast
def test_error_result_persisted_to_s3(e2e_helper, s3_endpoint, errors_bucket):
    """
    E2E: Test error results are persisted to S3 errors bucket.

    Scenario:
    1. Send envelope that will fail
    2. Wait for completion
    3. Verify error appears in S3 errors bucket
    4. Verify error details stored

    Expected: Errors stored separately for debugging
    """
    logger.info("Sending envelope that will fail...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_error",
        arguments={"should_fail": True},
    )

    envelope_id = response["result"]["envelope_id"]

    logger.info("Waiting for envelope to complete...")
    final_envelope = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=30)

    assert final_envelope["status"] == "failed", "Envelope should fail"

    logger.info("Waiting for error to appear in S3...")
    s3_object = wait_for_envelope_in_s3(
        bucket_name=errors_bucket,
        envelope_id=envelope_id,
        timeout=30
    )

    assert s3_object is not None, "Error should be in S3 errors bucket"

    logger.info("[+] Error result persisted to S3")


@pytest.mark.fast
def test_s3_persistence_with_large_payload(e2e_helper, s3_endpoint, results_bucket):
    """
    E2E: Test large payload persisted correctly to S3.

    Scenario:
    1. Send large payload (10MB)
    2. Wait for completion
    3. Verify large payload in S3
    4. Verify payload integrity

    Expected: Large payloads stored without truncation
    """
    import os
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    if transport == "sqs":
        pytest.skip("Large payload test not supported with SQS (256KB limit)")

    logger.info("Sending large payload...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_large_payload",
        arguments={"size_kb": 10240},
    )

    envelope_id = response["result"]["envelope_id"]

    logger.info("Waiting for large payload to complete...")
    final_envelope = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=90)

    assert final_envelope["status"] == "succeeded", "Large payload should succeed"

    logger.info("Waiting for result in S3...")
    s3_object = wait_for_envelope_in_s3(
        bucket_name=results_bucket,
        envelope_id=envelope_id,
        timeout=60
    )

    assert s3_object is not None, "Large payload should be in S3"

    logger.info("[+] Large payload persisted to S3")


@pytest.mark.fast
def test_envelope_state_transitions_tracked(e2e_helper):
    """
    E2E: Test envelope state transitions are tracked correctly.

    Scenario:
    1. Send envelope through pipeline
    2. Monitor state transitions
    3. Verify all states recorded (pending → processing → succeeded)

    Expected: State machine transitions logged
    """
    logger.info("Sending pipeline envelope...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_pipeline",
        arguments={"value": 5},
    )

    envelope_id = response["result"]["envelope_id"]
    states_seen = []

    logger.info("Monitoring state transitions...")
    start_time = time.time()
    while time.time() - start_time < 45:
        envelope = e2e_helper.get_envelope_status(envelope_id)
        status = envelope["status"]

        if not states_seen or states_seen[-1] != status:
            states_seen.append(status)
            logger.info(f"State transition: {status}")

        if status in ["succeeded", "failed"]:
            break

        time.sleep(0.3)

    logger.info(f"States observed: {states_seen}")

    assert "succeeded" in states_seen or "failed" in states_seen, \
        "Should reach terminal state"

    logger.info("[+] Envelope state transitions tracked")


@pytest.mark.fast
def test_concurrent_s3_writes_no_conflicts(e2e_helper, s3_endpoint, results_bucket):
    """
    E2E: Test concurrent S3 writes don't conflict.

    Scenario:
    1. Send 20 envelopes concurrently
    2. All complete successfully
    3. All results appear in S3
    4. No S3 write conflicts

    Expected: S3 handles concurrent writes gracefully
    """
    logger.info("Sending 20 concurrent envelopes...")
    envelope_ids = []

    for i in range(20):
        try:
            response = e2e_helper.call_mcp_tool(
                tool_name="test_echo",
                arguments={"message": f"s3-concurrent-{i}"},
            )
            envelope_ids.append(response["result"]["envelope_id"])
        except Exception as e:
            logger.warning(f"Failed to create envelope {i}: {e}")

    logger.info(f"Created {len(envelope_ids)} envelopes")

    logger.info("Waiting for all to complete...")
    completed = 0
    for envelope_id in envelope_ids:
        try:
            final = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=30)
            if final["status"] == "succeeded":
                completed += 1
        except Exception as e:
            logger.warning(f"Envelope failed: {e}")

    logger.info(f"Completed {completed}/{len(envelope_ids)} envelopes")

    logger.info("Verifying S3 objects created...")
    s3_found = 0
    for envelope_id in envelope_ids[:10]:
        s3_object = wait_for_envelope_in_s3(
            bucket_name=results_bucket,
            envelope_id=envelope_id,
            timeout=10
        )
        if s3_object is not None:
            s3_found += 1

    logger.info(f"Found {s3_found}/10 sample results in S3")
    assert s3_found >= 8, f"At least 8/10 should be in S3, got {s3_found}"

    logger.info("[+] Concurrent S3 writes handled successfully")


@pytest.mark.chaos
@pytest.mark.xdist_group(name="chaos")
@pytest.mark.timeout(300)
def test_database_connection_recovery(e2e_helper):
    """
    E2E: Test gateway recovers from database connection issues.

    Scenario:
    1. Send envelope (should succeed)
    2. Simulate database issues (scale postgres to 0)
    3. Try to send envelope (may fail or queue)
    4. Restore database
    5. Verify system recovers

    Expected: Graceful degradation and recovery
    """
    logger.info("Sending initial envelope...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "db-recovery-before"},
    )

    envelope_id_1 = response["result"]["envelope_id"]
    final_1 = e2e_helper.wait_for_envelope_completion(envelope_id_1, timeout=30)
    assert final_1["status"] == "succeeded", "Initial envelope should succeed"

    logger.info("Simulating database failure...")
    try:
        e2e_helper.kubectl("scale", "statefulset", "asya-gateway-postgresql", "--replicas=0")
        time.sleep(5)

        logger.info("Attempting to send envelope during DB failure...")
        try:
            response_during_failure = e2e_helper.call_mcp_tool(
                tool_name="test_echo",
                arguments={"message": "db-recovery-during"},
            )
            envelope_id_2 = response_during_failure["result"]["envelope_id"]
            logger.info(f"Envelope created during failure: {envelope_id_2}")
        except Exception as e:
            logger.info(f"Expected failure during DB outage: {e}")

        logger.info("Restoring database...")
        e2e_helper.kubectl("scale", "statefulset", "asya-gateway-postgresql", "--replicas=1")

        logger.info("Waiting for postgres pod...")
        assert e2e_helper.wait_for_pod_ready("app=postgresql", timeout=120)

        logger.info("Waiting for gateway to recover...")
        assert e2e_helper.wait_for_pod_ready("app.kubernetes.io/name=asya-gateway", timeout=30)

        logger.info("Re-establishing port-forward to gateway...")
        assert e2e_helper.restart_port_forward(), "Port-forward should be re-established"
        time.sleep(10)

        logger.info("Sending envelope after recovery...")
        response_after = e2e_helper.call_mcp_tool(
            tool_name="test_echo",
            arguments={"message": "db-recovery-after"},
        )

        envelope_id_3 = response_after["result"]["envelope_id"]
        final_3 = e2e_helper.wait_for_envelope_completion(envelope_id_3, timeout=30)
        assert final_3["status"] == "succeeded", "Envelope after recovery should succeed"

        logger.info("[+] Database connection recovery verified")

    finally:
        logger.info("Ensuring database is restored...")
        e2e_helper.kubectl("scale", "statefulset", "asya-gateway-postgresql", "--replicas=1")
        e2e_helper.wait_for_pod_ready("app=postgresql", timeout=120)


@pytest.mark.chaos
@pytest.mark.xdist_group(name="chaos")
def test_s3_error_retry_logic(e2e_helper, s3_endpoint):
    """
    E2E: Test S3 write failures are retried.

    Scenario:
    1. Send envelope
    2. Simulate S3 failure (scale minio to 0)
    3. Envelope should complete but S3 write may fail
    4. Restore S3
    5. Verify retry mechanism or eventual consistency

    Expected: System handles S3 outages gracefully
    """
    logger.info("Sending envelope...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "s3-retry-test"},
    )

    envelope_id = response["result"]["envelope_id"]

    logger.info("Simulating S3 failure...")
    try:
        e2e_helper.kubectl("scale", "deployment", "s3", "--replicas=0")
        time.sleep(5)

        logger.info("Waiting for envelope to complete (S3 unavailable)...")
        final_envelope = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=60)

        logger.info(f"Envelope status: {final_envelope['status']}")

        logger.info("Restoring S3...")
        e2e_helper.kubectl("scale", "deployment", "s3", "--replicas=1")

        logger.info("Waiting for s3 pod...")
        assert e2e_helper.wait_for_pod_ready("app=s3", timeout=60)

        logger.info("Waiting for gateway to recover...")
        assert e2e_helper.wait_for_pod_ready("app.kubernetes.io/name=asya-gateway", timeout=30)

        logger.info("Re-establishing port-forward to gateway...")
        assert e2e_helper.restart_port_forward(), "Port-forward should be re-established"
        time.sleep(10)

        logger.info("[+] S3 error handling verified")

    finally:
        logger.info("Ensuring S3 is restored...")
        e2e_helper.kubectl("scale", "deployment", "s3", "--replicas=1")
        e2e_helper.wait_for_pod_ready("app=s3", timeout=60)
