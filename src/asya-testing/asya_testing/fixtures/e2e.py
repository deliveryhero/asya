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


@pytest.fixture(scope="function", autouse=True)
def check_port_forward_health(gateway_url):
    """
    Check port-forward health before each E2E test.

    This fixture runs automatically before each test to ensure port-forwards
    are still running. If any port-forward is dead, it restarts it.

    This prevents chaos tests that kill pods from breaking subsequent tests
    due to dead port-forward connections.
    """
    import os
    import subprocess

    services_to_check = [
        ("gateway", gateway_url, 8080),
    ]

    for service_name, url, _port in services_to_check:
        try:
            response = requests.get(f"{url}/health", timeout=2)
            if response.status_code == 200:
                logger.debug(f"[.] Port-forward for {service_name} is healthy")
                continue
        except requests.exceptions.RequestException:
            pass

        logger.warning(f"[!] Port-forward for {service_name} is dead, restarting...")

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
            logger.info(f"[+] Port-forward for {service_name} restarted successfully")
        except Exception as e:
            logger.error(f"[-] Failed to restart port-forward for {service_name}: {e}")
            raise
