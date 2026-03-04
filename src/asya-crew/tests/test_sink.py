#!/usr/bin/env python3
"""
Unit tests for sink handler.

Tests the x-sink actor which handles first-layer termination,
routing to configurable hooks and reporting status via ABI protocol.

The sink handler is a generator driven via the ABI yield protocol:
- yield ("GET", ".id") -> runtime sends back the message UUID
- yield ("GET", ".parent_id") -> runtime sends back the parent UUID
- yield ("GET", ".status") -> runtime sends back the status dict
- yield ("GET", ".headers") -> runtime sends back the headers dict
- yield ("GET", ".route") -> runtime sends back the route dict
- yield ("SET", ".route.next", [...]) -> runtime sets next routing
- yield payload -> emitted as a downstream frame
"""

import logging
import os
import sys

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def make_abi_context(
    msg_id: str = "test-001",
    parent_id: str = "",
    phase: str = "succeeded",
    headers: dict | None = None,
    route_prev: list[str] | None = None,
    route_curr: str = "",
    route_next: list[str] | None = None,
) -> dict:
    """Build an ABI context dict for driving the sink generator."""
    return {
        "id": msg_id,
        "parent_id": parent_id,
        "status": {"phase": phase} if phase else {},
        "headers": headers or {},
        "route": {
            "prev": route_prev or [],
            "curr": route_curr,
            "next": route_next or [],
        },
    }


def drive_sink(payload: dict, ctx: dict) -> tuple[dict | None, list[tuple]]:
    """Drive the sink generator with ABI protocol simulation.

    Returns (emitted_payload, abi_commands) where abi_commands is a list of
    ABI tuples yielded by the generator (GET, SET, DEL verbs).
    """
    from asya_crew.sink import sink_handler

    gen = sink_handler(payload)

    emitted_payload = None
    abi_commands: list[tuple[str, ...]] = []

    # Map ABI GET paths to context values
    def resolve_get(path: str) -> object:
        parts = path.lstrip(".").split(".", 1)
        root = parts[0]
        return ctx.get(root)

    try:
        yielded = next(gen)
        while True:
            if isinstance(yielded, dict):
                emitted_payload = yielded
                yielded = next(gen)
            elif isinstance(yielded, tuple):
                abi_commands.append(yielded)
                verb = yielded[0]
                if verb == "GET":
                    send_val = resolve_get(yielded[1])
                    yielded = gen.send(send_val)
                elif verb == "SET":
                    # Apply SET to context for assertions
                    if yielded[1] == ".route.next" and len(yielded) >= 3:
                        ctx["route"]["next"] = yielded[2]
                    yielded = next(gen)
                else:
                    yielded = next(gen)
            else:
                raise RuntimeError(f"Unexpected yield: {yielded}")
    except StopIteration:
        pass

    return emitted_payload, abi_commands


@pytest.fixture(autouse=True)
def clean_module_cache(monkeypatch):
    """Clean module cache and env vars before each test."""
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

    ctx = make_abi_context(msg_id="test-message-123", phase="succeeded")
    result, abi_commands = drive_sink({"result": 42}, ctx)

    assert result == {"result": 42}
    assert ("SET", ".route.next", ["checkpoint-s3", "notify-slack"]) in abi_commands
    assert ctx["route"]["next"] == ["checkpoint-s3", "notify-slack"]


def test_failed_phase_with_hooks(monkeypatch):
    """Test sink handler with failed phase and hooks configured."""
    monkeypatch.setenv("ASYA_SINK_HOOKS", "checkpoint-s3")

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]

    ctx = make_abi_context(msg_id="test-message-456", phase="failed")
    result, abi_commands = drive_sink({}, ctx)

    assert result == {}
    assert ("SET", ".route.next", ["checkpoint-s3"]) in abi_commands


def test_succeeded_phase_no_hooks(monkeypatch):
    """Test sink handler with succeeded phase and no hooks configured."""
    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]

    ctx = make_abi_context(msg_id="test-message-789", phase="succeeded")
    result, abi_commands = drive_sink({"result": 100}, ctx)

    assert result == {"result": 100}
    # No SET commands should be issued when no hooks configured
    set_commands = [c for c in abi_commands if c[0] == "SET"]
    assert len(set_commands) == 0


def test_failed_phase_no_hooks(monkeypatch):
    """Test sink handler with failed phase and no hooks configured."""
    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]

    ctx = make_abi_context(msg_id="test-message-abc", phase="failed")
    result, abi_commands = drive_sink({}, ctx)

    assert result == {}
    set_commands = [c for c in abi_commands if c[0] == "SET"]
    assert len(set_commands) == 0


def test_non_terminal_phase_accepted(monkeypatch):
    """Test sink handler accepts any status.phase (not just 'succeeded'/'failed')."""
    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]

    ctx = make_abi_context(msg_id="test-message", phase="processing")
    result, _ = drive_sink({}, ctx)
    assert result == {}


def test_fan_out_child_skips_hooks(monkeypatch):
    """Fire-and-forget fan-out child: parent_id set -> skip hooks, return payload."""
    monkeypatch.setenv("ASYA_SINK_HOOKS", "checkpoint-s3")

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]

    ctx = make_abi_context(msg_id="test-fanout-child", phase="succeeded", parent_id="test-parent")
    result, abi_commands = drive_sink({"result": 1}, ctx)

    assert result == {"result": 1}
    # No SET to route.next — hooks skipped for fan-out children
    set_commands = [c for c in abi_commands if c[0] == "SET"]
    assert len(set_commands) == 0


def test_fan_out_child_runs_hooks_when_enabled(monkeypatch):
    """Fire-and-forget fan-out child: ASYA_SINK_FANOUT_HOOKS=true -> run hooks."""
    monkeypatch.setenv("ASYA_SINK_HOOKS", "checkpoint-s3")
    monkeypatch.setenv("ASYA_SINK_FANOUT_HOOKS", "true")

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]

    ctx = make_abi_context(msg_id="test-fanout-hooks", phase="succeeded", parent_id="test-parent")
    result, abi_commands = drive_sink({"result": 1}, ctx)

    assert result == {"result": 1}
    assert ("SET", ".route.next", ["checkpoint-s3"]) in abi_commands


def test_fan_in_partial_suppressed(monkeypatch):
    """Fan-in partial: x-asya-fan-in header -> silently consumed, no checkpoint or hooks."""
    monkeypatch.setenv("ASYA_SINK_HOOKS", "checkpoint-s3")

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]

    ctx = make_abi_context(
        msg_id="test-fanin",
        phase="partial",
        headers={"x-asya-fan-in": "aggregator"},
    )
    result, abi_commands = drive_sink({"shard": 1}, ctx)

    # Fan-in partials produce 0 frames (silently consumed)
    assert result is None
    # No SET commands (no hooks, no routing)
    set_commands = [c for c in abi_commands if c[0] == "SET"]
    assert len(set_commands) == 0


def test_missing_phase_defaults_to_unknown(monkeypatch):
    """When status has no 'phase' key, defaults to 'unknown'."""
    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]

    ctx = make_abi_context(msg_id="test-no-phase", phase="")
    result, _ = drive_sink({"data": "test"}, ctx)
    assert result == {"data": "test"}


def test_persistence_calls_checkpointer(tmp_path, monkeypatch):
    """When ASYA_PERSISTENCE_MOUNT is set, sink calls checkpointer."""
    mount_path = str(tmp_path / "checkpoints")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]
    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]

    ctx = make_abi_context(
        msg_id="test-persist",
        phase="succeeded",
        route_prev=["actor-a", "actor-b"],
        route_curr="",
    )
    result, abi_commands = drive_sink({"result": 42}, ctx)

    assert result == {"result": 42}
    # Should have read .route for checkpointer
    get_paths = [c[1] for c in abi_commands if c[0] == "GET"]
    assert ".route" in get_paths

    # Verify file was written with envelope message_id in filename
    json_files = []
    for dirpath, _, filenames in os.walk(mount_path):
        for f in filenames:
            if f.endswith(".json"):
                json_files.append(os.path.join(dirpath, f))
    assert len(json_files) == 1
    assert "test-persist" in json_files[0]


def test_persistence_uses_origin_id_when_present(tmp_path, monkeypatch):
    """When x-asya-origin-id header is set, checkpointer uses it as filename."""
    mount_path = str(tmp_path / "checkpoints")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]
    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]

    ctx = make_abi_context(
        msg_id="child-envelope-id",
        phase="succeeded",
        route_prev=["aggregator", "summarizer"],
        route_curr="",
        headers={"x-asya-origin-id": "original-task-id"},
    )
    result, _ = drive_sink({"result": "merged"}, ctx)

    assert result == {"result": "merged"}

    # Verify file uses origin-id (not child envelope ID) in filename
    json_files = []
    for dirpath, _, filenames in os.walk(mount_path):
        for f in filenames:
            if f.endswith(".json"):
                json_files.append(os.path.join(dirpath, f))
    assert len(json_files) == 1
    assert "original-task-id" in json_files[0]
    assert "child-envelope-id" not in json_files[0]


def test_fan_in_partial_skips_persistence(tmp_path, monkeypatch):
    """Fan-in partials skip checkpoint even when ASYA_PERSISTENCE_MOUNT is set."""
    mount_path = str(tmp_path / "checkpoints")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.sink" in sys.modules:
        del sys.modules["asya_crew.sink"]
    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]

    ctx = make_abi_context(
        msg_id="test-fanin-persist",
        phase="partial",
        headers={"x-asya-fan-in": {"origin_id": "abc", "slice_index": 0}},
    )
    result, _ = drive_sink({"shard": 1}, ctx)

    # Silently consumed
    assert result is None

    # No checkpoint file written
    json_files = []
    for dirpath, _, filenames in os.walk(mount_path):
        for f in filenames:
            if f.endswith(".json"):
                json_files.append(os.path.join(dirpath, f))
    assert len(json_files) == 0
