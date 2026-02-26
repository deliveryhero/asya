#!/usr/bin/env python3
"""
Unit tests for sink handler.

Tests the x-sink actor which handles first-layer termination,
routing to configurable hooks and reporting status via VFS.
"""

import logging
import os
import sys

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def setup_vfs(tmpdir, msg_id="test-001", phase="succeeded", parent_id="", headers=None):
    """Create VFS directory structure for testing."""
    os.makedirs(os.path.join(tmpdir, "route"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, "headers"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, "status"), exist_ok=True)

    with open(os.path.join(tmpdir, "id"), "w") as f:
        f.write(msg_id)
    with open(os.path.join(tmpdir, "parent_id"), "w") as f:
        f.write(parent_id)
    with open(os.path.join(tmpdir, "route", "prev"), "w") as f:
        f.write("")
    with open(os.path.join(tmpdir, "route", "curr"), "w") as f:
        f.write("x-sink")
    with open(os.path.join(tmpdir, "route", "next"), "w") as f:
        f.write("")
    if phase is not None:
        with open(os.path.join(tmpdir, "status", "phase"), "w") as f:
            f.write(phase)

    if headers:
        for key, value in headers.items():
            with open(os.path.join(tmpdir, "headers", key), "w") as f:
                f.write(value)

    return tmpdir


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, monkeypatch):
    """Set up test environment before each test."""
    for key in ["ASYA_SINK_HOOKS", "ASYA_SINK_FANOUT_HOOKS", "ASYA_PERSISTENCE_MOUNT"]:
        monkeypatch.delenv(key, raising=False)

    vfs_root = setup_vfs(str(tmp_path))
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]

    yield vfs_root

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]


def test_succeeded_phase_with_hooks(tmp_path, monkeypatch):
    """Test sink handler with succeeded phase and hooks configured."""
    logger.info("=== test_succeeded_phase_with_hooks ===")

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-message-123", phase="succeeded")
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)
    monkeypatch.setenv("ASYA_SINK_HOOKS", "checkpoint-s3,notify-slack")

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]
    from asya_crew.sink import sink_handler

    result = sink_handler({"result": 42})

    with open(os.path.join(vfs_root, "route", "next")) as f:
        next_file = f.read()
    assert next_file == "checkpoint-s3\nnotify-slack"
    assert result == {"result": 42}

    logger.info("=== test_succeeded_phase_with_hooks: PASSED ===")


def test_failed_phase_with_hooks(tmp_path, monkeypatch):
    """Test sink handler with failed phase and hooks configured."""
    logger.info("=== test_failed_phase_with_hooks ===")

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-message-456", phase="failed")
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)
    monkeypatch.setenv("ASYA_SINK_HOOKS", "checkpoint-s3")

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]
    from asya_crew.sink import sink_handler

    result = sink_handler({})

    with open(os.path.join(vfs_root, "route", "next")) as f:
        next_file = f.read()
    assert next_file == "checkpoint-s3"
    assert result == {}

    logger.info("=== test_failed_phase_with_hooks: PASSED ===")


def test_succeeded_phase_no_hooks(tmp_path, monkeypatch):
    """Test sink handler with succeeded phase and no hooks configured."""
    logger.info("=== test_succeeded_phase_no_hooks ===")

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-message-789", phase="succeeded")
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]
    from asya_crew.sink import sink_handler

    result = sink_handler({"result": 100})

    assert result == {"result": 100}

    logger.info("=== test_succeeded_phase_no_hooks: PASSED ===")


def test_failed_phase_no_hooks(tmp_path, monkeypatch):
    """Test sink handler with failed phase and no hooks configured."""
    logger.info("=== test_failed_phase_no_hooks ===")

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-message-abc", phase="failed")
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]
    from asya_crew.sink import sink_handler

    result = sink_handler({})

    assert result == {}

    logger.info("=== test_failed_phase_no_hooks: PASSED ===")


def test_non_terminal_phase_accepted(tmp_path, monkeypatch):
    """Test sink handler accepts any status.phase (not just 'succeeded'/'failed')."""
    logger.info("=== test_non_terminal_phase_accepted ===")

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-message", phase="processing")
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]
    from asya_crew.sink import sink_handler

    result = sink_handler({})
    assert result == {}

    logger.info("=== test_non_terminal_phase_accepted: PASSED ===")


def test_fan_out_child_skips_hooks(tmp_path, monkeypatch):
    """Fire-and-forget fan-out child: parent_id set -> skip hooks, return payload."""
    logger.info("=== test_fan_out_child_skips_hooks ===")

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-fanout-child", phase="succeeded", parent_id="test-parent")
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)
    monkeypatch.setenv("ASYA_SINK_HOOKS", "checkpoint-s3")

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]
    from asya_crew.sink import sink_handler

    result = sink_handler({"result": 1})

    with open(os.path.join(vfs_root, "route", "next")) as f:
        next_file = f.read()
    assert next_file == ""
    assert result == {"result": 1}

    logger.info("=== test_fan_out_child_skips_hooks: PASSED ===")


def test_fan_out_child_runs_hooks_when_enabled(tmp_path, monkeypatch):
    """Fire-and-forget fan-out child: ASYA_SINK_FANOUT_HOOKS=true -> run hooks."""
    logger.info("=== test_fan_out_child_runs_hooks_when_enabled ===")

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-fanout-hooks", phase="succeeded", parent_id="test-parent")
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)
    monkeypatch.setenv("ASYA_SINK_HOOKS", "checkpoint-s3")
    monkeypatch.setenv("ASYA_SINK_FANOUT_HOOKS", "true")

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]
    from asya_crew.sink import sink_handler

    result = sink_handler({"result": 1})

    with open(os.path.join(vfs_root, "route", "next")) as f:
        next_file = f.read()
    assert next_file == "checkpoint-s3"
    assert result == {"result": 1}

    logger.info("=== test_fan_out_child_runs_hooks_when_enabled: PASSED ===")


def test_fan_in_partial_runs_hooks(tmp_path, monkeypatch):
    """Fan-in partial: x-asya-fan-in header -> always run hooks."""
    logger.info("=== test_fan_in_partial_runs_hooks ===")

    vfs_root = setup_vfs(
        str(tmp_path),
        msg_id="test-fanin",
        phase="partial",
        headers={"x-asya-fan-in": "aggregator"},
    )
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)
    monkeypatch.setenv("ASYA_SINK_HOOKS", "checkpoint-s3")

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]
    from asya_crew.sink import sink_handler

    result = sink_handler({"shard": 1})

    with open(os.path.join(vfs_root, "route", "next")) as f:
        next_file = f.read()
    assert next_file == "checkpoint-s3"
    assert result == {"shard": 1}

    logger.info("=== test_fan_in_partial_runs_hooks: PASSED ===")
