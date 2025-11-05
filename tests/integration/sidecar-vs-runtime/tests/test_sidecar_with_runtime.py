#!/usr/bin/env python3
"""
Integration test suite for Asya sidecar-runtime protocol.

Tests the interaction between Go sidecar and Python runtime across
various scenarios including happy path, errors, OOM, timeouts, and edge cases.

Run tests with:
    pytest -v tests/integration/test_e2e_messaging.py
"""

import json
import logging
import os
from typing import Dict, Optional

import pika
import pytest
import requests

# Configure logging from environment variable (default: INFO)
log_level = os.getenv('ASYA_LOG_LEVEL', 'INFO').upper()
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
        logger.debug(f"Publishing to exchange='{exchange}', routing_key='{queue}'")
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
            routing_key=queue,
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

    def purge_queue(self, queue: str) -> None:
        """Purge all messages from a queue and wait for completion."""
        info_before = self.get_queue_info(queue)
        msg_count = info_before.get("messages", 0) if info_before else 0
        logger.debug(f"Purging queue '{queue}' ({msg_count} messages)")

        requests.delete(
            f"{self.base_url}/queues/%2F/{queue}/contents", auth=self.auth
        )
        # Verify purge completed by checking queue is empty
        self._wait_for_queue_empty(queue, timeout=2)
        logger.debug(f"Queue '{queue}' purged successfully")

    def _wait_for_queue_empty(self, queue: str, timeout: int = 2) -> None:
        """Wait for queue to be empty after purge."""
        import time
        start_time = time.time()
        while time.time() - start_time < timeout:
            info = self.get_queue_info(queue)
            if info and info.get("messages", 0) == 0:
                return
            time.sleep(0.05)  # Poll RabbitMQ API to verify purge completion

    def get_queue_info(self, queue: str) -> Optional[Dict]:
        """Get queue information including message count."""
        response = requests.get(
            f"{self.base_url}/queues/%2F/{queue}",
            auth=self.auth
        )
        if response.status_code == 200:
            return response.json()
        return None

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

    def purge_all_test_queues(self) -> None:
        """Purge all test queues before/after tests."""
        all_queues = [
            "test-actor-queue",
            "test-error-queue",
            "test-oom-queue",
            "test-cuda-oom-queue",
            "test-timeout-queue",
            "test-fanout-queue",
            "test-empty-queue",
            "test-large-queue",
            "test-unicode-queue",
            "test-null-queue",
            "test-conditional-queue",
            "test-nested-queue",
            "test-echo-queue",
            "happy-end",
            "error-end",
        ]
        for queue in all_queues:
            self.purge_queue(queue)


# ============================================================================
# Pytest Fixtures
# ============================================================================


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """One-time setup: purge all queues before test session starts."""
    rabbitmq_host = os.getenv("RABBITMQ_HOST", "rabbitmq")
    rabbitmq_port = int(os.getenv("RABBITMQ_PORT", "5672"))
    rabbitmq_user = os.getenv("RABBITMQ_USER", "guest")
    rabbitmq_pass = os.getenv("RABBITMQ_PASS", "guest")

    helper = RabbitMQTestHelper(
        rabbitmq_host, rabbitmq_port, rabbitmq_user, rabbitmq_pass
    )

    logger.info("Setting up test environment: purging all queues...")
    helper.purge_all_test_queues()
    logger.info("Test environment ready!")


@pytest.fixture(scope="function")
def rabbitmq_helper():
    """Create a RabbitMQ helper for each test with automatic cleanup."""
    rabbitmq_host = os.getenv("RABBITMQ_HOST", "rabbitmq")
    rabbitmq_port = int(os.getenv("RABBITMQ_PORT", "5672"))
    rabbitmq_user = os.getenv("RABBITMQ_USER", "guest")
    rabbitmq_pass = os.getenv("RABBITMQ_PASS", "guest")

    helper = RabbitMQTestHelper(
        rabbitmq_host, rabbitmq_port, rabbitmq_user, rabbitmq_pass
    )

    # Purge terminal queues BEFORE test to avoid interference from previous tests
    helper.purge_queue("happy-end")
    helper.purge_queue("error-end")

    yield helper

    # Purge queues after test (cleanup)
    helper.purge_all_test_queues()


# ============================================================================
# Test Cases
# ============================================================================


def test_happy_path(rabbitmq_helper):
    """Test successful message processing with echo_handler."""
    message = {
        "route": {"steps": ["test-echo-queue"], "current": 0},
        "payload": {"test": "happy_path", "data": "integration test"},
    }
    logger.info(f"Publishing message to test-echo-queue: {json.dumps(message, indent=2)}")

    rabbitmq_helper.publish_message("test-echo-queue", message)
    logger.info("Message published successfully, waiting for response in happy-end...")

    result = rabbitmq_helper.assert_message_in_queue("happy-end", timeout=10)
    logger.info(f"Result from happy-end: {json.dumps(result, indent=2) if result else 'None'}")
    assert result is not None, "No message in happy-end queue"

    payload = result.get("payload", {})
    logger.info(f"Payload extracted: {json.dumps(payload, indent=2)}")
    assert payload.get("test") == "happy_path", f"Payload not echoed correctly, got: {payload}"
    assert payload.get("data") == "integration test", f"Payload data missing, got: {payload}"
    logger.info("=== test_happy_path: PASSED ===\n")


def test_error_handling(rabbitmq_helper):
    """Test runtime error handling."""
    message = {
        "route": {"steps": ["test-error-queue"], "current": 0},
        "payload": {"test": "error_handling"},
    }
    logger.info(f"Publishing error test message to test-error-queue: {json.dumps(message, indent=2)}")

    rabbitmq_helper.publish_message("test-error-queue", message)
    logger.info("Message published, waiting for error in error-end...")

    result = rabbitmq_helper.assert_message_in_queue("error-end", timeout=10)
    logger.info(f"Result from error-end: {json.dumps(result, indent=2) if result else 'None'}")
    assert result is not None, "No message in error-end queue"

    error_msg = result.get("error", "")
    logger.info(f"Error message received: {error_msg}")
    assert "error" in error_msg.lower(), f"Not an error message, got: {error_msg}"
    logger.info("=== test_error_handling: PASSED ===\n")


def test_oom_error(rabbitmq_helper):
    """Test OOM error detection and recovery."""
    message = {
        "route": {"steps": ["test-oom-queue"], "current": 0},
        "payload": {"test": "oom_simulation"},
    }
    logger.info(f"Publishing OOM test message: {json.dumps(message, indent=2)}")

    rabbitmq_helper.publish_message("test-oom-queue", message)
    logger.info("Waiting for OOM error in error-end...")

    result = rabbitmq_helper.assert_message_in_queue("error-end", timeout=10)
    logger.info(f"Result from error-end: {json.dumps(result, indent=2) if result else 'None'}")
    assert result is not None, "No message in error-end queue"

    error_data = str(result)
    logger.info(f"Error data: {error_data[:200]}...")
    assert "memory" in error_data.lower() or "oom" in error_data.lower(), (
        f"Not an OOM error, got: {error_data[:200]}"
    )
    logger.info("=== test_oom_error: PASSED ===\n")


def test_cuda_oom_error(rabbitmq_helper):
    """Test CUDA OOM error detection."""
    message = {
        "route": {"steps": ["test-cuda-oom-queue"], "current": 0},
        "payload": {"test": "cuda_oom_simulation"},
    }

    rabbitmq_helper.publish_message("test-cuda-oom-queue", message)

    result = rabbitmq_helper.assert_message_in_queue("error-end", timeout=10)
    assert result is not None, "No message in error-end queue"

    error_data = str(result)
    assert "cuda" in error_data.lower() or "memory" in error_data.lower(), (
        "Not a CUDA OOM error"
    )


def test_timeout(rabbitmq_helper):
    """Test sidecar timeout enforcement."""
    message = {
        "route": {"steps": ["test-timeout-queue"], "current": 0},
        "payload": {"test": "timeout", "sleep": 5},
    }

    rabbitmq_helper.publish_message("test-timeout-queue", message)

    result = rabbitmq_helper.assert_message_in_queue("error-end", timeout=10)
    assert result is not None, "No timeout error in error-end queue"


def test_fanout(rabbitmq_helper):
    """Test fan-out (multiple responses)."""
    message = {
        "route": {"steps": ["test-fanout-queue"], "current": 0},
        "payload": {"test": "fanout", "count": 3},
    }

    rabbitmq_helper.publish_message("test-fanout-queue", message)

    # Should get 3 messages in happy-end
    messages = []
    for _ in range(3):
        msg = rabbitmq_helper.get_message("happy-end", timeout=5)
        if msg:
            messages.append(msg)

    assert len(messages) == 3, f"Expected 3 fan-out messages, got {len(messages)}"


def test_empty_response(rabbitmq_helper):
    """Test empty/null response (abort pipeline)."""
    message = {
        "route": {
            "steps": ["test-empty-queue", "should-not-reach"],
            "current": 0,
        },
        "payload": {"test": "empty_response"},
    }

    rabbitmq_helper.publish_message("test-empty-queue", message)

    # Empty response should go to happy-end, not continue to next step
    result = rabbitmq_helper.assert_message_in_queue("happy-end", timeout=10)
    assert result is not None, "Empty response should go to happy-end"


def test_large_payload(rabbitmq_helper):
    """Test large payload handling."""
    message = {
        "route": {"steps": ["test-large-queue"], "current": 0},
        "payload": {"test": "large_payload", "size_kb": 100},
    }

    rabbitmq_helper.publish_message("test-large-queue", message)

    result = rabbitmq_helper.assert_message_in_queue("happy-end", timeout=10)
    assert result is not None, "Large payload not processed"

    payload = result.get("payload", {})
    assert payload.get("data_size_kb") == 100, "Wrong payload size"


def test_unicode_handling(rabbitmq_helper):
    """Test Unicode/UTF-8 handling."""
    message = {
        "route": {"steps": ["test-unicode-queue"], "current": 0},
        "payload": {
            "test": "unicode",
            "text": "Hello 世界 🌍",
        },
    }

    rabbitmq_helper.publish_message("test-unicode-queue", message)

    result = rabbitmq_helper.assert_message_in_queue("happy-end", timeout=10)
    assert result is not None, "Unicode message not processed"

    payload = result.get("payload", {})
    assert "emoji" in payload, "Emoji not preserved"


def test_null_values(rabbitmq_helper):
    """Test null value handling."""
    message = {
        "route": {"steps": ["test-null-queue"], "current": 0},
        "payload": {"test": "null_values", "data": None},
    }

    rabbitmq_helper.publish_message("test-null-queue", message)

    result = rabbitmq_helper.assert_message_in_queue("happy-end", timeout=10)
    assert result is not None, "Null values not processed"


def test_multi_step_routing(rabbitmq_helper):
    """Test multi-step message routing."""

    # Purge source queues to ensure clean state
    logger.info("Purging test-conditional-queue and test-echo-queue...")
    rabbitmq_helper.purge_queue("test-conditional-queue")
    rabbitmq_helper.purge_queue("test-echo-queue")

    message = {
        "route": {
            "steps": [
                "test-conditional-queue",
                "test-echo-queue",
            ],
            "current": 0,
        },
        "payload": {"test": "multi_step", "data": "routed", "action": "success"},
    }
    logger.info(f"Publishing multi-step message: {json.dumps(message, indent=2)}")

    rabbitmq_helper.publish_message("test-conditional-queue", message)
    logger.info("Message published to test-conditional-queue")
    logger.info("Waiting for message to route through test-conditional-queue -> test-echo-queue -> happy-end...")

    # Should eventually reach happy-end after going through both queues
    result = rabbitmq_helper.assert_message_in_queue("happy-end", timeout=30)
    logger.info(f"Result from happy-end: {json.dumps(result, indent=2) if result else 'None'}")
    assert result is not None, "Multi-step routing failed - no message in happy-end after 30s"
    logger.info("=== test_multi_step_routing: PASSED ===\n")


def test_conditional_success(rabbitmq_helper):
    """Test conditional handler with success action."""
    message = {
        "route": {"steps": ["test-conditional-queue"], "current": 0},
        "payload": {"action": "success"},
    }

    rabbitmq_helper.publish_message("test-conditional-queue", message)

    result = rabbitmq_helper.assert_message_in_queue("happy-end", timeout=10)
    assert result is not None, "Conditional success failed"


def test_conditional_error(rabbitmq_helper):
    """Test conditional handler with error action."""
    # Purge source queue to ensure clean state
    rabbitmq_helper.purge_queue("test-conditional-queue")

    message = {
        "route": {"steps": ["test-conditional-queue"], "current": 0},
        "payload": {"action": "error", "error_msg": "conditional test error"},
    }

    rabbitmq_helper.publish_message("test-conditional-queue", message)

    result = rabbitmq_helper.assert_message_in_queue("error-end", timeout=20)
    assert result is not None, "Conditional error not caught"


def test_nested_data(rabbitmq_helper):
    """Test deeply nested data structures."""
    message = {
        "route": {"steps": ["test-nested-queue"], "current": 0},
        "payload": {"test": "nested"},
    }

    rabbitmq_helper.publish_message("test-nested-queue", message)

    result = rabbitmq_helper.assert_message_in_queue("happy-end", timeout=10)
    assert result is not None, "Nested data not processed"

    payload = result.get("payload", {})
    assert payload.get("nested_depth") == 20, "Nested structure not preserved"
