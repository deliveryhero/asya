"""Transport fixtures for Asya tests."""

import os
from dataclasses import dataclass

import pytest

from asya_testing.clients.base import ActorTransportClient, TransportClient
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
        envelope_completion_short: Short envelope completion timeout (simple operations)
        envelope_completion_medium: Medium envelope completion timeout (multi-actor pipelines)
        envelope_completion_long: Long envelope completion timeout (complex processing)
    """

    crash_detection: int
    envelope_completion_short: int
    envelope_completion_medium: int
    envelope_completion_long: int


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
    using the Asya naming convention (asya-{actor_name}).

    Returns:
        ActorTransportClient: Wrapped transport client that handles actor name resolution

    Raises:
        ValueError: If ASYA_TRANSPORT is not set or has invalid value
    """
    transport_type = require_env("ASYA_TRANSPORT").lower()
    base_client: TransportClient

    if transport_type == "rabbitmq":
        base_client = RabbitMQClient(
            host=require_env("RABBITMQ_HOST"),
            port=int(require_env("RABBITMQ_PORT")),
            user=require_env("RABBITMQ_USER"),
            password=require_env("RABBITMQ_PASS"),
        )
    elif transport_type == "sqs":
        base_client = SQSClient(
            endpoint_url=require_env("AWS_ENDPOINT_URL"),
            region=require_env("AWS_DEFAULT_REGION"),
            access_key=require_env("AWS_ACCESS_KEY_ID"),
            secret_key=require_env("AWS_SECRET_ACCESS_KEY"),
        )
    else:
        raise ValueError(f"Unsupported transport: {transport_type}")

    return ActorTransportClient(base_client)


@pytest.fixture(scope="session")
def transport_timeouts() -> TransportTimeouts:
    """
    Provide transport-aware timeout values for tests.

    Returns different timeout values based on the transport type:
    - SQS: Longer timeouts to account for 20s long-polling delays
    - RabbitMQ: Shorter timeouts for immediate message delivery

    Returns:
        TransportTimeouts: Timeout configuration based on ASYA_TRANSPORT env var

    Example:
        def test_something(transport_timeouts):
            envelope = wait_for_completion(
                envelope_id,
                timeout=transport_timeouts.envelope_completion_short
            )
    """
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq").lower()

    if transport == "sqs":
        return TransportTimeouts(
            crash_detection=60,
            envelope_completion_short=60,
            envelope_completion_medium=120,
            envelope_completion_long=180,
        )
    else:
        return TransportTimeouts(
            crash_detection=20,
            envelope_completion_short=30,
            envelope_completion_medium=90,
            envelope_completion_long=120,
        )
