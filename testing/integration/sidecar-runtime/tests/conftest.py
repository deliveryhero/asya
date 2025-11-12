#!/usr/bin/env python3
"""
Shared pytest fixtures for sidecar-runtime integration tests.
"""

import json
import logging
import time
from typing import Dict, Optional

import pika
import pytest
import requests

from asya_testing.config import require_env, get_env
from asya_testing.clients.sqs import SQSClient

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
            mandatory=True,
        )

        logger.debug("Message published and confirmed")
        connection.close()

    def get_message(self, queue: str, timeout: int = 10) -> Optional[Dict]:
        """Get a message from a queue with timeout."""
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

            if poll_count % 50 == 0:
                logger.debug(f"Still polling... {poll_count} polls, {time.time() - start_time:.1f}s elapsed")

            time.sleep(poll_interval)  # Poll RabbitMQ API for new messages

        logger.debug(f"Timeout after {poll_count} polls, no message found in '{queue}'")
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
        """Assert that a message appears in the specified queue."""
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
        """Get a message from a queue with timeout."""
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
        """Assert that a message appears in the specified queue."""
        message = self.get_message(queue, timeout)

        if message is None:
            return None

        if expected_fields:
            for field, expected_value in expected_fields.items():
                actual_value = message.get(field)
                if actual_value != expected_value:
                    return None

        return message


@pytest.fixture(scope="session", autouse=True)
def log_test_session_start():
    """Log when pytest session starts to track initialization time."""
    start = time.time()
    logger.info(f"[+] Pytest session starting at {time.strftime('%H:%M:%S')}")
    yield
    logger.info(f"[+] Pytest session ended (duration: {time.time()-start:.2f}s)")


@pytest.fixture(scope="function")
def transport_helper():
    """Create a transport helper (RabbitMQ or SQS) based on ASYA_TRANSPORT env var."""
    start = time.time()

    transport = get_env("ASYA_TRANSPORT", "rabbitmq")
    logger.info(f"[+] Starting transport_helper fixture setup for transport={transport}")

    if transport == "rabbitmq":
        rabbitmq_host = require_env("RABBITMQ_HOST")
        rabbitmq_port = int(require_env("RABBITMQ_PORT"))
        rabbitmq_user = require_env("RABBITMQ_USER")
        rabbitmq_pass = require_env("RABBITMQ_PASS")
        logger.info(f"[+] Environment loaded in {time.time()-start:.2f}s")

        helper = RabbitMQTestHelper(
            rabbitmq_host, rabbitmq_port, rabbitmq_user, rabbitmq_pass
        )
        logger.info(f"[+] RabbitMQ helper created in {time.time()-start:.2f}s")
    elif transport == "sqs":
        sqs_url = require_env("SQS_URL")
        region = get_env("AWS_DEFAULT_REGION", "us-east-1")
        access_key = get_env("AWS_ACCESS_KEY_ID", "test")
        secret_key = get_env("AWS_SECRET_ACCESS_KEY", "test")
        logger.info(f"[+] Environment loaded in {time.time()-start:.2f}s")

        helper = SQSTestHelper(
            sqs_url=sqs_url,
            region=region,
            access_key=access_key,
            secret_key=secret_key,
        )
        logger.info(f"[+] SQS helper created in {time.time()-start:.2f}s")
    else:
        raise ValueError(f"Unsupported transport: {transport}. Use 'rabbitmq' or 'sqs'")

    yield helper

    logger.info(f"[+] Fixture teardown (total time: {time.time()-start:.2f}s)")
