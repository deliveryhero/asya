#!/usr/bin/env python3
"""
Unit tests for sump handler.

Tests the x-sump actor which handles final termination,
logging errors and emitting metrics.
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
    for key in ["ASYA_S3_BUCKET"]:
        if key in os.environ:
            del os.environ[key]

    os.environ["ASYA_HANDLER_MODE"] = "envelope"
    os.environ["ASYA_ENABLE_VALIDATION"] = "false"

    yield

    for key in ["ASYA_S3_BUCKET"]:
        if key in os.environ:
            del os.environ[key]


def test_import_raises_with_payload_mode():
    """Test that importing sump module raises RuntimeError when ASYA_HANDLER_MODE=payload."""
    logger.info("=== test_import_raises_with_payload_mode ===")

    os.environ["ASYA_HANDLER_MODE"] = "payload"

    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]

    with pytest.raises(RuntimeError, match="Sump handler must run in envelope mode"):
        import asya_crew.sump  # noqa: F401

    os.environ["ASYA_HANDLER_MODE"] = "envelope"
    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]

    logger.info("=== test_import_raises_with_payload_mode: PASSED ===")


def test_import_succeeds_with_envelope_mode():
    """Test that importing sump module succeeds when ASYA_HANDLER_MODE=envelope."""
    logger.info("=== test_import_succeeds_with_envelope_mode ===")

    os.environ["ASYA_HANDLER_MODE"] = "envelope"

    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]

    import asya_crew.sump  # noqa: F401

    logger.info("=== test_import_succeeds_with_envelope_mode: PASSED ===")


def test_import_raises_with_validation_enabled():
    """Test that importing sump module raises RuntimeError when ASYA_ENABLE_VALIDATION=true."""
    logger.info("=== test_import_raises_with_validation_enabled ===")

    os.environ["ASYA_HANDLER_MODE"] = "envelope"
    os.environ["ASYA_ENABLE_VALIDATION"] = "true"

    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]

    with pytest.raises(RuntimeError, match="Sump handler must run with validation disabled"):
        import asya_crew.sump  # noqa: F401

    os.environ["ASYA_ENABLE_VALIDATION"] = "false"
    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]

    logger.info("=== test_import_raises_with_validation_enabled: PASSED ===")


def test_import_succeeds_with_validation_disabled():
    """Test that importing sump module succeeds when ASYA_ENABLE_VALIDATION=false."""
    logger.info("=== test_import_succeeds_with_validation_disabled ===")

    os.environ["ASYA_HANDLER_MODE"] = "envelope"
    os.environ["ASYA_ENABLE_VALIDATION"] = "false"

    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]

    import asya_crew.sump  # noqa: F401

    logger.info("=== test_import_succeeds_with_validation_disabled: PASSED ===")


def test_succeeded_phase_returns_none(caplog):
    """Test sump handler with succeeded phase returns None with debug log."""
    logger.info("=== test_succeeded_phase_returns_none ===")

    from asya_crew.sump import sump_handler

    message = {
        "id": "test-message-123",
        "status": {"phase": "succeeded", "actor": "test-actor"},
        "payload": {"result": 42},
    }

    with caplog.at_level(logging.DEBUG):
        sump_handler(message)

    assert "Terminal success for message test-message-123" in caplog.text

    logger.info("=== test_succeeded_phase_returns_none: PASSED ===")


def test_failed_phase_returns_none_logs_error(caplog):
    """Test sump handler with failed phase returns None and logs full message at ERROR level."""
    logger.info("=== test_failed_phase_returns_none_logs_error ===")

    from asya_crew.sump import sump_handler

    message = {
        "id": "test-message-456",
        "status": {"phase": "failed", "actor": "test-actor"},
        "error": "Processing failed",
        "payload": {"data": "test"},
    }

    with caplog.at_level(logging.ERROR):
        sump_handler(message)

    assert "Terminal failure for message test-message-456" in caplog.text
    assert '"id": "test-message-456"' in caplog.text
    assert '"error": "Processing failed"' in caplog.text

    logger.info("=== test_failed_phase_returns_none_logs_error: PASSED ===")


def test_missing_id():
    """Test sump handler with missing id raises ValueError."""
    logger.info("=== test_missing_id ===")

    from asya_crew.sump import sump_handler

    message = {"status": {"phase": "succeeded"}}

    with pytest.raises(ValueError, match="id"):
        sump_handler(message)

    logger.info("=== test_missing_id: PASSED ===")


def test_missing_status():
    """Test sump handler with missing status raises ValueError."""
    logger.info("=== test_missing_status ===")

    from asya_crew.sump import sump_handler

    message = {"id": "test-message"}

    with pytest.raises(ValueError, match="status"):
        sump_handler(message)

    logger.info("=== test_missing_status: PASSED ===")


def test_non_terminal_phase_logs_info(caplog):
    """Non-terminal phase (not succeeded/failed) is logged at INFO level."""
    logger.info("=== test_non_terminal_phase_logs_info ===")

    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]

    from asya_crew.sump import sump_handler

    message = {
        "id": "test-nonterminal",
        "status": {"phase": "awaiting_approval"},
        "payload": {"data": "test"},
    }

    with caplog.at_level(logging.INFO):
        sump_handler(message)

    assert "non-final phase" in caplog.text
    assert "awaiting_approval" in caplog.text
    logger.info("=== test_non_terminal_phase_logs_info: PASSED ===")


def test_invalid_status_type():
    """Test sump handler with invalid status type raises ValueError."""
    logger.info("=== test_invalid_status_type ===")

    from asya_crew.sump import sump_handler

    message = {"id": "test-message", "status": "not-a-dict"}

    with pytest.raises(ValueError, match="status must be a dict"):
        sump_handler(message)

    logger.info("=== test_invalid_status_type: PASSED ===")
