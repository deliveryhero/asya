#!/usr/bin/env python3
"""
Unit tests for S3 message persistence.

Tests the checkpoint-s3 actor which persists messages to S3/MinIO.
"""

import logging
import os
import sys
from unittest.mock import MagicMock, patch

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


def test_import_raises_with_payload_mode():
    """Test that importing s3 module raises RuntimeError when ASYA_HANDLER_MODE=payload."""
    logger.info("=== test_import_raises_with_payload_mode ===")

    os.environ["ASYA_HANDLER_MODE"] = "payload"

    if "asya_crew.message_persistence.s3" in sys.modules:
        del sys.modules["asya_crew.message_persistence.s3"]

    with pytest.raises(RuntimeError, match="Checkpoint handler must run in envelope mode"):
        import asya_crew.message_persistence.s3  # noqa: F401

    os.environ["ASYA_HANDLER_MODE"] = "envelope"
    if "asya_crew.message_persistence.s3" in sys.modules:
        del sys.modules["asya_crew.message_persistence.s3"]

    logger.info("=== test_import_raises_with_payload_mode: PASSED ===")


def test_import_succeeds_with_envelope_mode():
    """Test that importing s3 module succeeds when ASYA_HANDLER_MODE=envelope."""
    logger.info("=== test_import_succeeds_with_envelope_mode ===")

    os.environ["ASYA_HANDLER_MODE"] = "envelope"

    if "asya_crew.message_persistence.s3" in sys.modules:
        del sys.modules["asya_crew.message_persistence.s3"]

    import asya_crew.message_persistence.s3  # noqa: F401

    logger.info("=== test_import_succeeds_with_envelope_mode: PASSED ===")


def test_import_raises_with_validation_enabled():
    """Test that importing s3 module raises RuntimeError when ASYA_ENABLE_VALIDATION=true."""
    logger.info("=== test_import_raises_with_validation_enabled ===")

    os.environ["ASYA_HANDLER_MODE"] = "envelope"
    os.environ["ASYA_ENABLE_VALIDATION"] = "true"

    if "asya_crew.message_persistence.s3" in sys.modules:
        del sys.modules["asya_crew.message_persistence.s3"]

    with pytest.raises(RuntimeError, match="Checkpoint handler must run with validation disabled"):
        import asya_crew.message_persistence.s3  # noqa: F401

    os.environ["ASYA_ENABLE_VALIDATION"] = "false"
    if "asya_crew.message_persistence.s3" in sys.modules:
        del sys.modules["asya_crew.message_persistence.s3"]

    logger.info("=== test_import_raises_with_validation_enabled: PASSED ===")


def test_import_succeeds_with_validation_disabled():
    """Test that importing s3 module succeeds when ASYA_ENABLE_VALIDATION=false."""
    logger.info("=== test_import_succeeds_with_validation_disabled ===")

    os.environ["ASYA_HANDLER_MODE"] = "envelope"
    os.environ["ASYA_ENABLE_VALIDATION"] = "false"

    if "asya_crew.message_persistence.s3" in sys.modules:
        del sys.modules["asya_crew.message_persistence.s3"]

    import asya_crew.message_persistence.s3  # noqa: F401

    logger.info("=== test_import_succeeds_with_validation_disabled: PASSED ===")


def test_succeeded_phase_uses_succeeded_prefix():
    """Test checkpoint handler uses succeeded/ prefix for succeeded phase."""
    logger.info("=== test_succeeded_phase_uses_succeeded_prefix ===")

    os.environ["ASYA_S3_BUCKET"] = "test-bucket"
    if "asya_crew.message_persistence.s3" in sys.modules:
        del sys.modules["asya_crew.message_persistence.s3"]

    mock_s3 = MagicMock()
    with patch.dict("sys.modules", {"boto3": MagicMock()}):
        import asya_crew.message_persistence.s3 as s3_mod

        s3_mod.s3_client = mock_s3

        message = {
            "id": "test-message-123",
            "status": {"phase": "succeeded", "actor": "test-actor"},
            "payload": {"result": 42},
        }

        result = s3_mod.checkpoint_handler(message)

        assert result == {}
        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Key"].startswith("succeeded/")

    del os.environ["ASYA_S3_BUCKET"]
    if "asya_crew.message_persistence.s3" in sys.modules:
        del sys.modules["asya_crew.message_persistence.s3"]

    logger.info("=== test_succeeded_phase_uses_succeeded_prefix: PASSED ===")


def test_failed_phase_uses_failed_prefix():
    """Test checkpoint handler uses failed/ prefix for failed phase."""
    logger.info("=== test_failed_phase_uses_failed_prefix ===")

    os.environ["ASYA_S3_BUCKET"] = "test-bucket"
    if "asya_crew.message_persistence.s3" in sys.modules:
        del sys.modules["asya_crew.message_persistence.s3"]

    mock_s3 = MagicMock()
    with patch.dict("sys.modules", {"boto3": MagicMock()}):
        import asya_crew.message_persistence.s3 as s3_mod

        s3_mod.s3_client = mock_s3

        message = {
            "id": "test-message-456",
            "status": {"phase": "failed", "actor": "test-actor"},
            "error": "Processing failed",
        }

        result = s3_mod.checkpoint_handler(message)

        assert result == {}
        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Key"].startswith("failed/")

    del os.environ["ASYA_S3_BUCKET"]
    if "asya_crew.message_persistence.s3" in sys.modules:
        del sys.modules["asya_crew.message_persistence.s3"]

    logger.info("=== test_failed_phase_uses_failed_prefix: PASSED ===")


def test_missing_phase_uses_checkpoint_prefix():
    """Test checkpoint handler uses checkpoint/ prefix when status.phase is missing."""
    logger.info("=== test_missing_phase_uses_checkpoint_prefix ===")

    os.environ["ASYA_S3_BUCKET"] = "test-bucket"
    if "asya_crew.message_persistence.s3" in sys.modules:
        del sys.modules["asya_crew.message_persistence.s3"]

    mock_s3 = MagicMock()
    with patch.dict("sys.modules", {"boto3": MagicMock()}):
        import asya_crew.message_persistence.s3 as s3_mod

        s3_mod.s3_client = mock_s3

        message = {"id": "test-message-789", "status": {"actor": "test-actor"}, "payload": {"data": "test"}}

        result = s3_mod.checkpoint_handler(message)

        assert result == {}
        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Key"].startswith("checkpoint/")

    del os.environ["ASYA_S3_BUCKET"]
    if "asya_crew.message_persistence.s3" in sys.modules:
        del sys.modules["asya_crew.message_persistence.s3"]

    logger.info("=== test_missing_phase_uses_checkpoint_prefix: PASSED ===")


def test_returns_empty_dict():
    """Test checkpoint handler returns empty dict."""
    logger.info("=== test_returns_empty_dict ===")

    from asya_crew.message_persistence.s3 import checkpoint_handler

    message = {
        "id": "test-message-abc",
        "status": {"phase": "succeeded", "actor": "test-actor"},
        "payload": {"result": 100},
    }

    result = checkpoint_handler(message)

    assert result == {}

    logger.info("=== test_returns_empty_dict: PASSED ===")


def test_works_without_s3_configured():
    """Test checkpoint handler gracefully skips when S3 not configured."""
    logger.info("=== test_works_without_s3_configured ===")

    from asya_crew.message_persistence.s3 import checkpoint_handler

    message = {
        "id": "test-message-no-s3",
        "status": {"phase": "succeeded", "actor": "test-actor"},
        "payload": {"value": 42},
    }

    result = checkpoint_handler(message)

    assert result == {}

    logger.info("=== test_works_without_s3_configured: PASSED ===")


def test_missing_id():
    """Test checkpoint handler with missing id raises ValueError."""
    logger.info("=== test_missing_id ===")

    from asya_crew.message_persistence.s3 import checkpoint_handler

    message = {"status": {"phase": "succeeded"}}

    with pytest.raises(ValueError, match="id"):
        checkpoint_handler(message)

    logger.info("=== test_missing_id: PASSED ===")
