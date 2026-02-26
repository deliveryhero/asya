#!/usr/bin/env python3
"""
Unit tests for x-resume crew actor handler.

Tests the resume handler which restores paused messages from state proxy
storage and merges user input to continue execution.
"""

import json
import logging
import os
import sys

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def setup_vfs(tmpdir):
    """Create VFS directory structure for testing."""
    os.makedirs(os.path.join(tmpdir, "route"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, "headers"), exist_ok=True)

    with open(os.path.join(tmpdir, "route", "next"), "w") as f:
        f.write("")

    return tmpdir


def write_persisted_message(mount_path, task_id, payload, route_next, pause_metadata=None, headers=None):
    """Write a persisted message JSON file at {mount_path}/paused/{task_id}.json."""
    os.makedirs(os.path.join(mount_path, "paused"), exist_ok=True)
    msg = {
        "id": task_id,
        "route": {"prev": ["actor-a", "x-pause"], "curr": "x-resume", "next": route_next},
        "headers": headers or {},
        "payload": payload,
        "_pause_metadata": pause_metadata or {"prompt": "Paused", "fields": []},
    }
    path = os.path.join(mount_path, "paused", f"{task_id}.json")
    with open(path, "w") as f:
        json.dump(msg, f)
    return path


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, monkeypatch):
    """Set up test environment before each test."""
    monkeypatch.delenv("ASYA_PERSISTENCE_MOUNT", raising=False)

    vfs_root = setup_vfs(str(tmp_path / "vfs"))
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    if "asya_crew.resume" in sys.modules:
        del sys.modules["asya_crew.resume"]

    yield vfs_root

    if "asya_crew.resume" in sys.modules:
        del sys.modules["asya_crew.resume"]


def test_loads_persisted_message_and_merges(tmp_path, monkeypatch):
    """Test resume handler loads persisted message and merges user input at field paths."""
    logger.info("=== test_loads_persisted_message_and_merges ===")

    vfs_root = setup_vfs(str(tmp_path / "vfs"))
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    mount_path = str(tmp_path / "state")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    task_id = "task-123"
    with open(os.path.join(vfs_root, "headers", "x-asya-resume-task"), "w") as f:
        f.write(task_id)

    pause_metadata = {
        "prompt": "Enter approval",
        "fields": [{"name": "approved", "type": "boolean", "payload_key": "/approved", "required": True}],
    }
    write_persisted_message(
        mount_path, task_id, {"status": "pending"}, ["actor-b", "actor-c"], pause_metadata=pause_metadata
    )

    if "asya_crew.resume" in sys.modules:
        del sys.modules["asya_crew.resume"]
    from asya_crew.resume import resume_handler as handler

    result = handler({"approved": True})

    assert result == {"status": "pending", "approved": True}

    logger.info("=== test_loads_persisted_message_and_merges: PASSED ===")


def test_merge_at_nested_path(tmp_path, monkeypatch):
    """Test resume handler creates nested dict when payload_key is nested."""
    logger.info("=== test_merge_at_nested_path ===")

    vfs_root = setup_vfs(str(tmp_path / "vfs"))
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    mount_path = str(tmp_path / "state")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    task_id = "task-456"
    with open(os.path.join(vfs_root, "headers", "x-asya-resume-task"), "w") as f:
        f.write(task_id)

    pause_metadata = {
        "prompt": "Add review notes",
        "fields": [{"name": "notes", "type": "string", "payload_key": "/review/notes", "required": True}],
    }
    write_persisted_message(mount_path, task_id, {"status": "pending"}, ["actor-b"], pause_metadata=pause_metadata)

    if "asya_crew.resume" in sys.modules:
        del sys.modules["asya_crew.resume"]
    from asya_crew.resume import resume_handler as handler

    result = handler({"notes": "Looks good"})

    assert result == {"status": "pending", "review": {"notes": "Looks good"}}

    logger.info("=== test_merge_at_nested_path: PASSED ===")


def test_shallow_merge_without_field_mappings(tmp_path, monkeypatch):
    """Test resume handler performs shallow merge when no fields in pause metadata."""
    logger.info("=== test_shallow_merge_without_field_mappings ===")

    vfs_root = setup_vfs(str(tmp_path / "vfs"))
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    mount_path = str(tmp_path / "state")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)
    monkeypatch.setenv("ASYA_RESUME_MERGE_MODE", "shallow")

    task_id = "task-789"
    with open(os.path.join(vfs_root, "headers", "x-asya-resume-task"), "w") as f:
        f.write(task_id)

    pause_metadata = {"prompt": "Continue", "fields": []}
    write_persisted_message(
        mount_path, task_id, {"status": "pending", "count": 1}, ["actor-b"], pause_metadata=pause_metadata
    )

    if "asya_crew.resume" in sys.modules:
        del sys.modules["asya_crew.resume"]
    from asya_crew.resume import resume_handler as handler

    result = handler({"approved": True, "count": 5})

    assert result == {"status": "pending", "count": 5, "approved": True}

    logger.info("=== test_shallow_merge_without_field_mappings: PASSED ===")


def test_restores_route_via_vfs(tmp_path, monkeypatch):
    """Test resume handler writes route/next to VFS from persisted message."""
    logger.info("=== test_restores_route_via_vfs ===")

    vfs_root = setup_vfs(str(tmp_path / "vfs"))
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    mount_path = str(tmp_path / "state")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    task_id = "task-route"
    with open(os.path.join(vfs_root, "headers", "x-asya-resume-task"), "w") as f:
        f.write(task_id)

    write_persisted_message(mount_path, task_id, {"data": "test"}, ["actor-b", "actor-c", "actor-d"])

    if "asya_crew.resume" in sys.modules:
        del sys.modules["asya_crew.resume"]
    from asya_crew.resume import resume_handler as handler

    handler({})

    with open(os.path.join(vfs_root, "route", "next")) as f:
        route_next = f.read()

    assert route_next == "actor-b\nactor-c\nactor-d"

    logger.info("=== test_restores_route_via_vfs: PASSED ===")


def test_stamps_deadline_from_timeout_header(tmp_path, monkeypatch):
    """Test resume handler writes x-asya-deadline-at header when x-asya-resume-timeout present."""
    logger.info("=== test_stamps_deadline_from_timeout_header ===")

    vfs_root = setup_vfs(str(tmp_path / "vfs"))
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    mount_path = str(tmp_path / "state")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    task_id = "task-timeout"
    with open(os.path.join(vfs_root, "headers", "x-asya-resume-task"), "w") as f:
        f.write(task_id)
    with open(os.path.join(vfs_root, "headers", "x-asya-resume-timeout"), "w") as f:
        f.write("3600")

    write_persisted_message(mount_path, task_id, {"data": "test"}, ["actor-b"])

    if "asya_crew.resume" in sys.modules:
        del sys.modules["asya_crew.resume"]
    from asya_crew.resume import resume_handler as handler

    handler({})

    deadline_path = os.path.join(vfs_root, "headers", "x-asya-deadline-at")
    assert os.path.exists(deadline_path)

    with open(deadline_path) as f:
        deadline_str = f.read().strip()

    assert deadline_str.endswith("Z")
    assert "T" in deadline_str

    logger.info("=== test_stamps_deadline_from_timeout_header: PASSED ===")


def test_no_deadline_without_timeout_header(tmp_path, monkeypatch):
    """Test resume handler does not write x-asya-deadline-at when x-asya-resume-timeout absent."""
    logger.info("=== test_no_deadline_without_timeout_header ===")

    vfs_root = setup_vfs(str(tmp_path / "vfs"))
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    mount_path = str(tmp_path / "state")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    task_id = "task-no-timeout"
    with open(os.path.join(vfs_root, "headers", "x-asya-resume-task"), "w") as f:
        f.write(task_id)

    write_persisted_message(mount_path, task_id, {"data": "test"}, ["actor-b"])

    if "asya_crew.resume" in sys.modules:
        del sys.modules["asya_crew.resume"]
    from asya_crew.resume import resume_handler as handler

    handler({})

    deadline_path = os.path.join(vfs_root, "headers", "x-asya-deadline-at")
    assert not os.path.exists(deadline_path)

    logger.info("=== test_no_deadline_without_timeout_header: PASSED ===")


def test_cleans_up_persisted_file(tmp_path, monkeypatch):
    """Test resume handler deletes persisted JSON file after successful load."""
    logger.info("=== test_cleans_up_persisted_file ===")

    vfs_root = setup_vfs(str(tmp_path / "vfs"))
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    mount_path = str(tmp_path / "state")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    task_id = "task-cleanup"
    with open(os.path.join(vfs_root, "headers", "x-asya-resume-task"), "w") as f:
        f.write(task_id)

    persisted_path = write_persisted_message(mount_path, task_id, {"data": "test"}, ["actor-b"])

    if "asya_crew.resume" in sys.modules:
        del sys.modules["asya_crew.resume"]
    from asya_crew.resume import resume_handler as handler

    handler({})

    assert not os.path.exists(persisted_path)

    logger.info("=== test_cleans_up_persisted_file: PASSED ===")


def test_cleans_up_header_files(tmp_path, monkeypatch):
    """Test resume handler deletes x-asya-resume-task header file after read."""
    logger.info("=== test_cleans_up_header_files ===")

    vfs_root = setup_vfs(str(tmp_path / "vfs"))
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    mount_path = str(tmp_path / "state")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    task_id = "task-header-cleanup"
    task_header_path = os.path.join(vfs_root, "headers", "x-asya-resume-task")
    with open(task_header_path, "w") as f:
        f.write(task_id)

    write_persisted_message(mount_path, task_id, {"data": "test"}, ["actor-b"])

    if "asya_crew.resume" in sys.modules:
        del sys.modules["asya_crew.resume"]
    from asya_crew.resume import resume_handler as handler

    handler({})

    assert not os.path.exists(task_header_path)

    logger.info("=== test_cleans_up_header_files: PASSED ===")


def test_raises_when_persisted_message_not_found(tmp_path, monkeypatch):
    """Test resume handler raises FileNotFoundError when persisted message missing."""
    logger.info("=== test_raises_when_persisted_message_not_found ===")

    vfs_root = setup_vfs(str(tmp_path / "vfs"))
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    mount_path = str(tmp_path / "state")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    task_id = "task-missing"
    with open(os.path.join(vfs_root, "headers", "x-asya-resume-task"), "w") as f:
        f.write(task_id)

    if "asya_crew.resume" in sys.modules:
        del sys.modules["asya_crew.resume"]
    from asya_crew.resume import resume_handler as handler

    with pytest.raises(FileNotFoundError):
        handler({})

    logger.info("=== test_raises_when_persisted_message_not_found: PASSED ===")


def test_default_payload_key(tmp_path, monkeypatch):
    """Test resume handler uses default payload_key when not specified."""
    logger.info("=== test_default_payload_key ===")

    vfs_root = setup_vfs(str(tmp_path / "vfs"))
    monkeypatch.setenv("ASYA_MSG_ROOT", vfs_root)

    mount_path = str(tmp_path / "state")
    os.makedirs(mount_path)
    monkeypatch.setenv("ASYA_PERSISTENCE_MOUNT", mount_path)

    task_id = "task-default-key"
    with open(os.path.join(vfs_root, "headers", "x-asya-resume-task"), "w") as f:
        f.write(task_id)

    pause_metadata = {"prompt": "Enter name", "fields": [{"name": "username", "type": "string", "required": True}]}
    write_persisted_message(mount_path, task_id, {"status": "pending"}, ["actor-b"], pause_metadata=pause_metadata)

    if "asya_crew.resume" in sys.modules:
        del sys.modules["asya_crew.resume"]
    from asya_crew.resume import resume_handler as handler

    result = handler({"username": "alice"})

    assert result == {"status": "pending", "username": "alice"}

    logger.info("=== test_default_payload_key: PASSED ===")
