#!/usr/bin/env python3
"""
Unit tests for _sink handler.

Tests the unified terminal handler that replaces happy-end and error-end,
using status.phase to determine storage prefix.
"""

import logging
import os
import sys

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def setup_test_env():
    """Set up test environment before each test."""
    for key in ["ASYA_S3_BUCKET", "ASYA_S3_ENDPOINT"]:
        if key in os.environ:
            del os.environ[key]

    os.environ["ASYA_HANDLER_MODE"] = "envelope"
    os.environ["ASYA_ENABLE_VALIDATION"] = "false"

    yield

    for key in ["ASYA_S3_BUCKET", "ASYA_S3_ENDPOINT"]:
        if key in os.environ:
            del os.environ[key]


# ============================================================================
# Handler Mode Validation Tests
# ============================================================================


def test_import_raises_with_payload_mode():
    """Test that importing sink_handler raises RuntimeError when ASYA_HANDLER_MODE=payload."""
    os.environ["ASYA_HANDLER_MODE"] = "payload"

    if "handlers.sink_handler" in sys.modules:
        del sys.modules["handlers.sink_handler"]

    with pytest.raises(RuntimeError, match="_sink handler must run in envelope mode"):
        import handlers.sink_handler  # noqa: F401

    os.environ["ASYA_HANDLER_MODE"] = "envelope"
    if "handlers.sink_handler" in sys.modules:
        del sys.modules["handlers.sink_handler"]


def test_import_succeeds_with_envelope_mode():
    """Test that importing sink_handler succeeds when ASYA_HANDLER_MODE=envelope."""
    os.environ["ASYA_HANDLER_MODE"] = "envelope"

    if "handlers.sink_handler" in sys.modules:
        del sys.modules["handlers.sink_handler"]

    import handlers.sink_handler  # noqa: F401


def test_import_raises_with_validation_enabled():
    """Test that importing sink_handler raises RuntimeError when ASYA_ENABLE_VALIDATION=true."""
    os.environ["ASYA_HANDLER_MODE"] = "envelope"
    os.environ["ASYA_ENABLE_VALIDATION"] = "true"

    if "handlers.sink_handler" in sys.modules:
        del sys.modules["handlers.sink_handler"]

    with pytest.raises(RuntimeError, match="_sink handler must run with validation disabled"):
        import handlers.sink_handler  # noqa: F401

    os.environ["ASYA_ENABLE_VALIDATION"] = "false"
    if "handlers.sink_handler" in sys.modules:
        del sys.modules["handlers.sink_handler"]


# ============================================================================
# Succeeded Phase Tests
# ============================================================================


def test_sink_succeeded_returns_empty_dict():
    """Test _sink handler with succeeded phase returns empty dict."""
    from handlers.sink_handler import sink_handler

    message = {
        "id": "msg-001",
        "route": {"actors": ["actor-a", "actor-b"], "current": 2},
        "headers": {"trace_id": "xyz"},
        "payload": {"result": "success"},
        "status": {"phase": "succeeded", "actor": "actor-b", "attempt": 1, "max_attempts": 5},
    }

    result = sink_handler(message)
    assert result == {}


def test_sink_succeeded_with_minimal_message():
    """Test _sink handler with minimal succeeded message."""
    from handlers.sink_handler import sink_handler

    message = {
        "id": "msg-002",
        "payload": {},
        "status": {"phase": "succeeded"},
    }

    result = sink_handler(message)
    assert result == {}


# ============================================================================
# Failed Phase Tests
# ============================================================================


def test_sink_failed_returns_empty_dict():
    """Test _sink handler with failed phase returns empty dict."""
    from handlers.sink_handler import sink_handler

    message = {
        "id": "msg-003",
        "route": {"actors": ["actor-a", "actor-b"], "current": 1},
        "headers": {},
        "payload": {"input": "data"},
        "status": {
            "phase": "failed",
            "reason": "MaxRetriesExhausted",
            "actor": "actor-b",
            "attempt": 5,
            "max_attempts": 5,
            "error": {
                "type": "requests.exceptions.ConnectionError",
                "mro": ["ConnectionError", "IOError", "OSError", "Exception"],
                "message": "Connection refused",
            },
        },
    }

    result = sink_handler(message)
    assert result == {}


def test_sink_failed_with_non_retryable_error():
    """Test _sink handler with non-retryable failure."""
    from handlers.sink_handler import sink_handler

    message = {
        "id": "msg-004",
        "route": {"actors": ["validator"], "current": 0},
        "payload": {"bad": "data"},
        "status": {
            "phase": "failed",
            "reason": "NonRetryableFailure",
            "actor": "validator",
            "attempt": 1,
            "max_attempts": 5,
            "error": {
                "type": "ValueError",
                "mro": ["Exception"],
                "message": "Invalid input format",
            },
        },
    }

    result = sink_handler(message)
    assert result == {}


# ============================================================================
# Validation Tests
# ============================================================================


def test_sink_missing_id():
    """Test _sink handler raises ValueError when id is missing."""
    from handlers.sink_handler import sink_handler

    message = {
        "payload": {},
        "status": {"phase": "succeeded"},
    }

    with pytest.raises(ValueError, match="id"):
        sink_handler(message)


def test_sink_missing_status():
    """Test _sink handler raises ValueError when status is missing."""
    from handlers.sink_handler import sink_handler

    message = {
        "id": "msg-005",
        "payload": {},
    }

    with pytest.raises(ValueError, match="status"):
        sink_handler(message)


def test_sink_invalid_phase():
    """Test _sink handler raises ValueError for invalid status.phase."""
    from handlers.sink_handler import sink_handler

    message = {
        "id": "msg-006",
        "payload": {},
        "status": {"phase": "processing"},
    }

    with pytest.raises(ValueError, match="Invalid status.phase"):
        sink_handler(message)


def test_sink_missing_phase():
    """Test _sink handler raises ValueError when status.phase is missing."""
    from handlers.sink_handler import sink_handler

    message = {
        "id": "msg-007",
        "payload": {},
        "status": {"actor": "some-actor"},
    }

    with pytest.raises(ValueError, match="Invalid status.phase"):
        sink_handler(message)


def test_sink_non_dict_message():
    """Test _sink handler raises ValueError for non-dict message."""
    from handlers.sink_handler import sink_handler

    with pytest.raises(ValueError, match="Message must be a dict"):
        sink_handler("not a dict")  # type: ignore[arg-type]


def test_sink_status_is_not_dict():
    """Test _sink handler raises ValueError when status is not a dict."""
    from handlers.sink_handler import sink_handler

    message = {
        "id": "msg-008",
        "payload": {},
        "status": "succeeded",
    }

    with pytest.raises(ValueError, match="status"):
        sink_handler(message)


# ============================================================================
# S3 Persistence Tests (without S3 configured)
# ============================================================================


def test_sink_succeeded_without_s3():
    """Test _sink handler works without S3 persistence configured."""
    from handlers.sink_handler import sink_handler

    message = {
        "id": "msg-no-s3-ok",
        "route": {"actors": ["a", "b"], "current": 2},
        "payload": {"value": 42},
        "status": {"phase": "succeeded", "actor": "b"},
    }

    result = sink_handler(message)
    assert result == {}


def test_sink_failed_without_s3():
    """Test _sink handler works without S3 for failed messages."""
    from handlers.sink_handler import sink_handler

    message = {
        "id": "msg-no-s3-fail",
        "route": {"actors": ["a"], "current": 0},
        "payload": {"data": "test"},
        "status": {
            "phase": "failed",
            "reason": "MaxRetriesExhausted",
            "actor": "a",
            "error": {"type": "RuntimeError", "message": "boom"},
        },
    }

    result = sink_handler(message)
    assert result == {}
