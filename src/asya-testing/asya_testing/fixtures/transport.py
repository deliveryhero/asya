"""Transport fixtures for Asya tests."""

import os
from dataclasses import dataclass

import pytest

from asya_testing.clients.base import ActorTransportClient, TransportClient
from asya_testing.clients.pubsub import PubSubClient
from asya_testing.clients.rabbitmq import RabbitMQClient
from asya_testing.clients.sqs import SQSClient
from asya_testing.config import require_env


@dataclass
class TransportTimeouts:
    """Transport-aware timeout configurations.

    SQS uses 20-second long-polling which can introduce significant delays
    in message delivery compared to RabbitMQ's immediate delivery.

    Attributes:
        crash_detection: Timeout for detecting pod crashes after timeout
        task_completion_short: Short task completion timeout (simple operations)
        task_completion_medium: Medium task completion timeout (multi-actor pipelines)
        task_completion_long: Long task completion timeout (complex processing)
    """

    crash_detection: int
    task_completion_short: int
    task_completion_medium: int
    task_completion_long: int


@pytest.fixture
def rabbitmq_client():
    """
    RabbitMQ client fixture for component and integration tests.

    Returns configured RabbitMQClient using environment variables:
    - RABBITMQ_HOST (required)
    - RABBITMQ_PORT (required)
    - RABBITMQ_USER (required)
    - RABBITMQ_PASS (required)

    Raises:
        ConfigurationError: If any required variable is not set
    """
    host = require_env("RABBITMQ_HOST")
    port = int(require_env("RABBITMQ_PORT"))
    user = require_env("RABBITMQ_USER")
    password = require_env("RABBITMQ_PASS")
    return RabbitMQClient(host, port, user, password)


@pytest.fixture
def transport_client():
    """
    Generic transport client fixture that selects RabbitMQ or SQS based on ASYA_TRANSPORT.

    Returns an ActorTransportClient wrapper that converts actor names to queue names
    using the Asya naming convention (asya-{namespace}-{actor_name}).

    Returns:
        ActorTransportClient: Wrapped transport client that handles actor name resolution

    Raises:
        ValueError: If ASYA_TRANSPORT is not set or has invalid value
    """
    transport_type = require_env("ASYA_TRANSPORT").lower()
    namespace = require_env("ASYA_NAMESPACE")
    base_client: TransportClient

    if transport_type == "rabbitmq":
        base_client = RabbitMQClient(
            host=require_env("RABBITMQ_HOST"),
            port=int(require_env("RABBITMQ_PORT")),
            user=require_env("RABBITMQ_USER"),
            password=require_env("RABBITMQ_PASS"),
            namespace=namespace,
        )
    elif transport_type == "sqs":
        base_client = SQSClient(
            endpoint_url=require_env("AWS_ENDPOINT_URL"),
            region=require_env("AWS_DEFAULT_REGION"),
            access_key=require_env("AWS_ACCESS_KEY_ID"),
            secret_key=require_env("AWS_SECRET_ACCESS_KEY"),
        )
    elif transport_type == "pubsub":
        base_client = PubSubClient(
            project_id=require_env("PUBSUB_PROJECT_ID"),
        )
    else:
        raise ValueError(f"Unsupported transport: {transport_type}")

    return ActorTransportClient(base_client, namespace)


@pytest.fixture(scope="session")
def transport_timeouts() -> TransportTimeouts:
    """
    Provide transport-aware timeout values for tests.

    Returns different timeout values based on the transport type:
    - SQS: Longer timeouts to account for SQS polling delays
    - RabbitMQ: Shorter timeouts for immediate message delivery

    Returns:
        TransportTimeouts: Timeout configuration based on ASYA_TRANSPORT env var

    Example:
        def test_something(transport_timeouts):
            result = wait_for_completion(
                task_id,
                timeout=transport_timeouts.task_completion_short
            )
    """
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq").lower()

    if transport in ("sqs", "pubsub"):
        return TransportTimeouts(
            crash_detection=30,
            task_completion_short=30,
            task_completion_medium=60,
            task_completion_long=120,
        )
    else:
        return TransportTimeouts(
            crash_detection=20,
            task_completion_short=30,
            task_completion_medium=90,
            task_completion_long=120,
        )
