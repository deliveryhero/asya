#!/usr/bin/env python3
"""
Unit tests for sink handler.

Tests the x-sink actor which handles first-layer termination,
reporting final status to gateway and routing to configurable hooks.
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
    for key in ["ASYA_SINK_HOOKS", "ASYA_S3_BUCKET"]:
        if key in os.environ:
            del os.environ[key]

    os.environ["ASYA_HANDLER_MODE"] = "envelope"
    os.environ["ASYA_ENABLE_VALIDATION"] = "false"

    yield

    for key in ["ASYA_SINK_HOOKS", "ASYA_S3_BUCKET"]:
        if key in os.environ:
            del os.environ[key]


def test_import_raises_with_payload_mode():
    """Test that importing sink module raises RuntimeError when ASYA_HANDLER_MODE=payload."""
    logger.info("=== test_import_raises_with_payload_mode ===")

    os.environ["ASYA_HANDLER_MODE"] = "payload"

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]

    with pytest.raises(RuntimeError, match="Sink handler must run in envelope mode"):
        import asya_crew.sink  # noqa: F401

    os.environ["ASYA_HANDLER_MODE"] = "envelope"
    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]

    logger.info("=== test_import_raises_with_payload_mode: PASSED ===")


def test_import_succeeds_with_envelope_mode():
    """Test that importing sink module succeeds when ASYA_HANDLER_MODE=envelope."""
    logger.info("=== test_import_succeeds_with_envelope_mode ===")

    os.environ["ASYA_HANDLER_MODE"] = "envelope"

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]

    import asya_crew.sink  # noqa: F401

    logger.info("=== test_import_succeeds_with_envelope_mode: PASSED ===")


def test_import_raises_with_validation_enabled():
    """Test that importing sink module raises RuntimeError when ASYA_ENABLE_VALIDATION=true."""
    logger.info("=== test_import_raises_with_validation_enabled ===")

    os.environ["ASYA_HANDLER_MODE"] = "envelope"
    os.environ["ASYA_ENABLE_VALIDATION"] = "true"

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]

    with pytest.raises(RuntimeError, match="Sink handler must run with validation disabled"):
        import asya_crew.sink  # noqa: F401

    os.environ["ASYA_ENABLE_VALIDATION"] = "false"
    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]

    logger.info("=== test_import_raises_with_validation_enabled: PASSED ===")


def test_import_succeeds_with_validation_disabled():
    """Test that importing sink module succeeds when ASYA_ENABLE_VALIDATION=false."""
    logger.info("=== test_import_succeeds_with_validation_disabled ===")

    os.environ["ASYA_HANDLER_MODE"] = "envelope"
    os.environ["ASYA_ENABLE_VALIDATION"] = "false"

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]

    import asya_crew.sink  # noqa: F401

    logger.info("=== test_import_succeeds_with_validation_disabled: PASSED ===")


def test_succeeded_phase_with_hooks():
    """Test sink handler with succeeded phase and hooks configured."""
    logger.info("=== test_succeeded_phase_with_hooks ===")

    os.environ["ASYA_SINK_HOOKS"] = "checkpoint-s3,notify-slack"

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]

    from asya_crew.sink import sink_handler

    message = {
        "id": "test-message-123",
        "status": {"phase": "succeeded", "actor": "test-actor"},
        "payload": {"result": 42},
    }

    result = sink_handler(message)

    assert result["route"] == {"actors": ["checkpoint-s3", "notify-slack"], "current": 0}
    assert result["id"] == "test-message-123"

    logger.info("=== test_succeeded_phase_with_hooks: PASSED ===")


def test_failed_phase_with_hooks():
    """Test sink handler with failed phase and hooks configured."""
    logger.info("=== test_failed_phase_with_hooks ===")

    os.environ["ASYA_SINK_HOOKS"] = "checkpoint-s3"

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]

    from asya_crew.sink import sink_handler

    message = {
        "id": "test-message-456",
        "status": {"phase": "failed", "actor": "test-actor"},
        "error": "Processing failed",
    }

    result = sink_handler(message)

    assert result["route"] == {"actors": ["checkpoint-s3"], "current": 0}

    logger.info("=== test_failed_phase_with_hooks: PASSED ===")


def test_succeeded_phase_no_hooks():
    """Test sink handler with succeeded phase and no hooks configured."""
    logger.info("=== test_succeeded_phase_no_hooks ===")

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]

    from asya_crew.sink import sink_handler

    message = {
        "id": "test-message-789",
        "status": {"phase": "succeeded", "actor": "test-actor"},
        "payload": {"result": 100},
    }

    result = sink_handler(message)

    assert result == {}

    logger.info("=== test_succeeded_phase_no_hooks: PASSED ===")


def test_failed_phase_no_hooks():
    """Test sink handler with failed phase and no hooks configured."""
    logger.info("=== test_failed_phase_no_hooks ===")

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]

    from asya_crew.sink import sink_handler

    message = {
        "id": "test-message-abc",
        "status": {"phase": "failed", "actor": "test-actor"},
        "error": "Test error",
    }

    result = sink_handler(message)

    assert result == {}

    logger.info("=== test_failed_phase_no_hooks: PASSED ===")


def test_missing_id():
    """Test sink handler with missing id raises ValueError."""
    logger.info("=== test_missing_id ===")

    from asya_crew.sink import sink_handler

    message = {"status": {"phase": "succeeded"}}

    with pytest.raises(ValueError, match="id"):
        sink_handler(message)

    logger.info("=== test_missing_id: PASSED ===")


def test_missing_status():
    """Test sink handler with missing status raises ValueError."""
    logger.info("=== test_missing_status ===")

    from asya_crew.sink import sink_handler

    message = {"id": "test-message"}

    with pytest.raises(ValueError, match="status"):
        sink_handler(message)

    logger.info("=== test_missing_status: PASSED ===")


def test_invalid_status_type():
    """Test sink handler with invalid status type raises ValueError."""
    logger.info("=== test_invalid_status_type ===")

    from asya_crew.sink import sink_handler

    message = {"id": "test-message", "status": "not-a-dict"}

    with pytest.raises(ValueError, match="status must be a dict"):
        sink_handler(message)

    logger.info("=== test_invalid_status_type: PASSED ===")


def test_invalid_phase():
    """Test sink handler with invalid phase raises ValueError."""
    logger.info("=== test_invalid_phase ===")

    from asya_crew.sink import sink_handler

    message = {"id": "test-message", "status": {"phase": "processing"}}

    with pytest.raises(ValueError, match="Invalid status.phase"):
        sink_handler(message)

    logger.info("=== test_invalid_phase: PASSED ===")
