#!/usr/bin/env python3
"""
Unit tests for S3 message persistence.

Tests the checkpoint-s3 actor which persists messages to S3/MinIO.
Reads message metadata (id, phase, actor) from VFS at ASYA_MSG_ROOT.
"""

import logging
import os
import sys
from unittest.mock import MagicMock, patch

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def setup_vfs(tmpdir, msg_id="test-001", phase="succeeded", prev_actors=None):
    """Create VFS directory structure for testing."""
    os.makedirs(os.path.join(tmpdir, "route"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, "status"), exist_ok=True)

    with open(os.path.join(tmpdir, "id"), "w") as f:
        f.write(msg_id)
    with open(os.path.join(tmpdir, "parent_id"), "w") as f:
        f.write("")
    with open(os.path.join(tmpdir, "route", "prev"), "w") as f:
        f.write("\n".join(prev_actors) if prev_actors else "")
    with open(os.path.join(tmpdir, "route", "curr"), "w") as f:
        f.write("checkpoint-s3")
    with open(os.path.join(tmpdir, "route", "next"), "w") as f:
        f.write("")
    if phase is not None:
        with open(os.path.join(tmpdir, "status", "phase"), "w") as f:
            f.write(phase)

    return tmpdir


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, monkeypatch):
    """Set up test environment before each test."""
    for key in ["ASYA_S3_BUCKET", "ASYA_S3_ENDPOINT"]:
        monkeypatch.delenv(key, raising=False)

    vfs_root = setup_vfs(str(tmp_path))
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.message_persistence.s3" in sys.modules:
        del sys.modules["asya_crew.message_persistence.s3"]

    yield vfs_root

    if "asya_crew.message_persistence.s3" in sys.modules:
        del sys.modules["asya_crew.message_persistence.s3"]


def test_succeeded_phase_uses_succeeded_prefix(tmp_path, monkeypatch):
    """Test checkpoint handler uses succeeded/ prefix for succeeded phase."""
    logger.info("=== test_succeeded_phase_uses_succeeded_prefix ===")

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-message-123", phase="succeeded", prev_actors=["test-actor"])
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)
    monkeypatch.setenv("ASYA_S3_BUCKET", "test-bucket")

    if "asya_crew.message_persistence.s3" in sys.modules:
        del sys.modules["asya_crew.message_persistence.s3"]

    mock_s3 = MagicMock()
    with patch.dict("sys.modules", {"boto3": MagicMock()}):
        import asya_crew.message_persistence.s3 as s3_mod

        s3_mod.s3_client = mock_s3

        result = s3_mod.checkpoint_handler({"result": 42})

        assert result == {}
        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Key"].startswith("succeeded/")

    logger.info("=== test_succeeded_phase_uses_succeeded_prefix: PASSED ===")


def test_failed_phase_uses_failed_prefix(tmp_path, monkeypatch):
    """Test checkpoint handler uses failed/ prefix for failed phase."""
    logger.info("=== test_failed_phase_uses_failed_prefix ===")

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-message-456", phase="failed", prev_actors=["test-actor"])
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)
    monkeypatch.setenv("ASYA_S3_BUCKET", "test-bucket")

    if "asya_crew.message_persistence.s3" in sys.modules:
        del sys.modules["asya_crew.message_persistence.s3"]

    mock_s3 = MagicMock()
    with patch.dict("sys.modules", {"boto3": MagicMock()}):
        import asya_crew.message_persistence.s3 as s3_mod

        s3_mod.s3_client = mock_s3

        result = s3_mod.checkpoint_handler({"error": "Processing failed"})

        assert result == {}
        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Key"].startswith("failed/")

    logger.info("=== test_failed_phase_uses_failed_prefix: PASSED ===")


def test_missing_phase_uses_checkpoint_prefix(tmp_path, monkeypatch):
    """Test checkpoint handler uses checkpoint/ prefix when status/phase VFS file is absent."""
    logger.info("=== test_missing_phase_uses_checkpoint_prefix ===")

    vfs_root = setup_vfs(str(tmp_path / "no_phase"), msg_id="test-message-789", phase=None, prev_actors=["test-actor"])
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)
    monkeypatch.setenv("ASYA_S3_BUCKET", "test-bucket")

    if "asya_crew.message_persistence.s3" in sys.modules:
        del sys.modules["asya_crew.message_persistence.s3"]

    mock_s3 = MagicMock()
    with patch.dict("sys.modules", {"boto3": MagicMock()}):
        import asya_crew.message_persistence.s3 as s3_mod

        s3_mod.s3_client = mock_s3

        result = s3_mod.checkpoint_handler({"data": "test"})

        assert result == {}
        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Key"].startswith("checkpoint/")

    logger.info("=== test_missing_phase_uses_checkpoint_prefix: PASSED ===")


def test_returns_empty_dict(tmp_path, monkeypatch):
    """Test checkpoint handler returns empty dict."""
    logger.info("=== test_returns_empty_dict ===")

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-message-abc", phase="succeeded")
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.message_persistence.s3" in sys.modules:
        del sys.modules["asya_crew.message_persistence.s3"]

    from asya_crew.message_persistence.s3 import checkpoint_handler

    result = checkpoint_handler({"result": 100})

    assert result == {}

    logger.info("=== test_returns_empty_dict: PASSED ===")


def test_works_without_s3_configured(tmp_path, monkeypatch):
    """Test checkpoint handler gracefully skips when S3 not configured."""
    logger.info("=== test_works_without_s3_configured ===")

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-message-no-s3", phase="succeeded")
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.message_persistence.s3" in sys.modules:
        del sys.modules["asya_crew.message_persistence.s3"]

    from asya_crew.message_persistence.s3 import checkpoint_handler

    result = checkpoint_handler({"value": 42})

    assert result == {}

    logger.info("=== test_works_without_s3_configured: PASSED ===")


def test_key_includes_actor_from_vfs_prev(tmp_path, monkeypatch):
    """Test checkpoint handler uses last prev actor from VFS for S3 key."""
    logger.info("=== test_key_includes_actor_from_vfs_prev ===")

    vfs_root = setup_vfs(
        str(tmp_path),
        msg_id="test-actor-key",
        phase="succeeded",
        prev_actors=["actor-a", "actor-b", "text-processor"],
    )
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)
    monkeypatch.setenv("ASYA_S3_BUCKET", "test-bucket")

    if "asya_crew.message_persistence.s3" in sys.modules:
        del sys.modules["asya_crew.message_persistence.s3"]

    mock_s3 = MagicMock()
    with patch.dict("sys.modules", {"boto3": MagicMock()}):
        import asya_crew.message_persistence.s3 as s3_mod

        s3_mod.s3_client = mock_s3

        result = s3_mod.checkpoint_handler({"data": "test"})

        assert result == {}
        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args.kwargs
        key = call_kwargs["Key"]
        assert "/text-processor/" in key
        assert key.endswith("test-actor-key.json")

    logger.info("=== test_key_includes_actor_from_vfs_prev: PASSED ===")


def test_raises_on_non_dict_payload(tmp_path, monkeypatch):
    """Test checkpoint handler raises ValueError when payload is not a dict."""
    logger.info("=== test_raises_on_non_dict_payload ===")

    vfs_root = setup_vfs(str(tmp_path))
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.message_persistence.s3" in sys.modules:
        del sys.modules["asya_crew.message_persistence.s3"]

    from asya_crew.message_persistence.s3 import checkpoint_handler

    with pytest.raises(ValueError, match="Payload must be a dict"):
        checkpoint_handler("not-a-dict")  # type: ignore[arg-type]

    logger.info("=== test_raises_on_non_dict_payload: PASSED ===")
