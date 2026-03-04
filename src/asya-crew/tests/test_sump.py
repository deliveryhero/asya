#!/usr/bin/env python3
"""
Unit tests for sump handler.

Tests the x-sump actor which handles final termination,
logging errors and emitting metrics via ABI yield protocol.
"""

import copy
import logging
import os
import sys

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def make_metadata(msg_id="test-001", phase="succeeded", parent_id="", headers=None):
    """Create ABI metadata dict for testing."""
    return {
        "id": msg_id,
        "parent_id": parent_id,
        "route": {
            "prev": [],
            "curr": "x-sump",
            "next": [],
        },
        "headers": headers or {},
        "status": {"phase": phase} if phase else {},
    }


def drive_abi(gen, metadata):
    """Drive an ABI generator handler, simulating the runtime's _drive_generator."""
    meta = copy.deepcopy(metadata)
    frames = []
    send_val = None

    while True:
        try:
            yielded = gen.send(send_val)
        except StopIteration:
            break

        send_val = None

        if yielded is None:
            continue
        elif isinstance(yielded, dict):
            frames.append(yielded)
        elif isinstance(yielded, tuple):
            verb = yielded[0]
            if verb == "GET":
                send_val = _resolve_path(meta, yielded[1])
            elif verb == "SET" and len(yielded) >= 3:
                _set_path(meta, yielded[1], yielded[2])

    return frames, meta


def _resolve_path(data, path):
    """Resolve a dotted ABI path against a metadata dict."""
    parts = path.lstrip(".").split(".")
    current = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    if isinstance(current, dict | list):
        return copy.deepcopy(current)
    return current


def _set_path(data, path, value):
    """Set a value at a dotted ABI path in a metadata dict."""
    parts = path.lstrip(".").split(".")
    current = data
    for part in parts[:-1]:
        current = current[part]
    current[parts[-1]] = value


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    """Set up test environment before each test."""
    monkeypatch.delenv("ASYA_PERSISTENCE_MOUNT", raising=False)

    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]

    yield

    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]


def test_succeeded_phase_returns_no_frames(monkeypatch, caplog):
    """Test sump handler with succeeded phase emits no frames with debug log."""
    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]
    from asya_crew.sump import sump_handler

    metadata = make_metadata(msg_id="test-message-123", phase="succeeded")
    with caplog.at_level(logging.DEBUG):
        frames, _ = drive_abi(sump_handler({"result": 42}), metadata)

    assert len(frames) == 0
    assert "Terminal success for message test-message-123" in caplog.text


def test_failed_phase_returns_no_frames_logs_error(monkeypatch, caplog):
    """Test sump handler with failed phase emits no frames and logs at ERROR level."""
    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]
    from asya_crew.sump import sump_handler

    metadata = make_metadata(msg_id="test-message-456", phase="failed")
    with caplog.at_level(logging.ERROR):
        frames, _ = drive_abi(sump_handler({"data": "test"}), metadata)

    assert len(frames) == 0
    assert "Terminal failure for message test-message-456" in caplog.text


def test_non_terminal_phase_logs_info(monkeypatch, caplog):
    """Non-terminal phase (not succeeded/failed) is logged at INFO level."""
    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]
    from asya_crew.sump import sump_handler

    metadata = make_metadata(msg_id="test-nonterminal", phase="awaiting_approval")
    with caplog.at_level(logging.INFO):
        frames, _ = drive_abi(sump_handler({"data": "test"}), metadata)

    assert len(frames) == 0
    assert "non-final phase" in caplog.text
    assert "awaiting_approval" in caplog.text


def test_missing_phase(monkeypatch, caplog):
    """Test sump handler when status.phase is absent (graceful handling)."""
    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]
    from asya_crew.sump import sump_handler

    metadata = make_metadata(msg_id="test-no-phase", phase=None)
    with caplog.at_level(logging.INFO):
        frames, _ = drive_abi(sump_handler({"data": "test"}), metadata)

    assert len(frames) == 0
