"""
RabbitMQ helper functions for integration and E2E tests.

Provides utilities for:
- Waiting for RabbitMQ queue consumers to be ready
- Checking queue health and status
"""

import logging
import time

import pika

from asya_testing.config import require_env


logger = logging.getLogger(__name__)


def wait_for_rabbitmq_consumers(
    rabbitmq_url: str | None = None,
    required_queues: list[str] | None = None,
    timeout: int = 30,
) -> None:
    """
    Wait for RabbitMQ queues to have active consumers.

    Connects via AMQP and checks queue consumer counts until all required queues
    have at least one consumer. This ensures actor sidecars have initialized before tests start.

    Args:
        rabbitmq_url: RabbitMQ AMQP URL (if None, loaded from RABBITMQ_URL env var)
        required_queues: List of queue names that must have consumers.
                        If None, skips queue waiting (just verifies RabbitMQ connectivity).
        timeout: Maximum time to wait in seconds

    Raises:
        ConfigurationError: If rabbitmq_url is None and RABBITMQ_URL env var is not set
    """
    rabbitmq_url = rabbitmq_url or require_env("RABBITMQ_URL")

    if required_queues is None:
        logger.info("No required_queues specified, skipping RabbitMQ queue consumer check")
        return

    start_time = time.time()
    poll_interval = 0.5

    while time.time() - start_time < timeout:
        try:
            params = pika.URLParameters(rabbitmq_url)
            connection = pika.BlockingConnection(params)
            channel = connection.channel()

            queue_status = {}
            for queue_name in required_queues:
                try:
                    method = channel.queue_declare(queue=queue_name, passive=True)
                    queue_status[queue_name] = method.method.consumer_count
                except pika.exceptions.ChannelClosedByBroker:
                    channel = connection.channel()
                    queue_status[queue_name] = 0

            connection.close()

            all_ready = all(queue_status.get(queue_name, 0) > 0 for queue_name in required_queues)

            if all_ready:
                logger.info(f"All RabbitMQ consumers ready after {time.time() - start_time:.2f}s")
                return
            else:
                missing = [q for q in required_queues if queue_status.get(q, 0) == 0]
                logger.info(f"Waiting for consumers on: {missing}")

        except Exception as e:
            logger.info(f"RabbitMQ not ready: {e}")

        time.sleep(poll_interval)

    raise RuntimeError(f"RabbitMQ consumers not ready after {timeout}s")
