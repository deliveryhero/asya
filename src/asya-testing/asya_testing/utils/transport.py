"""Transport-agnostic utilities for integration tests."""

from asya_testing.config import require_env

from .rabbitmq import wait_for_rabbitmq_consumers
from .sqs import wait_for_sqs_queues


def wait_for_transport(
    required_queues: list[str] | None = None,
    timeout: int = 15,
) -> None:
    """
    Wait for transport (RabbitMQ or SQS) to be ready based on ASYA_TRANSPORT.

    This function determines the transport type from the ASYA_TRANSPORT environment
    variable and calls the appropriate waiting function. This ensures tests work
    with any configured transport without hardcoding transport-specific logic.

    Args:
        required_queues: List of queue names to check. If None, skips queue waiting
                        (only verifies transport connectivity). Tests that need specific
                        queues must explicitly pass them.
        timeout: Maximum time to wait in seconds (default: 30)

    Raises:
        RuntimeError: If transport is not ready within timeout
        ConfigurationError: If ASYA_TRANSPORT is not set or unsupported
        ConfigurationError: If required transport-specific env vars are not set

    Example:
        @pytest.fixture(scope="function")
        def gateway_url():
            url = require_env("ASYA_GATEWAY_URL")

            # Wait for gateway health
            max_retries = 30
            for i in range(max_retries):
                try:
                    response = requests.get(f"{url}/health", timeout=2)
                    if response.status_code == 200:
                        break
                except Exception:
                    if i == max_retries - 1:
                        raise RuntimeError("Gateway not available")
                    time.sleep(1)

            # Wait for transport (skips queue waiting if no queues specified)
            wait_for_transport(timeout=30)

            # Or explicitly wait for specific queues
            wait_for_transport(required_queues=["my-queue", "other-queue"], timeout=30)

            return url
    """
    transport = require_env("ASYA_TRANSPORT")

    if transport == "rabbitmq":
        rabbitmq_url = require_env("RABBITMQ_URL")
        wait_for_rabbitmq_consumers(rabbitmq_url, required_queues, timeout)
    elif transport == "sqs":
        endpoint_url = require_env("AWS_ENDPOINT_URL")
        wait_for_sqs_queues(endpoint_url, required_queues, timeout)
    else:
        raise ValueError(f"Unsupported transport: {transport}. Supported: rabbitmq, sqs")
