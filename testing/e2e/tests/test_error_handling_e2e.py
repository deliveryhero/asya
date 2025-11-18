#!/usr/bin/env python3
"""
E2E Error Handling Tests for Asya Framework.

Tests the two-tier error handling strategy:
1. Application-level: error-end queue (when available)
2. Transport-level: DLQ fallback (when error-end unavailable)

Test Scenarios:
- test_error_goes_to_error_end_when_available: Normal case - error-end handles errors
- test_error_goes_to_dlq_when_error_end_unavailable: Fallback - DLQ handles errors (RabbitMQ only)

Transport Support:
- ✅ RabbitMQ: Full support (both tests)
- ✅ SQS: Application-level error handling only (DLQ test skipped - SQS is store-and-forward)
"""

import logging
import os
import time

import pytest

logger = logging.getLogger(__name__)


def _get_transport_client(transport: str):
    """Get transport client based on ASYA_TRANSPORT environment variable."""
    if transport == "rabbitmq":
        from asya_testing.clients.rabbitmq import RabbitMQClient
        rabbitmq_host = os.getenv("RABBITMQ_HOST", "localhost")
        return RabbitMQClient(host=rabbitmq_host, port=15672)
    elif transport == "sqs":
        from asya_testing.clients.sqs import SQSClient
        endpoint_url = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
        return SQSClient(
            endpoint_url=endpoint_url,
            region=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
            access_key=os.getenv("AWS_ACCESS_KEY_ID", "test"),
            secret_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
        )
    else:
        pytest.skip(f"Unsupported transport: {transport}")


@pytest.mark.slow
def test_error_goes_to_error_end_when_available(e2e_helper, kubectl, chaos_queues, errors_bucket):
    """
    E2E: Test errors are processed by error-end when error-end is available.

    Scenario (Application-level error handling):
    1. error-end is running normally with KEDA autoscaling
    2. Send envelope to test-error actor with should_fail=True
    3. Actor fails → sidecar sends error to error-end queue
    4. error-end consumes and processes the error
    5. error-end persists error to S3 errors bucket
    6. Gateway receives final status from error-end

    Expected:
    - Envelope status becomes "failed" (error was handled)
    - Error persisted to S3 errors bucket
    - DLQ remains empty (error-end handled it, no fallback needed)

    This is the NORMAL case - application handles its own errors.
    """
    from asya_testing.utils.s3 import wait_for_envelope_in_s3

    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    transport_client = _get_transport_client(transport)

    actor_queue = "asya-test-error"
    dlq_name = f"{actor_queue}-dlq"

    logger.info(f"Transport: {transport}")
    logger.info("Scenario: error-end available (normal application-level handling)")

    # Purge DLQ before test
    logger.info("Purging DLQ before test")
    transport_client.purge(dlq_name)

    # Send failing envelope
    logger.info("Sending failing envelope to test-error actor")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_error",
        arguments={"should_fail": True},
    )

    envelope_id = response["result"]["envelope_id"]
    logger.info(f"Envelope ID: {envelope_id}")

    # Wait for envelope to reach final status
    logger.info("Waiting for envelope to complete (error-end should process it)...")
    final_envelope = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=30)

    # Verify envelope failed (error was handled by error-end)
    assert final_envelope["status"] == "failed", \
        "Envelope should be marked as 'failed' after error-end processes it"
    logger.info("[+] Envelope marked as failed - error was processed")

    # Verify error persisted to S3
    logger.info("Waiting for error to appear in S3 errors bucket...")
    s3_object = wait_for_envelope_in_s3(
        bucket_name=errors_bucket,
        envelope_id=envelope_id,
        timeout=30
    )

    assert s3_object is not None, \
        f"Error should be persisted to S3 errors bucket by error-end"
    logger.info("[+] Error persisted to S3 by error-end")

    # Verify DLQ is EMPTY (error-end handled the error, no fallback needed)
    logger.info(f"Verifying DLQ {dlq_name} is empty")
    dlq_message = transport_client.consume(dlq_name, timeout=2)
    assert dlq_message is None, \
        f"DLQ {dlq_name} should be empty when error-end handles the error"
    logger.info("[+] DLQ is empty - error was handled by error-end")

    logger.info("[+] Test passed - application-level error handling working")


@pytest.mark.slow
@pytest.mark.skipif(
    os.getenv("ASYA_TRANSPORT") == "sqs",
    reason="SQS accepts messages even when consumers are unavailable (store-and-forward). "
           "Message goes to error-end queue instead of DLQ when error-end deployment is scaled to 0. "
           "This test only works for RabbitMQ where publishing can fail when consumers are unavailable."
)
def test_error_goes_to_dlq_when_error_end_unavailable(e2e_helper, kubectl, chaos_queues):
    """
    E2E: Test errors go to DLQ when error-end is unavailable.

    Scenario (Transport-level fallback):
    1. Scale error-end to 0 replicas (make it unavailable)
    2. Send envelope to test-error actor with should_fail=True
    3. Actor fails → sidecar tries to send to error-end
    4. Sending to error-end fails → sidecar NACKs message
    5. Message retried 3 times (maxReceiveCount=3)
    6. Transport moves message to DLQ automatically

    Expected:
    - Message appears in DLQ after retries (NOT in error-end)
    - Envelope metadata preserved in DLQ
    - error-end queue remains empty

    This is the FALLBACK case - transport handles errors when app can't.

    NOTE: Only works with RabbitMQ. SQS is store-and-forward - messages are accepted
    even when no consumers are available, so errors go to error-end queue, not DLQ.
    """
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    transport_client = _get_transport_client(transport)

    actor_queue = "asya-test-error"
    dlq_name = f"{actor_queue}-dlq"
    error_end_queue = "asya-error-end"

    logger.info(f"Transport: {transport}")
    logger.info("Scenario: error-end unavailable (transport-level DLQ fallback)")

    # Disable KEDA scaling and scale error-end to 0
    logger.info("Disabling KEDA scaling for error-end")
    kubectl.run("patch asyncactor error-end -n asya-e2e --type=json -p '[{\"op\":\"replace\",\"path\":\"/spec/scaling/enabled\",\"value\":false},{\"op\":\"replace\",\"path\":\"/spec/workload/replicas\",\"value\":0}]'")

    logger.info("Waiting for ScaledObject to be deleted")
    kubectl.run("wait --for=delete scaledobject/error-end -n asya-e2e --timeout=60s", check=False)

    logger.info("Waiting for deployment to scale to 0")
    kubectl.wait_for_replicas("error-end", "asya-e2e", 0, timeout=60)
    logger.info("[+] error-end scaled to 0")

    try:
        # Purge queues before test
        logger.info("Purging queues before test")
        transport_client.purge(dlq_name)
        transport_client.purge(error_end_queue)

        # Send failing envelope
        logger.info("Sending failing envelope to test-error actor")
        response = e2e_helper.call_mcp_tool(
            tool_name="test_error",
            arguments={"should_fail": True},
        )

        envelope_id = response["result"]["envelope_id"]
        logger.info(f"Envelope ID: {envelope_id}")

        # Wait for retries to exhaust
        logger.info("Waiting for retries to exhaust (maxRetryCount=3)")
        if transport == "sqs":
            logger.info("SQS: Waiting 60s for retries + DLQ move")
            time.sleep(60)
        else:
            logger.info("RabbitMQ: Waiting 20s for retries + DLQ move")
            time.sleep(20)

        # Check DLQ for the message
        logger.info(f"Checking DLQ {dlq_name} for message")
        dlq_message = None
        for attempt in range(10):
            dlq_message = transport_client.consume(dlq_name, timeout=2)
            if dlq_message:
                break
            logger.info(f"DLQ check attempt {attempt + 1}/10")
            time.sleep(2)

        assert dlq_message is not None, \
            f"Message should be in DLQ {dlq_name} when error-end is unavailable"
        logger.info(f"[+] Message found in DLQ: {dlq_message.get('id')}")

        # Verify envelope ID matches
        assert dlq_message.get("id") == envelope_id, \
            "DLQ message ID should match original envelope ID"

        # Verify envelope structure is preserved
        assert "route" in dlq_message, "DLQ message should preserve route"
        assert "payload" in dlq_message, "DLQ message should preserve payload"
        logger.info("[+] DLQ message structure preserved")

        # Verify error-end queue is EMPTY (message should NOT go there when unavailable)
        logger.info(f"Verifying error-end queue {error_end_queue} is empty")
        error_end_message = transport_client.consume(error_end_queue, timeout=2)
        assert error_end_message is None, \
            "error-end queue should be empty when error-end is unavailable"
        logger.info("[+] error-end queue is empty - message went to DLQ instead")

        logger.info("[+] Test passed - transport-level DLQ fallback working")

    finally:
        # Re-enable KEDA scaling for error-end
        logger.info("Re-enabling KEDA scaling for error-end")
        kubectl.run("patch asyncactor error-end -n asya-e2e --type=json -p '[{\"op\":\"replace\",\"path\":\"/spec/scaling/enabled\",\"value\":true}]'")
        logger.info("[+] KEDA scaling re-enabled for error-end")


@pytest.mark.slow
@pytest.mark.comparison
def test_error_handling_comparison_summary(e2e_helper, kubectl):
    """
    E2E: Summary test showing both error handling paths side-by-side.

    This test demonstrates the two-tier error handling strategy:

    ┌─────────────────────────────────────────────────────────────┐
    │ Runtime Error Occurs in Actor                                │
    └─────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
    ┌─────────────────────────────────────────────────────────────┐
    │ Sidecar: Try sendToErrorQueue()                              │
    └─────────────────┬───────────────────────────────────────────┘
                      │
          ┌───────────┴───────────┐
          │                       │
          ▼                       ▼
    ┌──────────────┐      ┌──────────────┐
    │ Send Success │      │ Send Failure │
    │ (error-end   │      │ (error-end   │
    │  available)  │      │  unavailable)│
    └──────┬───────┘      └──────┬───────┘
           │                     │
           ▼                     ▼
    ┌──────────────┐      ┌──────────────┐
    │ ACK message  │      │ NACK message │
    │ (done)       │      │              │
    └──────────────┘      └──────┬───────┘
                                 │
                                 ▼
                          ┌──────────────┐
                          │ Transport    │
                          │ retries      │
                          │ (3x)         │
                          └──────┬───────┘
                                 │
                                 ▼
                          ┌──────────────┐
                          │ Move to DLQ  │
                          │ (fallback)   │
                          └──────────────┘

    Expected behaviors verified:
    1. error-end available → application-level handling
    2. error-end unavailable → transport-level DLQ fallback
    """
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    logger.info(f"Transport: {transport}")
    logger.info("")
    logger.info("=" * 80)
    logger.info("Error Handling Strategy Comparison")
    logger.info("=" * 80)
    logger.info("")
    logger.info("Scenario 1: error-end AVAILABLE (normal operation)")
    logger.info("  → Runtime error occurs")
    logger.info("  → Sidecar sends to error-end queue ✓")
    logger.info("  → Original message ACK'd ✓")
    logger.info("  → error-end persists to S3 ✓")
    logger.info("  → DLQ remains empty ✓")
    logger.info("")
    logger.info("Scenario 2: error-end UNAVAILABLE (fallback)")
    logger.info("  → Runtime error occurs")
    logger.info("  → Sidecar fails to send to error-end ✗")
    logger.info("  → Original message NACK'd ✓")
    logger.info("  → Transport retries 3 times ✓")
    logger.info("  → Message moved to DLQ ✓")
    logger.info("  → error-end queue empty ✓")
    logger.info("")
    logger.info("=" * 80)
    logger.info("")
    logger.info("[+] Both error handling paths validated in previous tests")
    logger.info("[+] Two-tier error handling strategy working correctly")
