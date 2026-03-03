"""Shared pytest fixtures for fan-out/fan-in integration tests."""

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

SINK_QUEUE = "asya-default-x-sink"
SUMP_QUEUE = "asya-default-x-sump"
FANOUT_ROUTER_QUEUE = "asya-default-test-fanout-router"
SUB_AGENT_QUEUE = "asya-default-test-sub-agent"
AGGREGATOR_QUEUE = "asya-default-test-aggregator"


class RabbitMQTestHelper:
    """Helper class for RabbitMQ integration testing."""

    def __init__(
        self,
        rabbitmq_host: str,
        rabbitmq_port: int,
        rabbitmq_user: str,
        rabbitmq_pass: str,
        namespace: str = "default",
    ):
        self.rabbitmq_host = rabbitmq_host
        self.rabbitmq_port = rabbitmq_port
        self.rabbitmq_user = rabbitmq_user
        self.rabbitmq_pass = rabbitmq_pass
        self.namespace = namespace
        self.base_url = f"http://{rabbitmq_host}:15672/api"
        self.auth = (rabbitmq_user, rabbitmq_pass)

    def publish_envelope(self, queue: str, envelope: dict, exchange: str = "asya") -> None:
        """Publish envelope to RabbitMQ with delivery confirmation."""
        routing_key = queue.removeprefix(f"asya-{self.namespace}-")
        credentials = pika.PlainCredentials(self.rabbitmq_user, self.rabbitmq_pass)
        parameters = pika.ConnectionParameters(
            self.rabbitmq_host, self.rabbitmq_port, "/", credentials
        )
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        channel.confirm_delivery()
        body = json.dumps(envelope)
        channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=body,
            properties=pika.BasicProperties(
                delivery_mode=2, content_type="application/json"
            ),
            mandatory=True,
        )
        connection.close()

    def get_envelope(self, queue: str, timeout: int = 10) -> Optional[Dict]:
        """Get envelope from a queue with timeout."""
        start_time = time.time()
        poll_interval = 0.1  # 100ms polling interval
        while time.time() - start_time < timeout:
            response = requests.post(
                f"{self.base_url}/queues/%2F/{queue}/get",
                auth=self.auth,
                json={"count": 1, "ackmode": "ack_requeue_false", "encoding": "auto"},
            )
            if response.status_code == 200:
                messages = response.json()
                if messages and len(messages) > 0:
                    payload_str = messages[0].get("payload", "")
                    try:
                        return json.loads(payload_str)
                    except json.JSONDecodeError:
                        return {"raw": payload_str}
            time.sleep(poll_interval)  # Poll RabbitMQ management API for new messages
        return None

    def purge_queue(self, queue: str) -> bool:
        """Purge all messages from a queue."""
        response = requests.delete(
            f"{self.base_url}/queues/%2F/{queue}/contents",
            auth=self.auth,
        )
        return response.status_code == 204

    def assert_message_in_queue(self, queue: str, timeout: int = 30) -> dict:
        """Wait for envelope in the queue and assert it is present."""
        msg = self.get_envelope(queue, timeout)
        assert msg is not None, f"No message found in '{queue}' within {timeout}s"
        return msg

    def wait_for_merged_result(self, queue: str, aggregation_key: str = "results", timeout: int = 60) -> dict:
        """Wait for envelope whose payload contains aggregation_key.

        Intermediate fan-in slices (None-returning aggregator calls) also go to x-sink,
        so we must skip them and wait for the final merged payload that contains the
        aggregation_key field.
        """
        start_time = time.time()
        poll_interval = 0.1  # 100ms polling interval
        while time.time() - start_time < timeout:
            response = requests.post(
                f"{self.base_url}/queues/%2F/{queue}/get",
                auth=self.auth,
                json={"count": 1, "ackmode": "ack_requeue_false", "encoding": "auto"},
            )
            if response.status_code == 200:
                messages = response.json()
                if messages and len(messages) > 0:
                    payload_str = messages[0].get("payload", "")
                    try:
                        msg = json.loads(payload_str)
                    except json.JSONDecodeError:
                        msg = {"raw": payload_str}

                    # Check if this is the merged result (has aggregation_key in payload)
                    payload = msg.get("payload", {})
                    if aggregation_key in payload:
                        return msg

                    logger.debug(f"[.] Skipping intermediate slice at '{queue}': {list(payload.keys())}")
            time.sleep(poll_interval)  # Poll RabbitMQ management API for new messages

        return None


class SQSTestHelper:
    """Helper class for SQS integration testing."""

    def __init__(
        self,
        sqs_url: str,
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

    def publish_envelope(self, queue: str, envelope: dict, exchange: str = "") -> None:
        """Publish envelope to SQS queue."""
        self.sqs_client.publish(queue, envelope, exchange)

    def get_envelope(self, queue: str, timeout: int = 10) -> Optional[Dict]:
        """Get envelope from a queue with timeout."""
        return self.sqs_client.consume(queue, timeout)

    def purge_queue(self, queue: str) -> bool:
        """Purge all messages from a queue."""
        try:
            self.sqs_client.purge(queue)
            return True
        except Exception as e:
            logger.warning(f"Failed to purge queue '{queue}': {e}")
            return False

    def assert_message_in_queue(self, queue: str, timeout: int = 30) -> dict:
        """Wait for envelope in the queue and assert it is present."""
        msg = self.get_envelope(queue, timeout)
        assert msg is not None, f"No message found in '{queue}' within {timeout}s"
        return msg

    def wait_for_merged_result(self, queue: str, aggregation_key: str = "results", timeout: int = 60) -> dict:
        """Wait for envelope whose payload contains aggregation_key.

        Intermediate fan-in slices (None-returning aggregator calls) also go to x-sink,
        so we must skip them and wait for the final merged payload that contains the
        aggregation_key field.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            msg = self.sqs_client.consume(queue, timeout=2)
            if msg is None:
                continue
            payload = msg.get("payload", {})
            if aggregation_key in payload:
                return msg
            logger.debug(f"[.] Skipping intermediate slice at '{queue}': {list(payload.keys())}")
        return None


@pytest.fixture(scope="session", autouse=True)
def log_test_session_start():
    """Log when pytest session starts to track initialization time."""
    start = time.time()
    logger.info(f"[+] Pytest session starting at {time.strftime('%H:%M:%S')}")
    yield
    logger.info(f"[+] Pytest session ended (duration: {time.time()-start:.2f}s)")


@pytest.fixture(scope="function")
def transport():
    """Create a transport helper (RabbitMQ or SQS) based on ASYA_TRANSPORT env var."""
    transport_name = get_env("ASYA_TRANSPORT", "rabbitmq")
    logger.info(f"[+] Setting up transport helper for transport={transport_name}")

    if transport_name == "rabbitmq":
        helper = RabbitMQTestHelper(
            rabbitmq_host=require_env("RABBITMQ_HOST"),
            rabbitmq_port=int(require_env("RABBITMQ_PORT")),
            rabbitmq_user=require_env("RABBITMQ_USER"),
            rabbitmq_pass=require_env("RABBITMQ_PASS"),
            namespace=require_env("ASYA_NAMESPACE"),
        )
    elif transport_name == "sqs":
        helper = SQSTestHelper(
            sqs_url=require_env("SQS_URL"),
            region=get_env("AWS_DEFAULT_REGION", "us-east-1"),
            access_key=get_env("AWS_ACCESS_KEY_ID", "test"),
            secret_key=get_env("AWS_SECRET_ACCESS_KEY", "test"),
        )
    else:
        raise ValueError(f"Unsupported transport: {transport_name}. Use 'rabbitmq' or 'sqs'")

    yield helper
