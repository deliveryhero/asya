#!/usr/bin/env python3
"""
Unit tests for generic checkpointer.

Tests the checkpointer which persists messages via state proxy file I/O.
Receives message metadata (id, phase, actor) as keyword arguments from
the sink/sump handler and writes complete messages as JSON files to
ASYA_PERSISTENCE_MOUNT.
"""

import json
import logging
import os
import sys

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    """Set up test environment before each test."""
    monkeypatch.delenv("ASYA_PERSISTENCE_MOUNT", raising=False)

    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]

    yield

    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]


def test_succeeded_phase_uses_succeeded_prefix(tmp_path, monkeypatch):
    """Test checkpoint handler writes to succeeded/ prefix for succeeded phase."""
    mount_path = str(tmp_path / "checkpoints")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]
    from asya_crew.checkpointer import handler

    handler(
        {"result": 42},
        message_id="test-message-123",
        phase="succeeded",
        route_prev=["test-actor"],
    )

    files = _find_json_files(mount_path)
    assert len(files) == 1
    assert files[0].startswith(os.path.join(mount_path, "succeeded/"))


def test_failed_phase_uses_failed_prefix(tmp_path, monkeypatch):
    """Test checkpoint handler writes to failed/ prefix for failed phase."""
    mount_path = str(tmp_path / "checkpoints")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]
    from asya_crew.checkpointer import handler

    handler(
        {"error": "Processing failed"},
        message_id="test-message-456",
        phase="failed",
        route_prev=["test-actor"],
    )

    files = _find_json_files(mount_path)
    assert len(files) == 1
    assert files[0].startswith(os.path.join(mount_path, "failed/"))


def test_missing_phase_uses_checkpoint_prefix(tmp_path, monkeypatch):
    """Test checkpoint handler writes to checkpoint/ prefix when phase is empty."""
    mount_path = str(tmp_path / "checkpoints")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]
    from asya_crew.checkpointer import handler

    handler(
        {"data": "test"},
        message_id="test-message-789",
        phase="",
        route_prev=["test-actor"],
    )

    files = _find_json_files(mount_path)
    assert len(files) == 1
    assert files[0].startswith(os.path.join(mount_path, "checkpoint/"))


def test_completes_without_error(tmp_path, monkeypatch):
    """Test checkpoint handler completes without raising."""
    mount_path = str(tmp_path / "checkpoints")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]
    from asya_crew.checkpointer import handler

    handler({"result": 100}, message_id="test-message-abc", phase="succeeded")


def test_skips_when_mount_not_configured(monkeypatch):
    """Test checkpoint handler gracefully skips when ASYA_PERSISTENCE_MOUNT not set."""
    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]
    from asya_crew.checkpointer import handler

    handler({"value": 42}, message_id="test-message-no-mount", phase="succeeded")


def test_key_is_flat_prefix_and_id(tmp_path, monkeypatch):
    """Test checkpoint key is {prefix}/{id}.json — reconstructable by gateway from task ID + status."""
    mount_path = str(tmp_path / "checkpoints")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]
    from asya_crew.checkpointer import handler

    handler(
        {"data": "test"},
        message_id="test-actor-key",
        phase="succeeded",
        route_prev=["actor-a", "actor-b", "text-processor"],
    )

    files = _find_json_files(mount_path)
    assert len(files) == 1
    assert files[0] == os.path.join(mount_path, "succeeded", "test-actor-key.json")


def test_persists_complete_message(tmp_path, monkeypatch):
    """Test checkpoint handler writes full message with metadata and payload."""
    mount_path = str(tmp_path / "checkpoints")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]
    from asya_crew.checkpointer import handler

    handler(
        {"result": 42},
        message_id="msg-full",
        parent_id="parent-001",
        phase="succeeded",
        route_prev=["actor-a", "actor-b"],
        route_curr="checkpoint",
    )

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


def test_message_without_parent_id(tmp_path, monkeypatch):
    """Test checkpoint handler omits parent_id field when empty."""
    mount_path = str(tmp_path / "checkpoints")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]
    from asya_crew.checkpointer import handler

    handler(
        {"data": "test"},
        message_id="msg-no-parent",
        phase="succeeded",
        route_prev=["actor-a"],
    )

    files = _find_json_files(mount_path)
    with open(files[0]) as f:
        message = json.load(f)

    assert "parent_id" not in message


def test_raises_on_non_dict_payload(monkeypatch):
    """Test checkpoint handler raises ValueError when payload is not a dict."""
    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]
    from asya_crew.checkpointer import handler

    with pytest.raises(ValueError, match="Payload must be a dict"):
        handler("not-a-dict", message_id="test")  # type: ignore[arg-type]


def _find_json_files(root: str) -> list[str]:
    """Recursively find all .json files under root."""
    result = []
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            if f.endswith(".json"):
                result.append(os.path.join(dirpath, f))
    return result
