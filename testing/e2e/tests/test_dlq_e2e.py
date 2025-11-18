#!/usr/bin/env python3
"""
E2E DLQ (Dead Letter Queue) Tests for Asya Framework.

Tests that poison messages (messages that repeatedly fail processing) are
automatically moved to DLQ after maxReceiveCount attempts.

DLQ Configuration (in operator values.yaml):
- RabbitMQ: dlq.enabled=true, dlq.maxRetryCount=3
- SQS: dlq.enabled=true, dlq.maxReceiveCount=3, dlq.retentionDays=14

Test Scenarios:
- test_poison_message_moves_to_dlq_e2e: Error-end queue missing → DLQ
- test_dlq_preserves_envelope_metadata_e2e: DLQ messages retain envelope ID and route info

Transport Support:
- ✅ RabbitMQ: Full support with Management API
- ✅ SQS: Full support with boto3 (LocalStack in CI)

DLQ Trigger Mechanism:
When runtime fails:
1. Sidecar tries to route error to asya-error-end queue
2. If error-end queue exists → application-level error handling (NOT DLQ)
3. If error-end queue missing → routing fails → sidecar NACK's message
4. After maxReceiveCount (3) NACKs → transport moves message to DLQ

Queue Health Monitoring:
The operator monitors queue health every 5 minutes and automatically recreates
missing queues. When we delete error-end queue for testing, the operator will
eventually recreate it. These tests work by creating a temporary window where
the queue is missing long enough to trigger DLQ behavior.

Note: These tests verify transport-level DLQ behavior (queue missing → DLQ),
while test_error_handling_e2e.py verifies application-level error handling
(error-end processes errors when queue exists).
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
@pytest.mark.dlq
def test_poison_message_moves_to_dlq_e2e(e2e_helper, kubectl, chaos_queues):
    """
    E2E: Test poison message (fails repeatedly) moves to DLQ.

    Scenario:
    1. Delete asya-error-end queue (force transport-level DLQ fallback)
    2. Send failing message to test-error actor
    3. Actor fails → sidecar tries to route to asya-error-end
    4. Routing fails (queue missing) → sidecar NACK's message
    5. Message redelivered, fails again (retry 1)
    6. Repeat for maxReceiveCount (3) times
    7. After 3rd NACK, transport moves message to asya-dlq
    8. Verify message in DLQ with correct envelope data
    9. Recreate error-end queue for cleanup

    Expected:
    - Message appears in DLQ after 3 failed attempts
    - No infinite retry loop
    - Envelope metadata preserved in DLQ

    Transport Support: Both RabbitMQ and SQS

    Note: This test takes ~30-60s depending on transport retry timing.
    """
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    transport_client = _get_transport_client(transport)

    dlq_name = "asya-dlq"
    error_end_queue = "asya-error-end"

    logger.info(f"Transport: {transport}, DLQ: {dlq_name}")
    logger.info("Purging DLQ before test")
    transport_client.purge(dlq_name)

    try:
        logger.info(f"[.] Deleting error-end queue to trigger DLQ fallback: {error_end_queue}")
        transport_client.delete_queue(error_end_queue)
        logger.info(f"[+] error-end queue deleted: {error_end_queue}")

        logger.info("Sending failing envelope to test-error actor")
        response = e2e_helper.call_mcp_tool(
            tool_name="test_error",
            arguments={"should_fail": True},
        )

        envelope_id = response["result"]["envelope_id"]
        logger.info(f"Envelope ID: {envelope_id}")

        # wait a bit
        time.sleep(30)

        logger.info(f"Checking if message moved to DLQ: {dlq_name}")
        dlq_message = None
        for attempt in range(15):
            dlq_message = transport_client.consume(dlq_name, timeout=2)
            if dlq_message:
                break
            logger.info(f"DLQ check attempt {attempt + 1}/15")
            time.sleep(2)

        assert dlq_message is not None, \
            f"Message should be in DLQ {dlq_name} after maxReceiveCount exceeded"

        logger.info(f"[+] Message found in DLQ: {dlq_message.get('id')}")

        assert dlq_message.get("id") == envelope_id, \
            "DLQ message ID should match original envelope ID"

        assert "payload" in dlq_message, \
            "DLQ message should contain payload"

        logger.info("[+] DLQ test passed - poison message moved to DLQ after retries")

    finally:
        logger.info(f"[.] Recreating error-end queue for cleanup: {error_end_queue}")
        transport_client.create_queue(error_end_queue)
        logger.info(f"[+] error-end queue recreated: {error_end_queue}")


@pytest.mark.slow
@pytest.mark.dlq
def test_dlq_preserves_envelope_metadata_e2e(e2e_helper, kubectl, chaos_queues):
    """
    E2E: Test DLQ preserves envelope metadata.

    Scenario:
    1. Delete asya-error-end queue (force DLQ fallback)
    2. Send envelope with specific payload to test-error actor
    3. Actor fails repeatedly (3 times)
    4. After retries, message goes to DLQ
    5. Verify DLQ message contains:
       - Envelope ID
       - Original route information
       - Original payload structure
    6. Recreate error-end queue for cleanup

    Expected:
    - All envelope metadata preserved in DLQ
    - Payload structure intact in DLQ

    Transport Support: Both RabbitMQ and SQS
    """
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    transport_client = _get_transport_client(transport)

    actor_queue = "asya-test-error"
    dlq_name = "asya-dlq"
    error_end_queue = "asya-error-end"

    logger.info(f"Transport: {transport}, DLQ: {dlq_name}")
    logger.info("Purging DLQ before test")
    transport_client.purge(dlq_name)

    try:
        logger.info(f"[.] Deleting error-end queue to trigger DLQ fallback: {error_end_queue}")
        transport_client.delete_queue(error_end_queue)
        logger.info(f"[+] error-end queue deleted: {error_end_queue}")

        test_payload = {
            "should_fail": True,
            "metadata": {
                "test_name": "metadata-preservation",
                "timestamp": "2025-01-01T00:00:00Z",
                "nested": {"key": "value", "count": 42}
            }
        }

        logger.info("Sending envelope with specific payload")
        response = e2e_helper.call_mcp_tool(
            tool_name="test_error",
            arguments=test_payload,
        )

        envelope_id = response["result"]["envelope_id"]
        logger.info(f"Envelope ID: {envelope_id}")

        logger.info("Waiting for message to move to DLQ after retries")
        if transport == "sqs":
            time.sleep(60)
        else:
            time.sleep(30)

        logger.info("Checking DLQ for message with metadata")
        dlq_message = None
        for attempt in range(15):
            dlq_message = transport_client.consume(dlq_name, timeout=2)
            if dlq_message:
                break
            logger.info(f"DLQ check attempt {attempt + 1}/15")
            time.sleep(2)

        assert dlq_message is not None, "Message should be in DLQ"
        logger.info(f"DLQ message: {dlq_message}")

        assert dlq_message.get("id") == envelope_id, \
            "DLQ message ID should match original envelope ID"
        assert "route" in dlq_message, \
            "DLQ message should preserve route information"
        assert "payload" in dlq_message, \
            "DLQ message should preserve payload"

        payload = dlq_message.get("payload", {})
        assert payload.get("should_fail") is True, \
            "DLQ payload should preserve should_fail parameter"
        assert "metadata" in payload, \
            "DLQ payload should preserve metadata field"

        logger.info("[+] DLQ preserves envelope metadata correctly")

    finally:
        logger.info(f"[.] Recreating error-end queue for cleanup: {error_end_queue}")
        transport_client.create_queue(error_end_queue)
        logger.info(f"[+] error-end queue recreated: {error_end_queue}")
