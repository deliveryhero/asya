#!/usr/bin/env python3
"""
Unit tests for sink handler.

Tests the x-sink actor which handles first-layer termination,
routing to configurable hooks and reporting status via ABI yield protocol.
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
            "curr": "x-sink",
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
    for key in ["ASYA_SINK_HOOKS", "ASYA_SINK_FANOUT_HOOKS", "ASYA_PERSISTENCE_MOUNT"]:
        monkeypatch.delenv(key, raising=False)

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]

    yield

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]


def test_succeeded_phase_with_hooks(monkeypatch):
    """Test sink handler with succeeded phase and hooks configured."""
    monkeypatch.setenv("ASYA_SINK_HOOKS", "checkpoint-s3,notify-slack")

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]
    from asya_crew.sink import sink_handler

    metadata = make_metadata(msg_id="test-message-123", phase="succeeded")
    frames, meta = drive_abi(sink_handler({"result": 42}), metadata)

    assert meta["route"]["next"] == ["checkpoint-s3", "notify-slack"]
    assert len(frames) == 1
    assert frames[0] == {"result": 42}


def test_failed_phase_with_hooks(monkeypatch):
    """Test sink handler with failed phase and hooks configured."""
    monkeypatch.setenv("ASYA_SINK_HOOKS", "checkpoint-s3")

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]
    from asya_crew.sink import sink_handler

    metadata = make_metadata(msg_id="test-message-456", phase="failed")
    frames, meta = drive_abi(sink_handler({}), metadata)

    assert meta["route"]["next"] == ["checkpoint-s3"]
    assert len(frames) == 1
    assert frames[0] == {}


def test_succeeded_phase_no_hooks(monkeypatch):
    """Test sink handler with succeeded phase and no hooks configured."""
    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]
    from asya_crew.sink import sink_handler

    metadata = make_metadata(msg_id="test-message-789", phase="succeeded")
    frames, meta = drive_abi(sink_handler({"result": 100}), metadata)

    assert len(frames) == 1
    assert frames[0] == {"result": 100}


def test_failed_phase_no_hooks(monkeypatch):
    """Test sink handler with failed phase and no hooks configured."""
    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]
    from asya_crew.sink import sink_handler

    metadata = make_metadata(msg_id="test-message-abc", phase="failed")
    frames, meta = drive_abi(sink_handler({}), metadata)

    assert len(frames) == 1
    assert frames[0] == {}


def test_non_terminal_phase_accepted(monkeypatch):
    """Test sink handler accepts any status.phase (not just 'succeeded'/'failed')."""
    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]
    from asya_crew.sink import sink_handler

    metadata = make_metadata(msg_id="test-message", phase="processing")
    frames, _ = drive_abi(sink_handler({}), metadata)

    assert len(frames) == 1
    assert frames[0] == {}


def test_fan_out_child_skips_hooks(monkeypatch):
    """Fire-and-forget fan-out child: parent_id set -> skip hooks, return payload."""
    monkeypatch.setenv("ASYA_SINK_HOOKS", "checkpoint-s3")

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]
    from asya_crew.sink import sink_handler

    metadata = make_metadata(msg_id="test-fanout-child", phase="succeeded", parent_id="test-parent")
    frames, meta = drive_abi(sink_handler({"result": 1}), metadata)

    assert meta["route"]["next"] == []
    assert len(frames) == 1
    assert frames[0] == {"result": 1}


def test_fan_out_child_runs_hooks_when_enabled(monkeypatch):
    """Fire-and-forget fan-out child: ASYA_SINK_FANOUT_HOOKS=true -> run hooks."""
    monkeypatch.setenv("ASYA_SINK_HOOKS", "checkpoint-s3")
    monkeypatch.setenv("ASYA_SINK_FANOUT_HOOKS", "true")

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]
    from asya_crew.sink import sink_handler

    metadata = make_metadata(msg_id="test-fanout-hooks", phase="succeeded", parent_id="test-parent")
    frames, meta = drive_abi(sink_handler({"result": 1}), metadata)

    assert meta["route"]["next"] == ["checkpoint-s3"]
    assert len(frames) == 1
    assert frames[0] == {"result": 1}


def test_fan_in_partial_runs_hooks(monkeypatch):
    """Fan-in partial: x-asya-fan-in header -> always run hooks."""
    monkeypatch.setenv("ASYA_SINK_HOOKS", "checkpoint-s3")

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]
    from asya_crew.sink import sink_handler

    metadata = make_metadata(
        msg_id="test-fanin",
        phase="partial",
        headers={"x-asya-fan-in": "aggregator"},
    )
    frames, meta = drive_abi(sink_handler({"shard": 1}), metadata)

    assert meta["route"]["next"] == ["checkpoint-s3"]
    assert len(frames) == 1
    assert frames[0] == {"shard": 1}
