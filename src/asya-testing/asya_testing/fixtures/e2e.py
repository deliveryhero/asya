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
    return E2ETestHelper(gateway_url=gateway_url, namespace=namespace, progress_method="sse")


@pytest.fixture(scope="session", autouse=True)
def check_port_forward_health(gateway_url):
    """
    Check port-forward health at session start.

    This fixture runs once per pytest-xdist worker to ensure port-forwards
    are running. Uses file-based locking to prevent race conditions when
    multiple workers start simultaneously.

    The Makefile calls port-forward.sh before pytest, so this is primarily
    a verification step and fallback for chaos tests that kill pods.
    """
    import fcntl
    import os
    import subprocess
    import tempfile
    import time

    lock_file = os.path.join(tempfile.gettempdir(), "asya-e2e-port-forward.lock")

    with open(lock_file, "w") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)

            try:
                response = requests.get(f"{gateway_url}/health", timeout=2)
                if response.status_code == 200:
                    logger.info("[+] Gateway port-forward is healthy")
                    return
            except requests.exceptions.RequestException:
                logger.warning("[!] Gateway port-forward not responding, restarting...")

            try:
                script_dir = subprocess.run(
                    ["git", "rev-parse", "--show-toplevel"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                ).stdout.strip()

                port_forward_script = f"{script_dir}/testing/e2e/scripts/port-forward.sh"

                subprocess.run(
                    [port_forward_script, "start"],
                    env={**os.environ, "NAMESPACE": "asya-e2e"},
                    timeout=30,
                    check=True,
                )
                logger.info("[+] Port-forward restart completed")

                for attempt in range(5):
                    time.sleep(2)  # Wait for port-forward to stabilize
                    try:
                        response = requests.get(f"{gateway_url}/health", timeout=2)
                        if response.status_code == 200:
                            logger.info(f"[+] Gateway healthy after restart (attempt {attempt + 1}/5)")
                            return
                    except requests.exceptions.RequestException:
                        pass

                raise RuntimeError("Gateway port-forward failed to become healthy after restart")

            except Exception as restart_error:
                logger.error(f"[-] Failed to restart port-forward: {restart_error}")
                raise

        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def wait_for_actors_factory(kubectl, namespace, actor_names, max_wait=120, check_interval=5):
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


def wait_for_queues_factory(transport_client, queue_names, max_wait=120, check_interval=5):
    """
    Generic fixture factory to wait for queues to be created by operator.

    Args:
        transport_client: Transport client (RabbitMQClient or SQSClient)
        queue_names: List of queue names to wait for (without 'asya-' prefix)
        max_wait: Maximum wait time in seconds
        check_interval: Check interval in seconds

    Returns:
        List of full queue names (with 'asya-' prefix) that are ready

    Raises:
        AssertionError: If any queue is not created after max_wait
    """
    import time

    expected_queues = [f"asya-{name}" if not name.startswith("asya-") else name for name in queue_names]
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
