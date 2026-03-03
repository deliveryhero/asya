"""
E2E-specific pytest fixtures for Asya framework tests.
"""

import logging

import pytest
import requests

from asya_testing.helpers.e2e import E2ETestHelper


logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def rabbitmq_url():
    """
    RabbitMQ AMQP URL for E2E tests.

    Note: This fixture does NOT fail-fast for backward compatibility with
    E2E tests that may run without RabbitMQ. For new tests, use test_config
    fixture which provides proper validation.

    Returns None if RABBITMQ_URL is not set.
    """
    import os

    return os.getenv("RABBITMQ_URL")


@pytest.fixture(scope="session")
def e2e_helper(gateway_url, namespace):
    """
    Create E2E test helper with Kubernetes operations.

    Extends GatewayTestHelper from asya_testing with kubectl operations
    for E2E tests that require Kubernetes pod management and monitoring.

    Uses SSE streaming by default for better performance (no polling overhead).

    Args:
        gateway_url: Gateway URL from gateway_url fixture
        namespace: Kubernetes namespace from namespace fixture

    Returns:
        E2ETestHelper instance with kubectl and pod management capabilities
    """
    return E2ETestHelper(
        gateway_url=gateway_url,
        namespace=namespace,
        system_namespace="asya-system",
        progress_method="sse",
    )


@pytest.fixture(scope="session", autouse=True)
def check_gateway_health(gateway_url):
    """
    Verify gateway is reachable at session start.

    Runs once per pytest-xdist worker. With NodePort, the gateway is
    accessible directly via Kind extraPortMappings — no port-forward needed.
    """
    import time

    for _attempt in range(5):
        try:
            response = requests.get(f"{gateway_url}/health", timeout=2)
            if response.status_code == 200:
                logger.info("[+] Gateway is healthy")
                return
        except requests.exceptions.RequestException:
            pass
        time.sleep(2)  # Wait for gateway pod readiness

    raise RuntimeError("Gateway not reachable — check NodePort and Kind extraPortMappings")


def wait_for_actors_factory(kubectl, namespace, actor_names, max_wait=120, check_interval=2):
    """
    Generic fixture factory to wait for AsyncActors to be deployed.

    Args:
        kubectl: Kubectl helper fixture
        namespace: Kubernetes namespace
        actor_names: List of actor names to wait for
        max_wait: Maximum wait time in seconds
        check_interval: Check interval in seconds

    Returns:
        List of actor names that are ready

    Raises:
        AssertionError: If any actor is not deployed after max_wait
    """
    import time

    logger.info(f"Waiting for {len(actor_names)} AsyncActors in namespace {namespace}")

    for actor_name in actor_names:
        elapsed = 0
        actor_ready = False

        while elapsed < max_wait:
            result = kubectl.run(f"get asyncactor {actor_name} -n {namespace}", check=False)
            if result.returncode == 0:
                actor_ready = True
                logger.info(f"[+] AsyncActor {actor_name} found")
                break

            logger.debug(f"Waiting for AsyncActor {actor_name} (elapsed: {elapsed}s / {max_wait}s)")
            time.sleep(check_interval)
            elapsed += check_interval

        assert actor_ready, (
            f"AsyncActor {actor_name} not found in namespace {namespace} after {max_wait}s. "
            f"Ensure actors are deployed via Helm."
        )

    return actor_names


def wait_for_queues_factory(transport_client, queue_names, namespace, max_wait=120, check_interval=2):
    """
    Generic fixture factory to wait for queues to be created by operator.

    Args:
        transport_client: Transport client (RabbitMQClient or SQSClient)
        queue_names: List of queue names to wait for (actor names without prefix)
        namespace: Kubernetes namespace for queue naming
        max_wait: Maximum wait time in seconds
        check_interval: Check interval in seconds

    Returns:
        List of full queue names (with 'asya-{namespace}-' prefix) that are ready

    Raises:
        AssertionError: If any queue is not created after max_wait
    """
    import time

    expected_queues = [f"asya-{namespace}-{name}" for name in queue_names]
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
        logger.debug(
            f"Waiting for queues ({ready_count}/{len(expected_queues)} ready, "
            f"missing: {missing}, elapsed: {elapsed}s / {max_wait}s)"
        )
        time.sleep(check_interval)
        elapsed += check_interval

    assert all_ready, (
        f"Not all queues ready after {max_wait}s. Missing: {[q for q in expected_queues if q not in queues]}. "
        f"Check operator logs and ensure queue creation is working."
    )

    return expected_queues
