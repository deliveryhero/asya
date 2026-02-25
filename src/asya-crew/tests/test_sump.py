#!/usr/bin/env python3
"""
Unit tests for sump handler.

Tests the x-sump actor which handles final termination,
logging errors and emitting metrics via VFS metadata.
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
        f.write("x-sump")
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
    monkeypatch.delenv("ASYA_PERSISTENCE_MOUNT", raising=False)

    vfs_root = setup_vfs(str(tmp_path))
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]

    yield vfs_root

    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]


def test_succeeded_phase_returns_none(tmp_path, monkeypatch, caplog):
    """Test sump handler with succeeded phase returns None with debug log."""
    logger.info("=== test_succeeded_phase_returns_none ===")

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-message-123", phase="succeeded")
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]
    from asya_crew.sump import sump_handler

    with caplog.at_level(logging.DEBUG):
        sump_handler({"result": 42})

    assert "Terminal success for message test-message-123" in caplog.text

    logger.info("=== test_succeeded_phase_returns_none: PASSED ===")


def test_failed_phase_returns_none_logs_error(tmp_path, monkeypatch, caplog):
    """Test sump handler with failed phase returns None and logs at ERROR level."""
    logger.info("=== test_failed_phase_returns_none_logs_error ===")

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-message-456", phase="failed")
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]
    from asya_crew.sump import sump_handler

    with caplog.at_level(logging.ERROR):
        sump_handler({"data": "test"})

    assert "Terminal failure for message test-message-456" in caplog.text

    logger.info("=== test_failed_phase_returns_none_logs_error: PASSED ===")


def test_non_terminal_phase_logs_info(tmp_path, monkeypatch, caplog):
    """Non-terminal phase (not succeeded/failed) is logged at INFO level."""
    logger.info("=== test_non_terminal_phase_logs_info ===")

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-nonterminal", phase="awaiting_approval")
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]
    from asya_crew.sump import sump_handler

    with caplog.at_level(logging.INFO):
        sump_handler({"data": "test"})

    assert "non-final phase" in caplog.text
    assert "awaiting_approval" in caplog.text

    logger.info("=== test_non_terminal_phase_logs_info: PASSED ===")


def test_missing_phase_vfs(tmp_path, monkeypatch, caplog):
    """Test sump handler when status/phase file is absent (graceful handling)."""
    logger.info("=== test_missing_phase_vfs ===")

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-no-phase", phase=None)
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]
    from asya_crew.sump import sump_handler

    with caplog.at_level(logging.INFO):
        sump_handler({"data": "test"})

    logger.info("=== test_missing_phase_vfs: PASSED ===")
