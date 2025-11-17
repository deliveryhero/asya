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
)

logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def chaos_actors(kubectl, namespace):
    """
    Ensure chaos test actors are deployed and ready.

    Required actors for chaos tests:
    - test-echo: For basic queue recreation tests
    - test-error: For error handling tests
    - error-end: System actor for error handling

    Raises:
        AssertionError: If any required actor is not deployed after waiting
    """
    required_actors = ["test-echo", "test-error", "test-queue-health", "error-end"]
    max_wait = 120
    check_interval = 5

    logger.info(f"Ensuring chaos test actors are deployed in namespace {namespace}")

    for actor_name in required_actors:
        elapsed = 0
        actor_ready = False

        while elapsed < max_wait:
            result = kubectl.run(f"get asyncactor {actor_name} -n {namespace}", check=False)
            if result.returncode == 0:
                actor_ready = True
                logger.info(f"[+] AsyncActor {actor_name} found in namespace {namespace}")
                break

            logger.info(f"Waiting for AsyncActor {actor_name} (elapsed: {elapsed}s / {max_wait}s)")
            time.sleep(check_interval)
            elapsed += check_interval

        assert actor_ready, \
            f"AsyncActor {actor_name} not found in namespace {namespace} after {max_wait}s. " \
            f"Ensure actors are deployed via Helm before running chaos tests."

    return required_actors


@pytest.fixture(scope="session")
def chaos_queues(chaos_actors, kubectl, namespace):
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

    expected_queues = [
        "asya-test-echo",
        "asya-test-error",
        "asya-test-queue-health",
        "asya-error-end",
    ]

    max_wait = 120
    check_interval = 5
    elapsed = 0
    all_ready = False

    logger.info(f"Waiting for {len(expected_queues)} queues to be created by operator")

    while elapsed < max_wait:
        queues = transport_client.list_queues()
        ready_count = sum(1 for q in expected_queues if q in queues)

        if ready_count == len(expected_queues):
            all_ready = True
            logger.info(f"[+] All {len(expected_queues)} queues are ready")
            break

        missing = [q for q in expected_queues if q not in queues]
        logger.info(f"Waiting for queues ({ready_count}/{len(expected_queues)} ready, "
                   f"missing: {missing}, elapsed: {elapsed}s / {max_wait}s)")
        time.sleep(check_interval)
        elapsed += check_interval

    assert all_ready, \
        f"Not all queues ready after {max_wait}s. Missing queues: {[q for q in expected_queues if q not in queues]}. " \
        f"Check operator logs and ensure queue creation is working."

    return expected_queues


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
