#!/usr/bin/env python3
"""
A2A protocol integration tests.

Tests the full A2A JSON-RPC endpoint at /a2a/ using a live gateway + actors
running in Docker Compose (no Kind cluster required).

Auth: API key only (ASYA_A2A_API_KEY env var set by .env.tester).
JWT auth is not tested at integration level — JWKS server not deployed here.

Coverage:
  - message/stream: blocking SSE stream until completion (A2A v0.3.7)
  - tasks/get: retrieve task state after completion
  - tasks/list: tasks per context
  - tasks/cancel: cancel a running slow task
  - tasks/resubscribe: events for completed task (A2A v0.3.7)
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
    """Send a task via message/stream (A2A v0.3.7) and collect SSE events until final."""
    ctx_id = context_id or str(uuid.uuid4())
    params = {
        "message": {
            "messageId": str(uuid.uuid4()),
            "contextId": ctx_id,
            "role": "user",
            "parts": [{"kind": "data", "data": payload}],
        },
        "metadata": {"skill": skill},
    }
    return _a2a_stream("message/stream", params, timeout=timeout)


def _extract_task_id(events: list[dict]) -> str | None:
    """Extract server-assigned task ID from the first SSE event."""
    for event in events:
        task_id = event.get("result", {}).get("taskId")
        if task_id:
            return task_id
    return None


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
# message/stream (A2A v0.3.7: was tasks/send)
# ---------------------------------------------------------------------------


def test_message_stream_echo_completes():
    """message/stream through test_echo actor returns completed state."""
    events = _send_task("test_echo", {"message": "a2a-integration"}, timeout=60)

    assert len(events) > 0, "must have at least one SSE event"
    final = _final_state(events)
    assert final == "completed", f"expected completed, got: {final}"
    assert any(e.get("result", {}).get("final") for e in events), "must have final=true event"
    logger.info(f"[+] message/stream echo: {len(events)} events, state={final}")


# ---------------------------------------------------------------------------
# tasks/get
# ---------------------------------------------------------------------------


def test_tasks_get_returns_state():
    """tasks/get returns completed state for a task finished via message/stream."""
    ctx_id = str(uuid.uuid4())
    params = {
        "message": {
            "messageId": str(uuid.uuid4()),
            "contextId": ctx_id,
            "role": "user",
            "parts": [{"kind": "data", "data": {"message": "get-test"}}],
        },
        "metadata": {"skill": "test_echo"},
    }
    events = _a2a_stream("message/stream", params, timeout=60)
    assert _final_state(events) == "completed"

    task_id = _extract_task_id(events)
    assert task_id, f"could not extract task ID from events: {events[:2]}"

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
        params = {
            "message": {
                "messageId": str(uuid.uuid4()),
                "contextId": ctx_id,
                "role": "user",
                "parts": [{"kind": "data", "data": {"message": f"list-{i}"}}],
            },
            "metadata": {"skill": "test_echo"},
        }
        events = _a2a_stream("message/stream", params, timeout=60)
        assert _final_state(events) == "completed"

    result = _a2a_post("tasks/list", {"context_id": ctx_id})
    assert "result" in result
    tasks = result["result"]
    if isinstance(tasks, dict):
        tasks = tasks.get("tasks", [])
    assert len(tasks) >= 2, f"expected >=2 tasks, got {len(tasks)}"
    logger.info(f"[+] tasks/list: {len(tasks)} tasks for context {ctx_id}")


# ---------------------------------------------------------------------------
# tasks/resubscribe (A2A v0.3.7: was tasks/subscribe)
# ---------------------------------------------------------------------------


def test_tasks_resubscribe_completed_task():
    """tasks/resubscribe reconnects to a live task stream and receives events until completion."""
    ctx_id = str(uuid.uuid4())
    send_params = {
        "message": {
            "messageId": str(uuid.uuid4()),
            "contextId": ctx_id,
            "role": "user",
            "parts": [{"kind": "data", "data": {"first_call": True}}],
        },
        "metadata": {"skill": "test_slow_boundary"},
    }

    task_id_ready = threading.Event()
    task_id_holder: list[str] = []
    send_events: list = []

    def _send():
        try:
            h = _headers()
            resp = requests.post(
                _A2A_URL,
                json={"jsonrpc": "2.0", "id": 1, "method": "message/stream", "params": send_params},
                headers=h,
                stream=True,
                timeout=90,
            )
            resp.raise_for_status()
            client = SSEClient(resp)
            for event in client.events():
                if not event.data:
                    continue
                data = json.loads(event.data)
                send_events.append(data)
                if not task_id_holder:
                    tid = data.get("result", {}).get("taskId")
                    if tid:
                        task_id_holder.append(tid)
                        task_id_ready.set()
                if data.get("result", {}).get("final"):
                    break
        except Exception:
            pass

    t = threading.Thread(target=_send, daemon=True)
    t.start()

    assert task_id_ready.wait(timeout=30), "timed out waiting for task ID from stream"
    task_id = task_id_holder[0]

    sub_events = _a2a_stream("tasks/resubscribe", {"id": task_id}, timeout=60)
    t.join(timeout=90)

    assert len(sub_events) > 0, "resubscribe must return at least one event"
    assert _final_state(sub_events) == "completed"
    logger.info(f"[+] tasks/resubscribe: {len(sub_events)} events, state=completed")


# ---------------------------------------------------------------------------
# tasks/cancel
# ---------------------------------------------------------------------------


def test_tasks_cancel_transitions_to_cancelled():
    """tasks/cancel on a running task transitions it to cancelled."""
    ctx_id = str(uuid.uuid4())
    send_params = {
        "message": {
            "messageId": str(uuid.uuid4()),
            "contextId": ctx_id,
            "role": "user",
            "parts": [{"kind": "data", "data": {"first_call": True}}],
        },
        "metadata": {"skill": "test_slow_boundary"},
    }

    task_id_ready = threading.Event()
    task_id_holder: list[str] = []
    send_events: list = []

    def _send():
        try:
            h = _headers()
            resp = requests.post(
                _A2A_URL,
                json={"jsonrpc": "2.0", "id": 1, "method": "message/stream", "params": send_params},
                headers=h,
                stream=True,
                timeout=90,
            )
            resp.raise_for_status()
            client = SSEClient(resp)
            for event in client.events():
                if not event.data:
                    continue
                data = json.loads(event.data)
                send_events.append(data)
                # Signal the task ID as soon as we have it
                if not task_id_holder:
                    tid = data.get("result", {}).get("taskId")
                    if tid:
                        task_id_holder.append(tid)
                        task_id_ready.set()
                if data.get("result", {}).get("final"):
                    break
        except Exception:
            pass

    t = threading.Thread(target=_send, daemon=True)
    t.start()

    assert task_id_ready.wait(timeout=30), "timed out waiting for task ID from stream"
    task_id = task_id_holder[0]

    cancel_result = _a2a_post("tasks/cancel", {"id": task_id}, timeout=15)
    t.join(timeout=65)

    assert "result" in cancel_result, f"tasks/cancel must return result: {cancel_result}"
    task = cancel_result["result"]
    cancel_state = task.get("status", {}).get("state") or task.get("state")
    assert cancel_state == "canceled", f"expected canceled, got: {cancel_state}"
    logger.info(f"[+] tasks/cancel: state={cancel_state}")


# ---------------------------------------------------------------------------
# Multi-hop pipeline
# ---------------------------------------------------------------------------


def test_multihop_pipeline_via_a2a():
    """message/stream through a multi-actor pipeline (doubler → incrementer) completes."""
    events = _send_task("test_pipeline", {"value": 7}, timeout=60)

    assert len(events) > 0
    final = _final_state(events)
    assert final == "completed", f"multi-hop pipeline should complete, got: {final}"
    logger.info(f"[+] multi-hop pipeline: {len(events)} events, state={final}")


# ---------------------------------------------------------------------------
# GetTask history (fetched from state proxy for completed tasks)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.getenv("ASYA_STORAGE") == "gcs",
    reason="pubsub-gcs routes x-sink writes through GCS socket connector; local FileReader cannot serve history",
)
def test_tasks_get_returns_history_for_completed_task():
    """tasks/get with historyLength returns conversation history for a completed task.

    History is persisted by x-sink to the shared state proxy volume and read
    back by the gateway on GetTask. The initial user message is always present
    in payload.a2a.task.history (set by the translator at send time).

    Uses a TextPart so the echo handler passes the payload through unchanged,
    preserving the payload.a2a.task.history set by the translator.
    """
    ctx_id = str(uuid.uuid4())
    params = {
        "message": {
            "messageId": str(uuid.uuid4()),
            "contextId": ctx_id,
            "role": "user",
            "parts": [{"kind": "text", "text": "history-test-message"}],
        },
        "metadata": {"skill": "test_echo"},
    }
    events = _a2a_stream("message/stream", params, timeout=60)
    assert _final_state(events) == "completed", f"task must complete first: {events[-3:]}"

    task_id = _extract_task_id(events)
    assert task_id, f"could not extract task ID from events: {events[:2]}"

    # Allow brief propagation window for x-sink to write the checkpoint file.
    import time
    for _ in range(20):
        result = _a2a_post("tasks/get", {"id": task_id, "historyLength": 10})
        task = result.get("result", {})
        history = task.get("history")
        if history:
            break
        time.sleep(0.5)  # Poll for state proxy file to be written

    assert history is not None, (
        f"tasks/get with historyLength must return history for completed task "
        f"(state proxy file may not be written yet or volume not shared). "
        f"task state: {task.get('status')}"
    )
    assert len(history) >= 1, f"expected at least 1 history message, got: {history}"
    # The initial user message is always the first history entry
    roles = [m.get("role") for m in history]
    assert "user" in roles, f"user message must be in history, got roles: {roles}"
    logger.info(f"[+] tasks/get history: task_id={task_id}, {len(history)} messages, roles={roles}")


def test_tasks_get_history_omitted_for_in_flight_task():
    """tasks/get omits history for in-flight tasks (not available from queues)."""
    import threading

    ctx_id = str(uuid.uuid4())
    send_params = {
        "message": {
            "messageId": str(uuid.uuid4()),
            "contextId": ctx_id,
            "role": "user",
            "parts": [{"kind": "data", "data": {"first_call": True}}],
        },
        "metadata": {"skill": "test_slow_boundary"},
    }

    task_id_ready = threading.Event()
    task_id_holder: list[str] = []

    def _send():
        try:
            h = _headers()
            resp = requests.post(
                _A2A_URL,
                json={"jsonrpc": "2.0", "id": 1, "method": "message/stream", "params": send_params},
                headers=h,
                stream=True,
                timeout=90,
            )
            resp.raise_for_status()
            from sseclient import SSEClient
            import json as _json

            client = SSEClient(resp)
            for event in client.events():
                if not event.data:
                    continue
                data = _json.loads(event.data)
                if not task_id_holder:
                    tid = data.get("result", {}).get("taskId")
                    if tid:
                        task_id_holder.append(tid)
                        task_id_ready.set()
                if data.get("result", {}).get("final"):
                    break
        except Exception:
            pass

    t = threading.Thread(target=_send, daemon=True)
    t.start()

    assert task_id_ready.wait(timeout=30), "timed out waiting for task ID"
    task_id = task_id_holder[0]

    result = _a2a_post("tasks/get", {"id": task_id, "historyLength": 10})
    task = result.get("result", {})
    history = task.get("history")

    # history must be absent (None) for in-flight tasks, not an empty list
    assert history is None, f"history must be omitted for in-flight tasks, got: {history}"
    logger.info(f"[+] tasks/get in-flight: task_id={task_id}, history correctly omitted")

    t.join(timeout=90)
