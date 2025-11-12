#!/usr/bin/env python3
"""
Integration test suite for Asya sidecar-runtime protocol.

Tests the interaction between Go sidecar and Python runtime across
various scenarios including happy path, errors, OOM, timeouts, and edge cases.
"""

import json
import logging
import os
from typing import Dict, Optional

import pika
import pytest
import requests

from asya_testing.config import require_env, get_env
from asya_testing.clients.sqs import SQSClient

log_level = get_env('ASYA_LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RabbitMQTestHelper:
    """Helper class for RabbitMQ integration testing."""

    def __init__(
        self,
        rabbitmq_host: str = "rabbitmq",
        rabbitmq_port: int = 5672,
        rabbitmq_user: str = "guest",
        rabbitmq_pass: str = "guest",
    ):
        self.rabbitmq_host = rabbitmq_host
        self.rabbitmq_port = rabbitmq_port
        self.rabbitmq_user = rabbitmq_user
        self.rabbitmq_pass = rabbitmq_pass
        self.base_url = f"http://{rabbitmq_host}:15672/api"
        self.auth = (rabbitmq_user, rabbitmq_pass)

    def publish_message(
        self, queue: str, message: dict, exchange: str = "asya"
    ) -> None:
        """Publish a message to RabbitMQ with delivery confirmation."""
        routing_key = queue.removeprefix("asya-") if queue.startswith("asya-") else queue
        logger.debug(f"Publishing to exchange='{exchange}', routing_key='{routing_key}'")
        credentials = pika.PlainCredentials(self.rabbitmq_user, self.rabbitmq_pass)
        parameters = pika.ConnectionParameters(
            self.rabbitmq_host, self.rabbitmq_port, "/", credentials
        )
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()

        # Enable publisher confirms to ensure message is delivered
        channel.confirm_delivery()

        body = json.dumps(message)
        logger.debug(f"Message body: {body[:200]}{'...' if len(body) > 200 else ''}")

        channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=body,
            properties=pika.BasicProperties(
                delivery_mode=2, content_type="application/json"
            ),
            mandatory=True,  # Ensure message is routed to a queue
        )

        logger.debug("Message published and confirmed")
        connection.close()

    def get_message(self, queue: str, timeout: int = 10) -> Optional[Dict]:
        """
        Get a message from a queue with timeout.

        Returns None if no message found within timeout.
        """
        import time
        start_time = time.time()
        poll_interval = 0.1  # 100ms polling interval
        poll_count = 0

        logger.debug(f"Polling queue '{queue}' for up to {timeout}s...")
        while time.time() - start_time < timeout:
            poll_count += 1
            response = requests.post(
                f"{self.base_url}/queues/%2F/{queue}/get",
                auth=self.auth,
                json={"count": 1, "ackmode": "ack_requeue_false", "encoding": "auto"},
            )

            if response.status_code == 200:
                messages = response.json()
                if messages and len(messages) > 0:
                    payload_str = messages[0].get("payload", "")
                    logger.debug(f"Message found after {poll_count} polls ({time.time() - start_time:.2f}s)")
                    try:
                        return json.loads(payload_str)
                    except json.JSONDecodeError:
                        logger.debug("Failed to parse JSON, returning raw payload")
                        return {"raw": payload_str}

            if poll_count % 50 == 0:  # Log every 5 seconds
                logger.debug(f"Still polling... {poll_count} polls, {time.time() - start_time:.1f}s elapsed")

            time.sleep(poll_interval)  # Poll RabbitMQ API for new messages

        logger.debug(f"Timeout after {poll_count} polls, no message found in '{queue}'")
        return None


    def get_queue_info(self, queue: str) -> Optional[Dict]:
        """Get queue information including message count."""
        response = requests.get(
            f"{self.base_url}/queues/%2F/{queue}",
            auth=self.auth
        )
        if response.status_code == 200:
            return response.json()
        return None

    def purge_queue(self, queue: str) -> bool:
        """Purge all messages from a queue."""
        response = requests.delete(
            f"{self.base_url}/queues/%2F/{queue}/contents",
            auth=self.auth
        )
        return response.status_code == 204

    def assert_message_in_queue(
        self, queue: str, expected_fields: Optional[Dict] = None, timeout: int = 10
    ) -> Optional[Dict]:
        """
        Assert that a message appears in the specified queue.

        Args:
            queue: Queue name to check
            expected_fields: Optional dict of field:value pairs to verify
            timeout: Seconds to wait for message

        Returns:
            The message if found, None otherwise
        """
        message = self.get_message(queue, timeout)

        if message is None:
            return None

        if expected_fields:
            for field, expected_value in expected_fields.items():
                actual_value = message.get(field)
                if actual_value != expected_value:
                    return None

        return message


class SQSTestHelper:
    """Helper class for SQS integration testing."""

    def __init__(
        self,
        sqs_url: str = "http://sqs:4566",
        region: str = "us-east-1",
        access_key: str = "test",
        secret_key: str = "test",
    ):
        self.sqs_client = SQSClient(
            endpoint_url=sqs_url,
            region=region,
            access_key=access_key,
            secret_key=secret_key,
        )

    def publish_message(
        self, queue: str, message: dict, exchange: str = ""
    ) -> None:
        """Publish a message to SQS queue."""
        logger.debug(f"Publishing to queue='{queue}'")
        logger.debug(f"Message body: {json.dumps(message)[:200]}...")
        self.sqs_client.publish(queue, message, exchange)
        logger.debug("Message published")

    def get_message(self, queue: str, timeout: int = 10) -> Optional[Dict]:
        """
        Get a message from a queue with timeout.

        Returns None if no message found within timeout.
        """
        logger.debug(f"Polling SQS queue '{queue}' for up to {timeout}s...")
        message = self.sqs_client.consume(queue, timeout)
        if message:
            logger.debug(f"Message found in '{queue}'")
        else:
            logger.debug(f"Timeout, no message found in '{queue}'")
        return message

    def purge_queue(self, queue: str) -> bool:
        """Purge all messages from a queue."""
        try:
            self.sqs_client.purge(queue)
            logger.debug(f"Purged queue '{queue}'")
            return True
        except Exception as e:
            logger.warning(f"Failed to purge queue '{queue}': {e}")
            return False

    def assert_message_in_queue(
        self, queue: str, expected_fields: Optional[Dict] = None, timeout: int = 10
    ) -> Optional[Dict]:
        """
        Assert that a message appears in the specified queue.

        Args:
            queue: Queue name to check
            expected_fields: Optional dict of field:value pairs to verify
            timeout: Seconds to wait for message

        Returns:
            The message if found, None otherwise
        """
        message = self.get_message(queue, timeout)

        if message is None:
            return None

        if expected_fields:
            for field, expected_value in expected_fields.items():
                actual_value = message.get(field)
                if actual_value != expected_value:
                    return None

        return message


# ============================================================================
# Test Cases
# ============================================================================


def test_happy_path(transport_helper):
    """Test successful message processing with echo_handler."""
    message = {
        "id": "test-happy-path-1",
        "route": {"actors": ["test-echo"], "current": 0},
        "payload": {"test": "happy_path", "data": "integration test"},
    }
    logger.info(f"Publishing message to asya-test-echo: {json.dumps(message, indent=2)}")

    transport_helper.publish_message("asya-test-echo", message)
    logger.info("Message published successfully, waiting for response in asya-happy-end...")

    result = transport_helper.assert_message_in_queue("asya-happy-end", timeout=10)
    logger.info(f"Result from happy-end: {json.dumps(result, indent=2) if result else 'None'}")
    assert result is not None, "No message in happy-end queue"

    payload = result.get("payload", {})
    logger.info(f"Payload extracted: {json.dumps(payload, indent=2)}")
    assert payload.get("test") == "happy_path", f"Payload not echoed correctly, got: {payload}"
    assert payload.get("data") == "integration test", f"Payload data missing, got: {payload}"
    logger.info("=== test_happy_path: PASSED ===\n")


def test_error_handling(transport_helper):
    """Test runtime error handling."""
    transport_helper.purge_queue("asya-error-end")
    message = {
        "id": "test-error-handling-1",
        "route": {"actors": ["test-error"], "current": 0},
        "payload": {"test": "error_handling"},
    }
    logger.info(f"Publishing error test message to test-error: {json.dumps(message, indent=2)}")

    transport_helper.publish_message("asya-test-error", message)
    logger.info("Message published, waiting for error in asya-error-end...")

    result = transport_helper.assert_message_in_queue("asya-error-end", timeout=10)
    logger.info(f"Result from error-end: {json.dumps(result, indent=2) if result else 'None'}")
    assert result is not None, "No message in error-end queue"

    # Error is inside payload (nested format)
    payload = result.get("payload", {})
    error_msg = payload.get("error", "")
    logger.info(f"Error message received: {error_msg}")
    assert "error" in error_msg.lower(), f"Not an error message, got: {error_msg}"

    # Original payload should be preserved inside payload
    original_payload = payload.get("original_payload", {})
    assert original_payload == {"test": "error_handling"}, f"Original payload not preserved, got: {original_payload}"
    logger.info("=== test_error_handling: PASSED ===\n")


def test_oom_error(transport_helper):
    """Test OOM error detection and recovery."""
    transport_helper.purge_queue("asya-error-end")
    message = {
        "id": "test-oom-error-1",
        "route": {"actors": ["test-oom-queue"], "current": 0},
        "payload": {"test": "oom_simulation"},
    }
    logger.info(f"Publishing OOM test message: {json.dumps(message, indent=2)}")

    transport_helper.publish_message("asya-test-oom-queue", message)
    logger.info("Waiting for OOM error in asya-error-end...")

    result = transport_helper.assert_message_in_queue("asya-error-end", timeout=10)
    logger.info(f"Result from error-end: {json.dumps(result, indent=2) if result else 'None'}")
    assert result is not None, "No message in error-end queue"

    error_data = str(result)
    logger.info(f"Error data: {error_data[:200]}...")
    assert "memory" in error_data.lower() or "oom" in error_data.lower(), (
        f"Not an OOM error, got: {error_data[:200]}"
    )
    logger.info("=== test_oom_error: PASSED ===\n")


def test_cuda_oom_error(transport_helper):
    """Test CUDA OOM error detection."""
    transport_helper.purge_queue("asya-error-end")
    message = {
        "id": "test-cuda-oom-error-1",
        "route": {"actors": ["test-cuda-oom-queue"], "current": 0},
        "payload": {"test": "cuda_oom_simulation"},
    }

    transport_helper.publish_message("asya-test-cuda-oom-queue", message)

    result = transport_helper.assert_message_in_queue("asya-error-end", timeout=10)
    assert result is not None, "No message in error-end queue"

    error_data = str(result)
    assert "cuda" in error_data.lower() or "memory" in error_data.lower(), (
        "Not a CUDA OOM error"
    )


def test_timeout(transport_helper):
    """Test sidecar timeout enforcement."""
    message = {
        "id": "test-timeout-1",
        "route": {"actors": ["test-timeout"], "current": 0},
        "payload": {"test": "timeout", "sleep": 5},
    }

    transport_helper.publish_message("asya-test-timeout", message)

    result = transport_helper.assert_message_in_queue("asya-error-end", timeout=10)
    assert result is not None, "No timeout error in error-end queue"


def test_fanout(transport_helper):
    """Test fan-out (multiple responses)."""
    message = {
        "id": "test-fanout-1",
        "route": {"actors": ["test-fanout"], "current": 0},
        "payload": {"test": "fanout", "count": 3},
    }

    transport_helper.publish_message("asya-test-fanout", message)

    # Should get 3 messages in asya-happy-end
    messages = []
    for _ in range(3):
        msg = transport_helper.get_message("asya-happy-end", timeout=5)
        if msg:
            messages.append(msg)

    assert len(messages) == 3, f"Expected 3 fan-out messages, got {len(messages)}"


def test_empty_response(transport_helper):
    """Test empty/null response (abort pipeline)."""
    message = {
        "id": "test-empty-response-1",
        "route": {
            "actors": ["test-empty", "should-not-reach"],
            "current": 0,
        },
        "payload": {"test": "empty_response"},
    }

    transport_helper.publish_message("asya-test-empty", message)

    # Empty response should go to asya-happy-end, not continue to next actor
    result = transport_helper.assert_message_in_queue("asya-happy-end", timeout=10)
    assert result is not None, "Empty response should go to happy-end"


def test_large_payload(transport_helper):
    """Test large payload handling."""
    message = {
        "id": "test-large-payload-1",
        "route": {"actors": ["test-large-queue"], "current": 0},
        "payload": {"test": "large_payload", "size_kb": 100},
    }

    transport_helper.publish_message("asya-test-large-queue", message)

    result = transport_helper.assert_message_in_queue("asya-happy-end", timeout=10)
    assert result is not None, "Large payload not processed"

    payload = result.get("payload", {})
    assert payload.get("data_size_kb") == 100, "Wrong payload size"


def test_unicode_handling(transport_helper):
    """Test Unicode/UTF-8 handling."""
    message = {
        "id": "test-unicode-handling-1",
        "route": {"actors": ["test-unicode"], "current": 0},
        "payload": {
            "test": "unicode",
            "text": "Hello 世界",
        },
    }

    transport_helper.publish_message("asya-test-unicode", message)

    result = transport_helper.assert_message_in_queue("asya-happy-end", timeout=10)
    assert result is not None, "Unicode message not processed"

    payload = result.get("payload", {})
    assert "test_chars" in payload, "Unicode test field not preserved"


def test_null_values(transport_helper):
    """Test null value handling."""
    message = {
        "id": "test-null-values-1",
        "route": {"actors": ["test-null"], "current": 0},
        "payload": {"test": "null_values", "data": None},
    }

    transport_helper.publish_message("asya-test-null", message)

    result = transport_helper.assert_message_in_queue("asya-happy-end", timeout=10)
    assert result is not None, "Null values not processed"


def test_multi_actor_routing(transport_helper):
    """Test multi-actor message routing."""

    # Purge source queues to ensure clean state
    logger.info("Purging asya-test-conditional-queue and asya-test-echo...")
    transport_helper.purge_queue("test-conditional-queue")
    transport_helper.purge_queue("test-echo")

    message = {
        "id": "test-multi-actor-routing-1",
        "route": {
            "actors": [
                "test-conditional-queue",
                "test-echo",
            ],
            "current": 0,
        },
        "payload": {"test": "multi_actor", "data": "routed", "action": "success"},
    }
    logger.info(f"Publishing multi-actor message: {json.dumps(message, indent=2)}")

    transport_helper.publish_message("asya-test-conditional-queue", message)
    logger.info("Message published to asya-test-conditional-queue")
    logger.info("Waiting for message to route through asya-test-conditional-queue -> asya-test-echo -> asya-happy-end...")

    # Should eventually reach asya-happy-end after going through both queues
    result = transport_helper.assert_message_in_queue("asya-happy-end", timeout=30)
    logger.info(f"Result from happy-end: {json.dumps(result, indent=2) if result else 'None'}")
    assert result is not None, "Multi-actor routing failed - no message in happy-end after 30s"
    logger.info("=== test_multi_actor_routing: PASSED ===\n")


def test_conditional_success(transport_helper):
    """Test conditional handler with success action."""
    message = {
        "id": "test-conditional-success-1",
        "route": {"actors": ["test-conditional-queue"], "current": 0},
        "payload": {"action": "success"},
    }

    transport_helper.publish_message("asya-test-conditional-queue", message)

    result = transport_helper.assert_message_in_queue("asya-happy-end", timeout=10)
    assert result is not None, "Conditional success failed"


def test_conditional_error(transport_helper):
    """Test conditional handler with error action."""
    # Purge source queue to ensure clean state
    transport_helper.purge_queue("test-conditional-queue")

    message = {
        "id": "test-conditional-error-1",
        "route": {"actors": ["test-conditional-queue"], "current": 0},
        "payload": {"action": "error", "error_msg": "conditional test error"},
    }

    transport_helper.publish_message("asya-test-conditional-queue", message)

    result = transport_helper.assert_message_in_queue("asya-error-end", timeout=20)
    assert result is not None, "Conditional error not caught"


def test_nested_data(transport_helper):
    """Test deeply nested data structures."""
    message = {
        "id": "test-nested-data-1",
        "route": {"actors": ["test-nested"], "current": 0},
        "payload": {"test": "nested"},
    }

    transport_helper.publish_message("asya-test-nested", message)

    result = transport_helper.assert_message_in_queue("asya-happy-end", timeout=10)
    assert result is not None, "Nested data not processed"

    payload = result.get("payload", {})
    assert payload.get("nested_depth") == 20, "Nested structure not preserved"


def test_invalid_route_current(transport_helper):
    """
    Test sidecar handling when runtime returns route.current out of range.

    When ASYA_ENABLE_VALIDATION=false, runtime may return invalid route.current.
    Sidecar should handle this gracefully by routing to happy-end
    (GetCurrentActor returns empty string for out-of-range indices).
    """
    handler_mode = get_env("ASYA_HANDLER_MODE", "payload")
    if handler_mode != "envelope":
        logger.info("Skipping test_invalid_route_current (only for envelope mode)")
        return

    transport_helper.purge_queue("asya-happy-end")
    message = {
        "id": "test-invalid-route-current-1",
        "route": {"actors": ["test-invalid-route", "should-not-reach"], "current": 0},
        "payload": {"test": "invalid_route_current"},
    }
    logger.info(f"Publishing message to test-invalid-route: {json.dumps(message, indent=2)}")

    transport_helper.publish_message("asya-test-invalid-route", message)
    logger.info("Message published, waiting for result in asya-happy-end...")

    result = transport_helper.assert_message_in_queue("asya-happy-end", timeout=10)
    logger.info(f"Result from happy-end: {json.dumps(result, indent=2) if result else 'None'}")
    assert result is not None, "Message with invalid route.current not routed to happy-end"

    payload = result.get("payload", {})
    assert payload.get("test") == "invalid_route_current", f"Payload corrupted, got: {payload}"

    route = result.get("route", {})
    actors = route.get("actors", [])
    current = route.get("current", 0)
    logger.info(f"Final route: actors={actors}, current={current}")

    assert current > len(actors), f"Expected current > len(actors), got current={current}, len={len(actors)}"
    logger.info("=== test_invalid_route_current: PASSED ===\n")
