"""RabbitMQ client implementation for component and integration tests."""

import json
import logging
import time

import pika
import requests

from .base import TransportClient


logger = logging.getLogger(__name__)


class RabbitMQClient(TransportClient):
    """
    RabbitMQ client for test operations.

    Provides methods for publishing, consuming, and purging queues.
    Uses RabbitMQ Management API for consume operations to avoid blocking.
    """

    def __init__(
        self,
        host: str = "rabbitmq",
        port: int = 5672,
        user: str = "guest",
        password: str = "guest",
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.api_url = f"http://{host}:15672/api"
        self.auth = (user, password)

    def publish(self, queue: str, message: dict, exchange: str = "asya") -> None:
        """Publish message to queue."""
        credentials = pika.PlainCredentials(self.user, self.password)
        parameters = pika.ConnectionParameters(self.host, self.port, "/", credentials)
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        channel.confirm_delivery()

        # Derive routing key from queue name by stripping asya- prefix
        routing_key = queue
        if queue.startswith("asya-"):
            routing_key = queue[5:]

        body = json.dumps(message)
        channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=body,
            properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
            mandatory=True,
        )
        connection.close()
        logger.debug(f"Published to {queue}: {message.get('id', 'N/A')}")

    def consume(self, queue: str, timeout: int = 10) -> dict | None:
        """Consume message from queue with timeout."""
        start = time.time()
        poll_interval = 0.1

        while time.time() - start < timeout:
            response = requests.post(
                f"{self.api_url}/queues/%2F/{queue}/get",
                auth=self.auth,
                json={"count": 1, "ackmode": "ack_requeue_false", "encoding": "auto"},
            )

            if response.status_code == 200:
                messages = response.json()
                if messages and len(messages) > 0:
                    payload_str = messages[0].get("payload", "")
                    logger.debug(f"Consumed from {queue}")
                    return json.loads(payload_str)

            time.sleep(poll_interval)

        logger.debug(f"Timeout waiting for message in {queue}")
        return None

    def purge(self, queue: str) -> None:
        """Purge all messages from queue."""
        requests.delete(f"{self.api_url}/queues/%2F/{queue}/contents", auth=self.auth)
        logger.debug(f"Purged {queue}")

    def delete_queue(self, queue: str) -> None:
        """Delete a queue."""
        response = requests.delete(f"{self.api_url}/queues/%2F/{queue}", auth=self.auth)
        if response.status_code == 204:
            logger.debug(f"Deleted queue {queue}")
        elif response.status_code == 404:
            logger.debug(f"Queue {queue} does not exist, skipping deletion")
        else:
            response.raise_for_status()

    def create_queue(self, queue: str) -> None:
        """Create a queue."""
        response = requests.put(
            f"{self.api_url}/queues/%2F/{queue}",
            auth=self.auth,
            json={"durable": True},
        )
        if response.status_code in (201, 204):
            logger.debug(f"Created queue {queue}")
        else:
            response.raise_for_status()

    def list_queues(self) -> list[str]:
        """List all queue names."""
        response = requests.get(f"{self.api_url}/queues/%2F", auth=self.auth)
        response.raise_for_status()
        queues = response.json()
        queue_names = [q["name"] for q in queues]
        logger.debug(f"Listed {len(queue_names)} queues")
        return queue_names
