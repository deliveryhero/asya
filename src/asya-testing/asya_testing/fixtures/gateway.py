"""
Gateway fixtures for integration and E2E tests.

FAIL-FAST: ASYA_GATEWAY_URL must be set by docker-compose.
"""

import logging
import time

import pytest
import requests

from asya_testing.config import get_config, require_env
from asya_testing.utils.gateway import GatewayTestHelper
from asya_testing.utils.rabbitmq import wait_for_rabbitmq_consumers


logger = logging.getLogger(__name__)


@pytest.fixture(scope="function")
def gateway_helper(request):
    """
    Create a gateway test helper with ready gateway and transport consumers.

    This fixture ensures:
    1. Gateway /health endpoint is responsive
    2. Transport-specific readiness (RabbitMQ consumers or other transports)
    3. Waits for actor queues to have consumers before returning
    4. Returns a GatewayTestHelper instance for test use

    Uses environment variables:
    - ASYA_GATEWAY_URL (gateway URL)
    - ASYA_TRANSPORT (transport type: rabbitmq, sqs, etc.)
    """
    config = get_config()
    gateway_url = require_env("ASYA_GATEWAY_URL")

    helper = GatewayTestHelper(gateway_url)

    max_retries = 20
    for i in range(max_retries):
        try:
            response = requests.get(f"{gateway_url}/health", timeout=2)
            response.raise_for_status()
            logger.info(f"Gateway is ready (attempt {i + 1}/{max_retries})")
            break
        except Exception as e:
            if i == max_retries - 1:
                raise RuntimeError(f"Gateway not available after {max_retries} attempts") from e
            logger.debug(f"Gateway not ready yet (attempt {i + 1}/{max_retries}), retrying...")
            time.sleep(0.5)  # Polling interval for gateway health check

    # Only wait for RabbitMQ consumers if using RabbitMQ transport
    if config.is_rabbitmq():
        logger.info("Using RabbitMQ transport - waiting for consumers")

        # Extract actors from test to determine which queues to wait for
        required_queues = _get_required_queues_for_test(request)

        if required_queues:
            logger.info(f"Waiting for queues: {required_queues}")
            wait_for_rabbitmq_consumers(required_queues=required_queues, timeout=60)
        else:
            logger.info("No specific queues detected, waiting for common actors")
            wait_for_rabbitmq_consumers(
                required_queues=["asya-test-echo", "asya-happy-end", "asya-error-end"], timeout=60
            )
    else:
        logger.info(f"Using {config.transport.value} transport - skipping RabbitMQ consumer check")

    yield helper


def _get_required_queues_for_test(request) -> list[str]:
    """
    Extract required queue names from test name and docstring.

    Returns queue names with 'asya-' prefix as created by the operator.
    """
    import re

    queues = []
    test_name = request.node.name

    # Common actor pattern mapping (actor name -> queue name with asya- prefix)
    actor_patterns = {
        "echo": "asya-test-echo",
        "doubler": "asya-test-doubler",
        "incrementer": "asya-test-incrementer",
        "error": "asya-test-error",
        "timeout": "asya-test-timeout",
        "fanout": "asya-test-fanout",
        "nested": "asya-test-nested",
        "empty": "asya-test-empty",
        "unicode": "asya-test-unicode",
        "large[_-]?payload": "asya-test-large-payload",
        "slow[_-]?boundary": "asya-test-slow-boundary",
    }

    for pattern, queue_name in actor_patterns.items():
        if re.search(pattern, test_name, re.IGNORECASE):
            queues.append(queue_name)

    # Always include end actors as they're used in all tests
    if "happy" in test_name.lower() or "s3" in test_name.lower() or "persist" in test_name.lower():
        queues.append("asya-happy-end")
    if "error" in test_name.lower():
        queues.append("asya-error-end")

    # Multihop tests
    if "multihop" in test_name.lower():
        queues.extend([f"asya-test-multihop-{i}" for i in range(15)])

    return list(set(queues))


@pytest.fixture(params=["sse", "polling"], ids=["SSE", "HTTP-Polling"])
def gateway_helper_parametrized(request):
    """
    Gateway test helper fixture parametrized for both SSE and HTTP polling.

    This ensures all tests run with both progress monitoring methods.
    Useful for integration tests that verify both SSE and polling work correctly.

    Uses environment variables:
    - ASYA_GATEWAY_URL (gateway URL)
    - ASYA_TRANSPORT (transport type: rabbitmq, sqs, etc.)
    """
    config = get_config()
    gateway_url = require_env("ASYA_GATEWAY_URL")
    progress_method = request.param

    logger.info(f"\n{'=' * 80}")
    logger.info(f"Test: {request.node.name}")
    logger.info(f"Progress method: {progress_method}")
    logger.info(f"{'=' * 80}\n")

    helper = GatewayTestHelper(gateway_url=gateway_url, progress_method=progress_method)

    max_retries = 30
    for i in range(max_retries):
        try:
            requests.get(f"{gateway_url}/health", timeout=2)
            logger.info("Gateway is ready")
            break
        except Exception as e:
            if i == max_retries - 1:
                raise RuntimeError("Gateway not available") from e
            time.sleep(1)

    # Only wait for RabbitMQ consumers if using RabbitMQ transport
    if config.is_rabbitmq():
        logger.info("Using RabbitMQ transport - waiting for consumers")

        # Extract actors from test to determine which queues to wait for
        required_queues = _get_required_queues_for_test(request)

        if required_queues:
            logger.info(f"Waiting for queues: {required_queues}")
            wait_for_rabbitmq_consumers(required_queues=required_queues, timeout=60)
        else:
            logger.info("No specific queues detected, waiting for common actors")
            wait_for_rabbitmq_consumers(
                required_queues=["asya-test-echo", "asya-happy-end", "asya-error-end"], timeout=60
            )
    else:
        logger.info(f"Using {config.transport.value} transport - skipping RabbitMQ consumer check")

    yield helper
