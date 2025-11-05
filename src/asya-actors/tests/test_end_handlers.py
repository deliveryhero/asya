#!/usr/bin/env python3
"""
Unit tests for terminal handlers (happy_end and error_end).

Simple smoke tests to verify the handlers don't crash with various inputs.
Mocking external services (requests, boto3) is done at a high level.
"""

import logging
import os
import sys
from unittest.mock import Mock, patch

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def setup_test_env():
    """Set up test environment before each test."""
    # Ensure clean environment
    for key in ["ASYA_GATEWAY_URL", "ASYA_S3_BUCKET", "ASYA_S3_ENDPOINT"]:
        if key in os.environ:
            del os.environ[key]

    # Set minimal config for tests
    os.environ["ASYA_GATEWAY_URL"] = "http://test-gateway:8080"

    yield

    # Cleanup
    for key in ["ASYA_GATEWAY_URL", "ASYA_S3_BUCKET", "ASYA_S3_ENDPOINT"]:
        if key in os.environ:
            del os.environ[key]


# ============================================================================
# Happy End Handler Tests
# ============================================================================


def test_happy_end_with_valid_message():
    """Test happy_end handler with valid message doesn't crash."""
    logger.info("=== test_happy_end_with_valid_message ===")

    with patch("requests.post") as mock_post:
        mock_post.return_value = Mock(status_code=200)

        from handlers.end_handlers import happy_end_handler

        message = {"job_id": "test-job-123", "payload": {"value": 42}}

        result = happy_end_handler(message)

        assert result == {}

    logger.info("=== test_happy_end_with_valid_message: PASSED ===")


def test_happy_end_with_empty_payload():
    """Test happy_end handler with empty payload."""
    logger.info("=== test_happy_end_with_empty_payload ===")

    with patch("requests.post") as mock_post:
        mock_post.return_value = Mock(status_code=200)

        from handlers.end_handlers import happy_end_handler

        message = {"job_id": "test-job-456", "payload": {}}

        result = happy_end_handler(message)
        assert result == {}

    logger.info("=== test_happy_end_with_empty_payload: PASSED ===")


def test_happy_end_with_route_metadata():
    """Test happy_end handler with route metadata."""
    logger.info("=== test_happy_end_with_route_metadata ===")

    with patch("requests.post") as mock_post:
        mock_post.return_value = Mock(status_code=200)

        from handlers.end_handlers import happy_end_handler

        message = {
            "job_id": "test-job-route",
            "route": {"steps": ["queue1", "queue2", "happy-end"], "current": 2},
            "payload": {"value": 100},
        }

        result = happy_end_handler(message)
        assert result == {}

    logger.info("=== test_happy_end_with_route_metadata: PASSED ===")


def test_happy_end_missing_job_id():
    """Test happy_end handler with missing job_id raises error."""
    logger.info("=== test_happy_end_missing_job_id ===")

    from handlers.end_handlers import happy_end_handler

    message = {"payload": {"result": "test"}}

    with pytest.raises(ValueError, match="job_id"):
        happy_end_handler(message)

    logger.info("=== test_happy_end_missing_job_id: PASSED ===")


def test_happy_end_with_gateway_error():
    """Test happy_end handler handles gateway errors gracefully."""
    logger.info("=== test_happy_end_with_gateway_error ===")

    with patch("requests.post") as mock_post:
        mock_post.return_value = Mock(status_code=500, text="Server Error")

        from handlers.end_handlers import happy_end_handler

        message = {"job_id": "test-job-error", "payload": {"value": 42}}

        result = happy_end_handler(message)
        assert result == {}

    logger.info("=== test_happy_end_with_gateway_error: PASSED ===")


def test_happy_end_with_connection_error():
    """Test happy_end handler handles connection errors gracefully."""
    logger.info("=== test_happy_end_with_connection_error ===")

    with patch("requests.post") as mock_post:
        import requests

        mock_post.side_effect = requests.exceptions.ConnectionError(
            "Connection refused"
        )

        from handlers.end_handlers import happy_end_handler

        message = {"job_id": "test-job-conn-error", "payload": {"value": 42}}

        result = happy_end_handler(message)
        assert result == {}

    logger.info("=== test_happy_end_with_connection_error: PASSED ===")


def test_happy_end_without_gateway_url():
    """Test happy_end handler works without ASYA_GATEWAY_URL set."""
    logger.info("=== test_happy_end_without_gateway_url ===")

    if "ASYA_GATEWAY_URL" in os.environ:
        del os.environ["ASYA_GATEWAY_URL"]

    import importlib
    import sys

    if "handlers.end_handlers" in sys.modules:
        importlib.reload(sys.modules["handlers.end_handlers"])

    from handlers.end_handlers import happy_end_handler

    message = {"job_id": "test-job-no-gw", "payload": {"value": 42}}

    result = happy_end_handler(message)
    assert result == {}

    logger.info("=== test_happy_end_without_gateway_url: PASSED ===")


# ============================================================================
# Error End Handler Tests
# ============================================================================


def test_error_end_returns_empty_dict():
    """Test error_end handler returns empty dict (terminal processing)."""
    logger.info("=== test_error_end_returns_empty_dict ===")

    with patch("requests.post") as mock_post:
        mock_post.return_value = Mock(status_code=200)

        from handlers.end_handlers import error_end_handler

        message = {
            "job_id": "test-job-001",
            "error": "Processing failed",
            "route": {},
            "payload": {},
        }

        result = error_end_handler(message)

        assert result == {}

    logger.info("=== test_error_end_returns_empty_dict: PASSED ===")


def test_error_end_missing_job_id():
    """Test error_end handler handles missing job_id by raising ValueError."""
    logger.info("=== test_error_end_missing_job_id ===")

    from handlers.end_handlers import error_end_handler

    message = {"error": "Test error"}

    with pytest.raises(ValueError, match="job_id"):
        error_end_handler(message)

    logger.info("=== test_error_end_missing_job_id: PASSED ===")


def test_error_end_with_gateway_error():
    """Test error_end handler handles gateway errors gracefully."""
    logger.info("=== test_error_end_with_gateway_error ===")

    with patch("requests.post") as mock_post:
        mock_post.return_value = Mock(status_code=500, text="Server Error")

        from handlers.end_handlers import error_end_handler

        message = {
            "job_id": "test-job-gw-error",
            "error": "Test error",
            "route": {},
            "payload": {},
        }

        result = error_end_handler(message)
        assert result == {}

    logger.info("=== test_error_end_with_gateway_error: PASSED ===")


def test_error_end_without_gateway_url():
    """Test error_end handler works without ASYA_GATEWAY_URL."""
    logger.info("=== test_error_end_without_gateway_url ===")

    if "ASYA_GATEWAY_URL" in os.environ:
        del os.environ["ASYA_GATEWAY_URL"]

    import importlib
    import sys

    if "handlers.end_handlers" in sys.modules:
        importlib.reload(sys.modules["handlers.end_handlers"])

    from handlers.end_handlers import error_end_handler

    message = {
        "job_id": "test-job-no-gw",
        "error": "Test error",
        "route": {},
        "payload": {},
    }

    result = error_end_handler(message)
    assert result == {}

    logger.info("=== test_error_end_without_gateway_url: PASSED ===")
