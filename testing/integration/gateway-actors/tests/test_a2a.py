#!/usr/bin/env python3
"""
A2A protocol integration tests.

Tests the full A2A JSON-RPC endpoint at /a2a/ using a live gateway + actors
running in Docker Compose (no Kind cluster required).

Auth: API key only (ASYA_A2A_API_KEY env var set by .env.tester).
JWT auth is not tested at integration level — JWKS server not deployed here.

Coverage:
  - tasks/send: blocking SSE stream until completion
  - tasks/get: retrieve task state after completion
  - tasks/list: tasks per context
  - tasks/cancel: cancel a running slow task
  - tasks/subscribe: events for completed task
  - Multi-hop pipeline (doubler → incrementer)
  - Auth: API key accepted / wrong key rejected
"""

import json
import logging
import os
import threading
import time
import uuid

import pytest
import requests
from sseclient import SSEClient

logger = logging.getLogger(__name__)

GATEWAY_URL = os.environ["ASYA_GATEWAY_URL"]
API_KEY = os.environ["ASYA_A2A_API_KEY"]

_A2A_URL = f"{GATEWAY_URL}/a2a/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _headers() -> dict:
    return {"X-API-Key": API_KEY}


def _a2a_post(method: str, params: dict, headers: dict | None = None, timeout: int = 10) -> dict:
    h = _headers()
    if headers:
        h.update(headers)
    resp = requests.post(
        _A2A_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        headers=h,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def _a2a_stream(
    method: str, params: dict, headers: dict | None = None, timeout: int = 60
) -> list[dict]:
    h = _headers()
    if headers:
        h.update(headers)
    resp = requests.post(
        _A2A_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        headers=h,
        stream=True,
        timeout=timeout,
    )
    resp.raise_for_status()

    events = []
    client = SSEClient(resp)
    try:
        for event in client.events():
            if not event.data:
                continue
            data = json.loads(event.data)
            events.append(data)
            if data.get("result", {}).get("final"):
                break
    except Exception as e:
        logger.debug(f"SSE stream ended: {e}")
    return events


def _send_task(skill: str, payload: dict, context_id: str | None = None, timeout: int = 60) -> list[dict]:
    task_id = str(uuid.uuid4())
    ctx_id = context_id or str(uuid.uuid4())
    params = {
        "id": task_id,
        "contextId": ctx_id,
        "message": {
            "role": "user",
            "parts": [{"type": "data", "data": payload}],
        },
        "metadata": {"skill": skill},
    }
    return _a2a_stream("tasks/send", params, timeout=timeout)


def _final_state(events: list[dict]) -> str | None:
    for event in reversed(events):
        result = event.get("result", {})
        status = result.get("status", {})
        if status:
            return status.get("state")
    return None


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_a2a_no_auth_returns_401():
    """A2A endpoint rejects unauthenticated requests."""
    resp = requests.post(
        _A2A_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": "tasks/get", "params": {"id": "probe"}},
        timeout=5,
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == -32005


def test_a2a_wrong_api_key_returns_401():
    """Wrong API key is rejected."""
    resp = requests.post(
        _A2A_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": "tasks/get", "params": {"id": "probe"}},
        headers={"X-API-Key": "definitely-wrong"},
        timeout=5,
    )
    assert resp.status_code == 401


def test_a2a_valid_api_key_passes():
    """Valid API key allows access."""
    resp = requests.post(
        _A2A_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": "tasks/get", "params": {"id": "no-such-task"}},
        headers=_headers(),
        timeout=5,
    )
    assert resp.status_code != 401, f"valid key rejected: {resp.text}"


# ---------------------------------------------------------------------------
# tasks/send
# ---------------------------------------------------------------------------


def test_tasks_send_echo_completes():
    """tasks/send through test_echo actor returns completed state."""
    events = _send_task("test_echo", {"message": "a2a-integration"}, timeout=60)

    assert len(events) > 0, "must have at least one SSE event"
    final = _final_state(events)
    assert final == "completed", f"expected completed, got: {final}"
    assert any(e.get("result", {}).get("final") for e in events), "must have final=true event"
    logger.info(f"[+] tasks/send echo: {len(events)} events, state={final}")


# ---------------------------------------------------------------------------
# tasks/get
# ---------------------------------------------------------------------------


def test_tasks_get_returns_state():
    """tasks/get returns completed state for a task finished via tasks/send."""
    task_id = str(uuid.uuid4())
    ctx_id = str(uuid.uuid4())
    params = {
        "id": task_id,
        "contextId": ctx_id,
        "message": {"role": "user", "parts": [{"type": "data", "data": {"message": "get-test"}}]},
        "metadata": {"skill": "test_echo"},
    }
    events = _a2a_stream("tasks/send", params, timeout=60)
    assert _final_state(events) == "completed"

    result = _a2a_post("tasks/get", {"id": task_id})
    assert "result" in result, f"tasks/get must have result: {result}"
    task = result["result"]
    state = task.get("status", {}).get("state") or task.get("state")
    assert state == "completed", f"expected completed, got: {state}"
    logger.info(f"[+] tasks/get: state={state}")


# ---------------------------------------------------------------------------
# tasks/list
# ---------------------------------------------------------------------------


def test_tasks_list_returns_tasks_for_context():
    """tasks/list returns tasks grouped by context ID."""
    ctx_id = str(uuid.uuid4())

    for i in range(2):
        task_id = str(uuid.uuid4())
        params = {
            "id": task_id,
            "contextId": ctx_id,
            "message": {"role": "user", "parts": [{"type": "data", "data": {"message": f"list-{i}"}}]},
            "metadata": {"skill": "test_echo"},
        }
        events = _a2a_stream("tasks/send", params, timeout=60)
        assert _final_state(events) == "completed"

    result = _a2a_post("tasks/list", {"contextId": ctx_id})
    assert "result" in result
    tasks = result["result"]
    if isinstance(tasks, dict):
        tasks = tasks.get("tasks", [])
    assert len(tasks) >= 2, f"expected >=2 tasks, got {len(tasks)}"
    logger.info(f"[+] tasks/list: {len(tasks)} tasks for context {ctx_id}")


# ---------------------------------------------------------------------------
# tasks/subscribe
# ---------------------------------------------------------------------------


def test_tasks_subscribe_completed_task():
    """tasks/subscribe on a completed task delivers immediate final event."""
    task_id = str(uuid.uuid4())
    params = {
        "id": task_id,
        "contextId": str(uuid.uuid4()),
        "message": {"role": "user", "parts": [{"type": "data", "data": {"message": "sub-test"}}]},
        "metadata": {"skill": "test_echo"},
    }
    events = _a2a_stream("tasks/send", params, timeout=60)
    assert _final_state(events) == "completed"

    sub_events = _a2a_stream("tasks/subscribe", {"id": task_id}, timeout=15)
    assert len(sub_events) > 0, "subscribe must return at least one event"
    assert _final_state(sub_events) == "completed"
    logger.info(f"[+] tasks/subscribe: {len(sub_events)} events")


# ---------------------------------------------------------------------------
# tasks/cancel
# ---------------------------------------------------------------------------


def test_tasks_cancel_transitions_to_cancelled():
    """tasks/cancel on a running task transitions it to cancelled."""
    task_id = str(uuid.uuid4())
    send_params = {
        "id": task_id,
        "contextId": str(uuid.uuid4()),
        "message": {"role": "user", "parts": [{"type": "data", "data": {"first_call": True}}]},
        "metadata": {"skill": "test_slow_boundary"},
    }

    send_events: list = []

    def _send():
        try:
            send_events.extend(_a2a_stream("tasks/send", send_params, timeout=60))
        except Exception:
            pass

    t = threading.Thread(target=_send, daemon=True)
    t.start()
    time.sleep(0.5)  # Wait for task to be dispatched to queue

    cancel_events = _a2a_stream("tasks/cancel", {"id": task_id}, timeout=15)
    t.join(timeout=65)

    assert len(cancel_events) > 0
    cancel_state = _final_state(cancel_events)
    assert cancel_state == "canceled", f"expected canceled, got: {cancel_state}"
    logger.info(f"[+] tasks/cancel: state={cancel_state}")


# ---------------------------------------------------------------------------
# Multi-hop pipeline
# ---------------------------------------------------------------------------


def test_multihop_pipeline_via_a2a():
    """tasks/send through a multi-actor pipeline (doubler → incrementer) completes."""
    events = _send_task("test_pipeline", {"value": 7}, timeout=60)

    assert len(events) > 0
    final = _final_state(events)
    assert final == "completed", f"multi-hop pipeline should complete, got: {final}"
    logger.info(f"[+] multi-hop pipeline: {len(events)} events, state={final}")
