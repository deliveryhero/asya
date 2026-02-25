#!/usr/bin/env python3
"""
Unit tests for generic checkpointer.

Tests the checkpointer which persists messages via state proxy file I/O.
Reads message metadata (id, phase, actor) from VFS at ASYA_MSG_ROOT and
writes complete messages as JSON files to ASYA_PERSISTENCE_MOUNT.
"""

import json
import logging
import os
import sys

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def setup_vfs(tmpdir, msg_id="test-001", phase="succeeded", prev_actors=None, parent_id="", curr="checkpoint"):
    """Create VFS directory structure for testing."""
    os.makedirs(os.path.join(tmpdir, "route"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, "status"), exist_ok=True)

    with open(os.path.join(tmpdir, "id"), "w") as f:
        f.write(msg_id)
    with open(os.path.join(tmpdir, "parent_id"), "w") as f:
        f.write(parent_id)
    with open(os.path.join(tmpdir, "route", "prev"), "w") as f:
        f.write("\n".join(prev_actors) if prev_actors else "")
    with open(os.path.join(tmpdir, "route", "curr"), "w") as f:
        f.write(curr)
    with open(os.path.join(tmpdir, "route", "next"), "w") as f:
        f.write("")
    if phase is not None:
        with open(os.path.join(tmpdir, "status", "phase"), "w") as f:
            f.write(phase)

    return tmpdir


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, monkeypatch):
    """Set up test environment before each test."""
    monkeypatch.delenv("ASYA_PERSISTENCE_MOUNT", raising=False)

    vfs_root = setup_vfs(str(tmp_path))
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]

    yield vfs_root

    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]


def test_succeeded_phase_uses_succeeded_prefix(tmp_path, monkeypatch):
    """Test checkpoint handler writes to succeeded/ prefix for succeeded phase."""
    logger.info("=== test_succeeded_phase_uses_succeeded_prefix ===")

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-message-123", phase="succeeded", prev_actors=["test-actor"])
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    mount_path = str(tmp_path / "checkpoints")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]
    from asya_crew.checkpointer import handler

    result = handler({"result": 42})

    assert result == {}
    files = _find_json_files(mount_path)
    assert len(files) == 1
    assert files[0].startswith(os.path.join(mount_path, "succeeded/"))

    logger.info("=== test_succeeded_phase_uses_succeeded_prefix: PASSED ===")


def test_failed_phase_uses_failed_prefix(tmp_path, monkeypatch):
    """Test checkpoint handler writes to failed/ prefix for failed phase."""
    logger.info("=== test_failed_phase_uses_failed_prefix ===")

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-message-456", phase="failed", prev_actors=["test-actor"])
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    mount_path = str(tmp_path / "checkpoints")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]
    from asya_crew.checkpointer import handler

    result = handler({"error": "Processing failed"})

    assert result == {}
    files = _find_json_files(mount_path)
    assert len(files) == 1
    assert files[0].startswith(os.path.join(mount_path, "failed/"))

    logger.info("=== test_failed_phase_uses_failed_prefix: PASSED ===")


def test_missing_phase_uses_checkpoint_prefix(tmp_path, monkeypatch):
    """Test checkpoint handler writes to checkpoint/ prefix when status/phase VFS file is absent."""
    logger.info("=== test_missing_phase_uses_checkpoint_prefix ===")

    vfs_root = setup_vfs(str(tmp_path / "no_phase"), msg_id="test-message-789", phase=None, prev_actors=["test-actor"])
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    mount_path = str(tmp_path / "checkpoints")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]
    from asya_crew.checkpointer import handler

    result = handler({"data": "test"})

    assert result == {}
    files = _find_json_files(mount_path)
    assert len(files) == 1
    assert files[0].startswith(os.path.join(mount_path, "checkpoint/"))

    logger.info("=== test_missing_phase_uses_checkpoint_prefix: PASSED ===")


def test_returns_empty_dict(tmp_path, monkeypatch):
    """Test checkpoint handler returns empty dict."""
    logger.info("=== test_returns_empty_dict ===")

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-message-abc", phase="succeeded")
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]
    from asya_crew.checkpointer import handler

    result = handler({"result": 100})

    assert result == {}

    logger.info("=== test_returns_empty_dict: PASSED ===")


def test_skips_when_mount_not_configured(tmp_path, monkeypatch):
    """Test checkpoint handler gracefully skips when ASYA_PERSISTENCE_MOUNT not set."""
    logger.info("=== test_skips_when_mount_not_configured ===")

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-message-no-mount", phase="succeeded")
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]
    from asya_crew.checkpointer import handler

    result = handler({"value": 42})

    assert result == {}

    logger.info("=== test_skips_when_mount_not_configured: PASSED ===")


def test_key_includes_actor_from_vfs_prev(tmp_path, monkeypatch):
    """Test checkpoint handler uses last prev actor from VFS for file path."""
    logger.info("=== test_key_includes_actor_from_vfs_prev ===")

    vfs_root = setup_vfs(
        str(tmp_path),
        msg_id="test-actor-key",
        phase="succeeded",
        prev_actors=["actor-a", "actor-b", "text-processor"],
    )
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    mount_path = str(tmp_path / "checkpoints")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]
    from asya_crew.checkpointer import handler

    result = handler({"data": "test"})

    assert result == {}
    files = _find_json_files(mount_path)
    assert len(files) == 1
    assert "/text-processor/" in files[0]
    assert files[0].endswith("test-actor-key.json")

    logger.info("=== test_key_includes_actor_from_vfs_prev: PASSED ===")


def test_persists_complete_message(tmp_path, monkeypatch):
    """Test checkpoint handler writes full message with metadata and payload."""
    logger.info("=== test_persists_complete_message ===")

    vfs_root = setup_vfs(
        str(tmp_path),
        msg_id="msg-full",
        phase="succeeded",
        prev_actors=["actor-a", "actor-b"],
        parent_id="parent-001",
        curr="checkpoint",
    )
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    mount_path = str(tmp_path / "checkpoints")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]
    from asya_crew.checkpointer import handler

    handler({"result": 42})

    files = _find_json_files(mount_path)
    assert len(files) == 1

    with open(files[0]) as f:
        message = json.load(f)

    assert message["id"] == "msg-full"
    assert message["parent_id"] == "parent-001"
    assert message["route"]["prev"] == ["actor-a", "actor-b"]
    assert message["route"]["curr"] == "checkpoint"
    assert message["status"]["phase"] == "succeeded"
    assert message["payload"] == {"result": 42}

    logger.info("=== test_persists_complete_message: PASSED ===")


def test_message_without_parent_id(tmp_path, monkeypatch):
    """Test checkpoint handler omits parent_id field when empty."""
    logger.info("=== test_message_without_parent_id ===")

    vfs_root = setup_vfs(
        str(tmp_path),
        msg_id="msg-no-parent",
        phase="succeeded",
        prev_actors=["actor-a"],
        parent_id="",
    )
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    mount_path = str(tmp_path / "checkpoints")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]
    from asya_crew.checkpointer import handler

    handler({"data": "test"})

    files = _find_json_files(mount_path)
    with open(files[0]) as f:
        message = json.load(f)

    assert "parent_id" not in message

    logger.info("=== test_message_without_parent_id: PASSED ===")


def test_raises_on_non_dict_payload(tmp_path, monkeypatch):
    """Test checkpoint handler raises ValueError when payload is not a dict."""
    logger.info("=== test_raises_on_non_dict_payload ===")

    vfs_root = setup_vfs(str(tmp_path))
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]
    from asya_crew.checkpointer import handler

    with pytest.raises(ValueError, match="Payload must be a dict"):
        handler("not-a-dict")  # type: ignore[arg-type]

    logger.info("=== test_raises_on_non_dict_payload: PASSED ===")


def _find_json_files(root: str) -> list[str]:
    """Recursively find all .json files under root."""
    result = []
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            if f.endswith(".json"):
                result.append(os.path.join(dirpath, f))
    return result
