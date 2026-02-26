#!/usr/bin/env python3
"""
Unit tests for x-pause crew actor.

Tests the pause handler which persists paused messages via state proxy file I/O.
Reads message metadata from VFS at ASYA_MSG_ROOT, ensures x-resume is in route.next,
writes complete messages as JSON files to ASYA_PERSISTENCE_MOUNT, and signals pause
via x-asya-pause header.
"""

import json
import logging
import os
import sys

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def setup_vfs(
    tmpdir,
    msg_id="test-001",
    prev_actors=None,
    curr="x-pause",
    next_actors=None,
    parent_id="",
    headers=None,
):
    """Create VFS directory structure for testing."""
    os.makedirs(os.path.join(tmpdir, "route"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, "headers"), exist_ok=True)

    with open(os.path.join(tmpdir, "id"), "w") as f:
        f.write(msg_id)
    with open(os.path.join(tmpdir, "parent_id"), "w") as f:
        f.write(parent_id)
    with open(os.path.join(tmpdir, "route", "prev"), "w") as f:
        f.write("\n".join(prev_actors) if prev_actors else "")
    with open(os.path.join(tmpdir, "route", "curr"), "w") as f:
        f.write(curr)
    with open(os.path.join(tmpdir, "route", "next"), "w") as f:
        f.write("\n".join(next_actors) if next_actors else "")

    # Write headers if provided
    if headers:
        for header_name, header_value in headers.items():
            header_path = os.path.join(tmpdir, "headers", header_name)
            with open(header_path, "w") as f:
                if isinstance(header_value, dict | list):
                    f.write(json.dumps(header_value))
                else:
                    f.write(str(header_value))

    return tmpdir


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, monkeypatch):
    """Set up test environment before each test."""
    monkeypatch.delenv("ASYA_PERSISTENCE_MOUNT", raising=False)
    monkeypatch.delenv("ASYA_PAUSE_METADATA", raising=False)

    vfs_root = setup_vfs(str(tmp_path))
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.pause" in sys.modules:
        del sys.modules["asya_crew.pause"]

    yield vfs_root

    if "asya_crew.pause" in sys.modules:
        del sys.modules["asya_crew.pause"]


def test_persists_message_with_paused_prefix(tmp_path, monkeypatch):
    """Test pause handler writes to paused/{msg_id}.json."""
    logger.info("=== test_persists_message_with_paused_prefix ===")

    vfs_root = setup_vfs(
        str(tmp_path),
        msg_id="test-pause-123",
        prev_actors=["actor-a"],
        curr="x-pause",
        next_actors=["actor-b"],
    )
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    mount_path = str(tmp_path / "state")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.pause" in sys.modules:
        del sys.modules["asya_crew.pause"]
    from asya_crew.pause import pause_handler

    pause_handler({"data": "test"})

    expected_file = os.path.join(mount_path, "paused", "test-pause-123.json")
    assert os.path.isfile(expected_file)

    with open(expected_file) as f:
        message = json.load(f)
    assert message["id"] == "test-pause-123"

    logger.info("=== test_persists_message_with_paused_prefix: PASSED ===")


def test_prepends_x_resume_when_missing(tmp_path, monkeypatch):
    """Test pause handler prepends x-resume to route.next when missing."""
    logger.info("=== test_prepends_x_resume_when_missing ===")

    vfs_root = setup_vfs(
        str(tmp_path),
        msg_id="test-resume-prepend",
        curr="x-pause",
        next_actors=["actor-b", "actor-c"],
    )
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    mount_path = str(tmp_path / "state")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.pause" in sys.modules:
        del sys.modules["asya_crew.pause"]
    from asya_crew.pause import pause_handler

    pause_handler({"data": "test"})

    # Read route/next from VFS
    with open(os.path.join(vfs_root, "route", "next")) as f:
        next_actors = f.read().strip().splitlines()

    assert next_actors == ["x-resume", "actor-b", "actor-c"]

    # Verify persisted message also has updated route
    expected_file = os.path.join(mount_path, "paused", "test-resume-prepend.json")
    with open(expected_file) as f:
        message = json.load(f)
    assert message["route"]["next"] == ["x-resume", "actor-b", "actor-c"]

    logger.info("=== test_prepends_x_resume_when_missing: PASSED ===")


def test_preserves_route_when_x_resume_present(tmp_path, monkeypatch):
    """Test pause handler does not modify route.next when x-resume is already first."""
    logger.info("=== test_preserves_route_when_x_resume_present ===")

    vfs_root = setup_vfs(
        str(tmp_path),
        msg_id="test-resume-present",
        curr="x-pause",
        next_actors=["x-resume", "actor-b", "actor-c"],
    )
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    mount_path = str(tmp_path / "state")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.pause" in sys.modules:
        del sys.modules["asya_crew.pause"]
    from asya_crew.pause import pause_handler

    pause_handler({"data": "test"})

    # Read route/next from VFS
    with open(os.path.join(vfs_root, "route", "next")) as f:
        next_actors = f.read().strip().splitlines()

    assert next_actors == ["x-resume", "actor-b", "actor-c"]

    # Verify persisted message has unchanged route
    expected_file = os.path.join(mount_path, "paused", "test-resume-present.json")
    with open(expected_file) as f:
        message = json.load(f)
    assert message["route"]["next"] == ["x-resume", "actor-b", "actor-c"]

    logger.info("=== test_preserves_route_when_x_resume_present: PASSED ===")


def test_sets_x_asya_pause_header(tmp_path, monkeypatch):
    """Test pause handler writes x-asya-pause header with metadata JSON."""
    logger.info("=== test_sets_x_asya_pause_header ===")

    vfs_root = setup_vfs(
        str(tmp_path),
        msg_id="test-header",
        curr="x-pause",
        next_actors=["actor-b"],
    )
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.pause" in sys.modules:
        del sys.modules["asya_crew.pause"]
    from asya_crew.pause import pause_handler

    pause_handler({"data": "test"})

    # Read x-asya-pause header from VFS
    header_path = os.path.join(vfs_root, "headers", "x-asya-pause")
    assert os.path.isfile(header_path)

    with open(header_path) as f:
        header_content = json.load(f)

    assert header_content["prompt"] == "Task paused"
    assert header_content["fields"] == []

    logger.info("=== test_sets_x_asya_pause_header: PASSED ===")


def test_returns_none(tmp_path, monkeypatch):
    """Test pause handler returns None."""
    logger.info("=== test_returns_none ===")

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-none", curr="x-pause")
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.pause" in sys.modules:
        del sys.modules["asya_crew.pause"]
    from asya_crew.pause import pause_handler

    pause_handler({"data": "test"})

    logger.info("=== test_returns_none: PASSED ===")


def test_custom_pause_metadata_from_env(tmp_path, monkeypatch):
    """Test pause handler uses ASYA_PAUSE_METADATA env var for header content."""
    logger.info("=== test_custom_pause_metadata_from_env ===")

    custom_metadata = {
        "prompt": "Please provide additional information",
        "fields": [
            {"name": "user_id", "type": "string", "required": True},
            {"name": "comment", "type": "text", "required": False},
        ],
    }

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-custom-meta", curr="x-pause")
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)
    monkeypatch.setenv("ASYA_PAUSE_METADATA", json.dumps(custom_metadata))

    mount_path = str(tmp_path / "state")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.pause" in sys.modules:
        del sys.modules["asya_crew.pause"]
    from asya_crew.pause import pause_handler

    pause_handler({"data": "test"})

    # Check x-asya-pause header
    header_path = os.path.join(vfs_root, "headers", "x-asya-pause")
    with open(header_path) as f:
        header_content = json.load(f)

    assert header_content == custom_metadata

    # Check persisted message _pause_metadata
    expected_file = os.path.join(mount_path, "paused", "test-custom-meta.json")
    with open(expected_file) as f:
        message = json.load(f)
    assert message["_pause_metadata"] == custom_metadata

    logger.info("=== test_custom_pause_metadata_from_env: PASSED ===")


def test_persisted_message_contains_full_state(tmp_path, monkeypatch):
    """Test pause handler persists complete message with id, route, headers, payload, _pause_metadata."""
    logger.info("=== test_persisted_message_contains_full_state ===")

    vfs_root = setup_vfs(
        str(tmp_path),
        msg_id="test-full-state",
        prev_actors=["actor-a", "actor-b"],
        curr="x-pause",
        next_actors=["actor-c"],
        parent_id="parent-123",
        headers={
            "trace-id": "trace-456",
            "priority": json.dumps({"level": "high"}),
        },
    )
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    mount_path = str(tmp_path / "state")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.pause" in sys.modules:
        del sys.modules["asya_crew.pause"]
    from asya_crew.pause import pause_handler

    pause_handler({"result": 42, "nested": {"key": "value"}})

    expected_file = os.path.join(mount_path, "paused", "test-full-state.json")
    with open(expected_file) as f:
        message = json.load(f)

    assert message["id"] == "test-full-state"
    assert message["parent_id"] == "parent-123"
    assert message["route"]["prev"] == ["actor-a", "actor-b"]
    assert message["route"]["curr"] == "x-pause"
    assert message["route"]["next"] == ["x-resume", "actor-c"]  # x-resume prepended
    assert message["headers"]["trace-id"] == "trace-456"
    assert message["headers"]["priority"] == {"level": "high"}
    assert message["payload"] == {"result": 42, "nested": {"key": "value"}}
    assert "_pause_metadata" in message
    assert message["_pause_metadata"]["prompt"] == "Task paused"

    logger.info("=== test_persisted_message_contains_full_state: PASSED ===")


def test_skips_persistence_when_mount_not_configured(tmp_path, monkeypatch):
    """Test pause handler skips file write when ASYA_PERSISTENCE_MOUNT not set but still sets header."""
    logger.info("=== test_skips_persistence_when_mount_not_configured ===")

    vfs_root = setup_vfs(str(tmp_path), msg_id="test-no-mount", curr="x-pause")
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.pause" in sys.modules:
        del sys.modules["asya_crew.pause"]
    from asya_crew.pause import pause_handler

    pause_handler({"data": "test"})

    # No file should be written
    files = _find_json_files(str(tmp_path))
    assert len(files) == 0

    # But x-asya-pause header should still be set
    header_path = os.path.join(vfs_root, "headers", "x-asya-pause")
    assert os.path.isfile(header_path)

    logger.info("=== test_skips_persistence_when_mount_not_configured: PASSED ===")


def test_skips_transient_headers(tmp_path, monkeypatch):
    """Test pause handler excludes transient headers from persisted message."""
    logger.info("=== test_skips_transient_headers ===")

    vfs_root = setup_vfs(
        str(tmp_path),
        msg_id="test-transient",
        curr="x-pause",
        headers={
            "trace-id": "trace-789",
            "x-asya-fan-in": "transient-value-1",
            "x-asya-route-override": "transient-value-2",
            "x-asya-route-resolved": "transient-value-3",
            "x-asya-parent-id": "transient-value-4",
            "custom-header": "keep-this",
        },
    )
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    mount_path = str(tmp_path / "state")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    if "asya_crew.pause" in sys.modules:
        del sys.modules["asya_crew.pause"]
    from asya_crew.pause import pause_handler

    pause_handler({"data": "test"})

    expected_file = os.path.join(mount_path, "paused", "test-transient.json")
    with open(expected_file) as f:
        message = json.load(f)

    # Only non-transient headers should be in persisted message
    assert "trace-id" in message["headers"]
    assert "custom-header" in message["headers"]
    assert "x-asya-fan-in" not in message["headers"]
    assert "x-asya-route-override" not in message["headers"]
    assert "x-asya-route-resolved" not in message["headers"]
    assert "x-asya-parent-id" not in message["headers"]

    logger.info("=== test_skips_transient_headers: PASSED ===")


def _find_json_files(root: str) -> list[str]:
    """Recursively find all .json files under root."""
    result = []
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            if f.endswith(".json"):
                result.append(os.path.join(dirpath, f))
    return result
