"""Pytest configuration for E2E tests."""

import logging
import os
import time

import pytest

pytest_plugins = ["asya_testing.conftest"]

from asya_testing.fixtures import (
    test_config,
    gateway_url,
    gateway_helper,
    s3_endpoint,
    results_bucket,
    errors_bucket,
    rabbitmq_client,
    rabbitmq_url,
    namespace,
    transport_timeouts,
    TransportTimeouts,
    e2e_helper,
    kubectl,
    wait_for_actors_factory,
    wait_for_queues_factory,
)

logger = logging.getLogger(__name__)


CHAOS_ACTOR_NAMES = ["test-echo", "test-error", "test-queue-health", "error-end"]


@pytest.fixture(scope="function", autouse=True)
def ensure_gateway_port_forward(request, e2e_helper):
    """
    Ensure gateway port-forward is healthy before each chaos test.

    Chaos tests often delete/restart pods which kills port-forwards.
    This fixture checks connectivity before each test and restarts if needed.

    Only runs for tests marked with @pytest.mark.chaos.
    """
    if "chaos" not in request.keywords:
        return

    max_retries = 3
    for attempt in range(max_retries):
        try:
            import requests
            requests.get(f"{e2e_helper.gateway_url}/health", timeout=2)
            logger.info(f"Gateway port-forward healthy before {request.node.name}")
            return
        except Exception as e:
            logger.warning(f"Gateway port-forward check failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                logger.info("Restarting port-forward...")
                e2e_helper.restart_port_forward()
                time.sleep(3)
            else:
                pytest.fail(f"Gateway port-forward not available after {max_retries} attempts")


@pytest.fixture(scope="session")
def chaos_actors(kubectl, namespace):
    """
    Ensure chaos test actors are deployed and ready.

    Required actors for chaos tests:
    - test-echo: For basic queue recreation tests
    - test-error: For error handling tests
    - test-queue-health: For queue health monitoring tests
    - error-end: System actor for error handling

    Raises:
        AssertionError: If any required actor is not deployed after waiting
    """
    return wait_for_actors_factory(kubectl, namespace, CHAOS_ACTOR_NAMES)


@pytest.fixture(scope="session")
def chaos_queues(chaos_actors):
    """
    Ensure chaos test queues are created and ready.

    Waits for all actor queues to be created by the operator.
    This fixture depends on chaos_actors to ensure AsyncActors exist first.

    Returns:
        list[str]: List of queue names that are ready
    """
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")

    if transport == "rabbitmq":
        from asya_testing.clients.rabbitmq import RabbitMQClient
        rabbitmq_host = os.getenv("RABBITMQ_HOST", "localhost")
        transport_client = RabbitMQClient(host=rabbitmq_host, port=15672)
    elif transport == "sqs":
        from asya_testing.clients.sqs import SQSClient
        endpoint_url = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
        transport_client = SQSClient(
            endpoint_url=endpoint_url,
            region=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
            access_key=os.getenv("AWS_ACCESS_KEY_ID", "test"),
            secret_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
        )
    else:
        pytest.fail(f"Unsupported transport: {transport}")

    return wait_for_queues_factory(transport_client, CHAOS_ACTOR_NAMES)


__all__ = [
    "test_config",
    "gateway_url",
    "gateway_helper",
    "s3_endpoint",
    "results_bucket",
    "errors_bucket",
    "rabbitmq_client",
    "rabbitmq_url",
    "namespace",
    "transport_timeouts",
    "TransportTimeouts",
    "e2e_helper",
    "kubectl",
    "chaos_actors",
    "chaos_queues",
]
