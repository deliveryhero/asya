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


@pytest.fixture(scope="function")
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
