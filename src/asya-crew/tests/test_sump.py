#!/usr/bin/env python3
"""
Unit tests for sump handler.

Tests the x-sump actor which handles final termination,
logging errors and emitting metrics via ABI yield protocol.

The sump handler is a generator driven via the ABI yield protocol:
- yield ("GET", ".id") -> runtime sends back the message UUID
- yield ("GET", ".status") -> runtime sends back the status dict
- yield ("GET", ".route") -> runtime sends back the route dict
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
    phase: str = "succeeded",
    route_prev: list[str] | None = None,
    route_curr: str = "",
    route_next: list[str] | None = None,
) -> dict:
    """Build an ABI context dict for driving the sump generator."""
    return {
        "id": msg_id,
        "status": {"phase": phase} if phase else {},
        "route": {
            "prev": route_prev or [],
            "curr": route_curr,
            "next": route_next or [],
        },
    }


def drive_sump(payload: dict, ctx: dict) -> tuple[dict | None, list[tuple]]:
    """Drive the sump generator with ABI protocol simulation.

    Returns (emitted_payload, abi_commands) where abi_commands is a list of
    ABI tuples yielded by the generator (GET verbs).
    """
    from asya_crew.sump import sump_handler

    gen = sump_handler(payload)

    emitted_payload = None
    abi_commands: list[tuple] = []

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
    monkeypatch.delenv("ASYA_PERSISTENCE_MOUNT", raising=False)

    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]

    yield

    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]


def test_succeeded_phase_returns_payload(caplog):
    """Test sump handler with succeeded phase yields payload with debug log."""
    ctx = make_abi_context(msg_id="test-message-123", phase="succeeded")

    with caplog.at_level(logging.DEBUG):
        result, _ = drive_sump({"result": 42}, ctx)

    assert result == {"result": 42}
    assert "Terminal success for message test-message-123" in caplog.text


def test_failed_phase_returns_payload_logs_error(caplog):
    """Test sump handler with failed phase yields payload and logs at ERROR level."""
    ctx = make_abi_context(msg_id="test-message-456", phase="failed")

    with caplog.at_level(logging.ERROR):
        result, _ = drive_sump({"data": "test"}, ctx)

    assert result == {"data": "test"}
    assert "Terminal failure for message test-message-456" in caplog.text


def test_non_terminal_phase_logs_info(caplog):
    """Non-terminal phase (not succeeded/failed) is logged at INFO level."""
    ctx = make_abi_context(msg_id="test-nonterminal", phase="awaiting_approval")

    with caplog.at_level(logging.INFO):
        result, _ = drive_sump({"data": "test"}, ctx)

    assert result == {"data": "test"}
    assert "non-final phase" in caplog.text
    assert "awaiting_approval" in caplog.text


def test_missing_phase_defaults_to_unknown(caplog):
    """Test sump handler when status has no phase key defaults to 'unknown'."""
    ctx = make_abi_context(msg_id="test-no-phase", phase="")

    with caplog.at_level(logging.INFO):
        result, _ = drive_sump({"data": "test"}, ctx)

    assert result == {"data": "test"}


def test_persistence_calls_checkpointer(tmp_path, monkeypatch):
    """When ASYA_PERSISTENCE_MOUNT is set, sump calls checkpointer."""
    mount_path = str(tmp_path / "checkpoints")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.sump" in sys.modules:
        del sys.modules["asya_crew.sump"]
    if "asya_crew.checkpointer" in sys.modules:
        del sys.modules["asya_crew.checkpointer"]

    ctx = make_abi_context(
        msg_id="test-persist",
        phase="failed",
        route_prev=["actor-a", "actor-b"],
        route_curr="x-sump",
    )
    result, abi_commands = drive_sump({"error": "something failed"}, ctx)

    assert result == {"error": "something failed"}
    get_paths = [c[1] for c in abi_commands if c[0] == "GET"]
    assert ".route" in get_paths

    json_files = []
    for dirpath, _, filenames in os.walk(mount_path):
        for f in filenames:
            if f.endswith(".json"):
                json_files.append(os.path.join(dirpath, f))
    assert len(json_files) == 1
