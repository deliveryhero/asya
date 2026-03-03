"""Pub/Sub client implementation for component and integration tests."""

import contextlib
import json
import logging
import time

from google.api_core.exceptions import AlreadyExists, GoogleAPICallError, NotFound
from google.cloud import pubsub_v1

from .base import TransportClient


logger = logging.getLogger(__name__)


class PubSubClient(TransportClient):
    """
    Pub/Sub client for test operations.

    Provides methods for publishing, consuming, and purging topics/subscriptions.
    Compatible with the gcloud Pub/Sub emulator via PUBSUB_EMULATOR_HOST.
    """

    def __init__(self, project_id: str = "test-project"):
        self.project_id = project_id
        self.publisher = pubsub_v1.PublisherClient()
        self.subscriber = pubsub_v1.SubscriberClient()

    def _topic_path(self, topic_name: str) -> str:
        return self.publisher.topic_path(self.project_id, topic_name)

    def _subscription_path(self, subscription_name: str) -> str:
        return self.subscriber.subscription_path(self.project_id, subscription_name)

    def _ensure_topic_and_subscription(self, name: str) -> None:
        """Create topic and subscription if they don't exist."""
        topic_path = self._topic_path(name)
        sub_path = self._subscription_path(name)
        with contextlib.suppress(AlreadyExists):
            self.publisher.create_topic(request={"name": topic_path})
        with contextlib.suppress(AlreadyExists):
            self.subscriber.create_subscription(
                request={"name": sub_path, "topic": topic_path, "ack_deadline_seconds": 60}
            )

    def publish(self, queue: str, message: dict) -> None:
        """Publish message to topic."""
        self._ensure_topic_and_subscription(queue)
        topic_path = self._topic_path(queue)
        body = json.dumps(message).encode("utf-8")
        future = self.publisher.publish(topic_path, body)
        future.result()
        logger.debug(f"Published to {queue}: {message.get('id', 'N/A')}")

    def consume(self, queue: str, timeout: int = 10) -> dict | None:
        """Consume message from subscription with timeout."""
        sub_path = self._subscription_path(queue)
        start = time.time()
        poll_interval = 0.5

        while time.time() - start < timeout:
            try:
                response = self.subscriber.pull(
                    request={"subscription": sub_path, "max_messages": 1},
                    timeout=min(2.0, max(0.5, timeout - (time.time() - start))),
                )
            except GoogleAPICallError:
                time.sleep(poll_interval)  # Retry on transient errors from emulator
                continue

            if response.received_messages:
                msg = response.received_messages[0]
                self.subscriber.acknowledge(request={"subscription": sub_path, "ack_ids": [msg.ack_id]})
                logger.debug(f"Consumed from {queue}")
                return json.loads(msg.message.data.decode("utf-8"))

            time.sleep(poll_interval)  # Poll interval between empty pulls

        logger.debug(f"Timeout waiting for message in {queue}")
        return None

    def purge(self, queue: str) -> None:
        """Purge all messages by pulling and acking everything."""
        sub_path = self._subscription_path(queue)
        while True:
            try:
                response = self.subscriber.pull(
                    request={"subscription": sub_path, "max_messages": 100},
                    timeout=2.0,
                )
            except GoogleAPICallError:
                break
            if not response.received_messages:
                break
            ack_ids = [msg.ack_id for msg in response.received_messages]
            self.subscriber.acknowledge(request={"subscription": sub_path, "ack_ids": ack_ids})
        logger.debug(f"Purged {queue}")

    def delete_queue(self, queue: str) -> None:
        """Delete topic and subscription."""
        with contextlib.suppress(NotFound):
            self.subscriber.delete_subscription(request={"subscription": self._subscription_path(queue)})
        with contextlib.suppress(NotFound):
            self.publisher.delete_topic(request={"topic": self._topic_path(queue)})
        logger.debug(f"Deleted topic/subscription {queue}")

    def create_queue(self, queue: str) -> None:
        """Create topic and subscription."""
        self._ensure_topic_and_subscription(queue)
        logger.debug(f"Created topic/subscription {queue}")

    def list_queues(self) -> list[str]:
        """List all subscription names (subscriptions are the consumer-side queues)."""
        project_path = f"projects/{self.project_id}"
        subscriptions = []
        for sub in self.subscriber.list_subscriptions(request={"project": project_path}):
            name = sub.name.split("/")[-1]
            subscriptions.append(name)
        logger.debug(f"Listed {len(subscriptions)} subscriptions")
        return subscriptions
