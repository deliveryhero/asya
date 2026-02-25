"""Fixtures for stateful actors integration tests."""

import json
import logging
import time
from typing import Dict, Optional

import pika
import pytest
import requests

from asya_testing.config import require_env

logger = logging.getLogger(__name__)


class RabbitMQTestHelper:
    """Helper for publishing and consuming RabbitMQ messages."""

    def __init__(self, host: str, port: int, user: str, password: str, namespace: str = "default"):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.namespace = namespace
        self.base_url = f"http://{host}:15672/api"
        self.auth = (user, password)

    def publish_message(self, queue: str, message: dict, exchange: str = "asya") -> None:
        """Publish a message to RabbitMQ with delivery confirmation."""
        routing_key = queue.removeprefix(f"asya-{self.namespace}-")
        credentials = pika.PlainCredentials(self.user, self.password)
        params = pika.ConnectionParameters(self.host, self.port, "/", credentials)
        connection = pika.BlockingConnection(params)
        channel = connection.channel()
        channel.confirm_delivery()
        body = json.dumps(message)
        channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=body,
            properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
            mandatory=True,
        )
        connection.close()

    def get_message(self, queue: str, timeout: int = 10) -> Optional[Dict]:
        """Get a message from a queue with timeout."""
        start = time.time()
        poll_interval = 0.1  # 100ms polling interval
        while time.time() - start < timeout:
            resp = requests.post(
                f"{self.base_url}/queues/%2F/{queue}/get",
                auth=self.auth,
                json={"count": 1, "ackmode": "ack_requeue_false", "encoding": "auto"},
            )
            if resp.status_code == 200:
                messages = resp.json()
                if messages:
                    try:
                        return json.loads(messages[0].get("payload", ""))
                    except json.JSONDecodeError:
                        return {"raw": messages[0].get("payload", "")}
            time.sleep(poll_interval)  # Poll RabbitMQ management API
        return None

    def assert_message_in_queue(self, queue: str, timeout: int = 10) -> dict:
        """Wait for a message in the queue and assert it is present."""
        msg = self.get_message(queue, timeout)
        assert msg is not None, f"No message found in '{queue}' within {timeout}s"
        return msg


@pytest.fixture(scope="function")
def transport():
    """RabbitMQ test helper configured from environment variables."""
    helper = RabbitMQTestHelper(
        host=require_env("RABBITMQ_HOST"),
        port=int(require_env("RABBITMQ_PORT")),
        user=require_env("RABBITMQ_USER"),
        password=require_env("RABBITMQ_PASS"),
        namespace=require_env("ASYA_NAMESPACE"),
    )
    yield helper
