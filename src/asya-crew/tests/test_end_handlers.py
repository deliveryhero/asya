#!/usr/bin/env python3
"""
Unit tests for end handlers (happy_end and error_end).

Simple smoke tests to verify the handlers don't crash with various inputs.
Mocking external services (requests, boto3) is done at a high level.
"""

import logging
import os
import sys

import pytest


# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def setup_test_env():
    """Set up test environment before each test."""
    # Ensure clean environment
    for key in ["ASYA_S3_BUCKET", "ASYA_S3_ENDPOINT"]:
        if key in os.environ:
            del os.environ[key]

    # Ensure ASYA_HANDLER_MODE is set to envelope for tests
    os.environ["ASYA_HANDLER_MODE"] = "envelope"
    # Disable validation for end handlers (they work directly with envelopes)
    os.environ["ASYA_ENABLE_VALIDATION"] = "false"

    yield

    # Cleanup
    for key in ["ASYA_S3_BUCKET", "ASYA_S3_ENDPOINT"]:
        if key in os.environ:
            del os.environ[key]


# ============================================================================
# Envelope Mode Validation Tests
# ============================================================================


def test_import_raises_with_payload_mode():
    """Test that importing end_handlers module raises RuntimeError when ASYA_HANDLER_MODE=payload."""
    logger.info("=== test_import_raises_with_payload_mode ===")

    # Set ASYA_HANDLER_MODE to payload
    os.environ["ASYA_HANDLER_MODE"] = "payload"

    # Remove the module from sys.modules if it's already loaded
    if "handlers.end_handlers" in sys.modules:
        del sys.modules["handlers.end_handlers"]

    # Attempt to import should raise RuntimeError
    with pytest.raises(RuntimeError, match="End handlers must run in envelope mode"):
        import handlers.end_handlers  # noqa: F401

    # Clean up
    os.environ["ASYA_HANDLER_MODE"] = "envelope"
    if "handlers.end_handlers" in sys.modules:
        del sys.modules["handlers.end_handlers"]

    logger.info("=== test_import_raises_with_payload_mode: PASSED ===")


def test_import_succeeds_with_envelope_mode():
    """Test that importing end_handlers module succeeds when ASYA_HANDLER_MODE=envelope."""
    logger.info("=== test_import_succeeds_with_envelope_mode ===")

    # Set ASYA_HANDLER_MODE to envelope
    os.environ["ASYA_HANDLER_MODE"] = "envelope"

    # Remove the module from sys.modules if it's already loaded
    if "handlers.end_handlers" in sys.modules:
        del sys.modules["handlers.end_handlers"]

    # Import should succeed
    import handlers.end_handlers  # noqa: F401

    logger.info("=== test_import_succeeds_with_envelope_mode: PASSED ===")


def test_import_raises_with_validation_enabled():
    """Test that importing end_handlers module raises RuntimeError when ASYA_ENABLE_VALIDATION=true."""
    logger.info("=== test_import_raises_with_validation_enabled ===")

    # Set ASYA_HANDLER_MODE to envelope (required for end handlers)
    os.environ["ASYA_HANDLER_MODE"] = "envelope"
    # Set ASYA_ENABLE_VALIDATION to true (should cause import to fail)
    os.environ["ASYA_ENABLE_VALIDATION"] = "true"

    # Remove the module from sys.modules if it's already loaded
    if "handlers.end_handlers" in sys.modules:
        del sys.modules["handlers.end_handlers"]

    # Attempt to import should raise RuntimeError
    with pytest.raises(RuntimeError, match="End handlers must run with validation disabled"):
        import handlers.end_handlers  # noqa: F401

    # Clean up
    os.environ["ASYA_ENABLE_VALIDATION"] = "false"
    if "handlers.end_handlers" in sys.modules:
        del sys.modules["handlers.end_handlers"]

    logger.info("=== test_import_raises_with_validation_enabled: PASSED ===")


def test_import_succeeds_with_validation_disabled():
    """Test that importing end_handlers module succeeds when ASYA_ENABLE_VALIDATION=false."""
    logger.info("=== test_import_succeeds_with_validation_disabled ===")

    # Set ASYA_HANDLER_MODE to envelope (required for end handlers)
    os.environ["ASYA_HANDLER_MODE"] = "envelope"
    # Set ASYA_ENABLE_VALIDATION to false (should allow import)
    os.environ["ASYA_ENABLE_VALIDATION"] = "false"

    # Remove the module from sys.modules if it's already loaded
    if "handlers.end_handlers" in sys.modules:
        del sys.modules["handlers.end_handlers"]

    # Import should succeed
    import handlers.end_handlers  # noqa: F401

    logger.info("=== test_import_succeeds_with_validation_disabled: PASSED ===")


# ============================================================================
# Happy End Handler Tests
# ============================================================================


def test_happy_end_with_valid_envelope():
    """Test happy_end handler with valid envelope returns empty dict."""
    logger.info("=== test_happy_end_with_valid_envelope ===")

    from handlers.end_handlers import happy_end_handler

    envelope = {"id": "test-envelope-123", "payload": {"value": 42}}

    result = happy_end_handler(envelope)

    assert result == {}

    logger.info("=== test_happy_end_with_valid_envelope: PASSED ===")


def test_happy_end_with_empty_payload():
    """Test happy_end handler with empty payload."""
    logger.info("=== test_happy_end_with_empty_payload ===")

    from handlers.end_handlers import happy_end_handler

    envelope = {"id": "test-envelope-456", "payload": {}}

    result = happy_end_handler(envelope)
    assert result == {}

    logger.info("=== test_happy_end_with_empty_payload: PASSED ===")


def test_happy_end_with_route_metadata():
    """Test happy_end handler with route metadata."""
    logger.info("=== test_happy_end_with_route_metadata ===")

    from handlers.end_handlers import happy_end_handler

    envelope = {
        "id": "test-envelope-route",
        "route": {"actors": ["queue1", "queue2"], "current": 2},
        "payload": {"value": 100},
    }

    result = happy_end_handler(envelope)
    assert result == {}

    logger.info("=== test_happy_end_with_route_metadata: PASSED ===")


def test_happy_end_missing_id():
    """Test happy_end handler with missing id raises error."""
    logger.info("=== test_happy_end_missing_id ===")

    from handlers.end_handlers import happy_end_handler

    envelope = {"payload": {"result": "test"}}

    with pytest.raises(ValueError, match="id"):
        happy_end_handler(envelope)

    logger.info("=== test_happy_end_missing_id: PASSED ===")


def test_happy_end_returns_metadata():
    """Test happy_end handler returns empty dict (sidecar extracts result from envelope)."""
    logger.info("=== test_happy_end_returns_metadata ===")

    from handlers.end_handlers import happy_end_handler

    envelope = {"id": "test-envelope-metadata", "payload": {"value": 42}}

    result = happy_end_handler(envelope)
    assert result == {}

    logger.info("=== test_happy_end_returns_metadata: PASSED ===")


# ============================================================================
# Error End Handler Tests
# ============================================================================


def test_error_end_returns_error_metadata():
    """Test error_end handler returns empty dict (sidecar extracts error from envelope)."""
    logger.info("=== test_error_end_returns_error_metadata ===")

    from handlers.end_handlers import error_end_handler

    envelope = {
        "id": "test-envelope-001",
        "error": "Processing failed",
        "route": {},
        "payload": {},
    }

    result = error_end_handler(envelope)

    assert result == {}

    logger.info("=== test_error_end_returns_error_metadata: PASSED ===")


def test_error_end_missing_id():
    """Test error_end handler raises error for missing id."""
    logger.info("=== test_error_end_missing_id ===")

    from handlers.end_handlers import error_end_handler

    envelope = {"error": "Test error"}

    with pytest.raises(ValueError, match="id"):
        error_end_handler(envelope)

    logger.info("=== test_error_end_missing_id: PASSED ===")


# ============================================================================
# S3 Persistence Tests
# ============================================================================


def test_happy_end_without_s3():
    """Test happy_end without S3 persistence (S3 optional)."""
    logger.info("=== test_happy_end_without_s3 ===")

    from handlers.end_handlers import happy_end_handler

    envelope = {
        "id": "test-no-s3",
        "route": {"actors": ["queue1", "queue2"], "current": 2},
        "payload": {"value": 42},
    }

    result = happy_end_handler(envelope)
    assert result == {}

    logger.info("=== test_happy_end_without_s3: PASSED ===")


def test_error_end_without_s3():
    """Test error_end without S3 persistence (S3 optional)."""
    logger.info("=== test_error_end_without_s3 ===")

    from handlers.end_handlers import error_end_handler

    envelope = {
        "id": "test-error-no-s3",
        "error": "Test failure",
        "route": {"actors": ["queue1"], "current": 1},
        "payload": {"data": "test"},
    }

    result = error_end_handler(envelope)
    assert result == {}

    logger.info("=== test_error_end_without_s3: PASSED ===")


# ============================================================================
# Error Parsing Tests (integrated into error_end_handler)
# ============================================================================
# Note: parse_error_envelope was removed - error_end_handler now handles
# unwrapping directly without a separate parsing function
