#!/usr/bin/env python3
"""
E2E tests for the A2A protocol implementation.

Tests the full A2A JSON-RPC endpoint at /a2a/ in a live Kind cluster:
  - Agent card discovery (public, unauthenticated)
  - Auth: API key and JWT Bearer token
  - message/stream: dispatch work through the actor mesh, block on SSE stream (A2A v0.3.7)
  - tasks/get: retrieve current task state
  - tasks/resubscribe: SSE stream of task updates (A2A v0.3.7)
  - tasks/cancel: transition task to cancelled state
  - tasks/list: list tasks for a context
  - Extended agent card: skills section includes DB-backed tool metadata
  - Multi-actor pipeline: message/stream through a multi-hop route

Prerequisites (set by deploy.sh and profile .env files):
  - ASYA_GATEWAY_URL: gateway NodePort URL (e.g. http://127.0.0.1:8080)
  - ASYA_A2A_API_KEY: API key configured in the gateway
  - ASYA_A2A_JWT_ISSUER: JWT issuer configured in the gateway
  - ASYA_A2A_JWT_AUDIENCE: JWT audience configured in the gateway
  - A2A_PRIVATE_KEY_PATH: (optional) path to RSA private key for JWT signing;
      defaults to testing/e2e/.jwks/private_key.pem
"""

import json
import logging
import os
import pathlib
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from sseclient import SSEClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_E2E_DIR = pathlib.Path(__file__).parent.parent
_DEFAULT_PRIVATE_KEY_PATH = str(_E2E_DIR / ".jwks" / "private_key.pem")

GATEWAY_URL = os.getenv("ASYA_GATEWAY_URL", "http://127.0.0.1:8080")
API_KEY = os.getenv("ASYA_A2A_API_KEY", "")
JWT_ISSUER = os.getenv("ASYA_A2A_JWT_ISSUER", "https://test-issuer.e2e")
JWT_AUDIENCE = os.getenv("ASYA_A2A_JWT_AUDIENCE", "asya-gateway-e2e")
PRIVATE_KEY_PATH = os.getenv("A2A_PRIVATE_KEY_PATH", _DEFAULT_PRIVATE_KEY_PATH)

_A2A_URL = f"{GATEWAY_URL}/a2a/"
_AGENT_CARD_URL = f"{GATEWAY_URL}/.well-known/agent.json"
_EXTENDED_CARD_URL = f"{GATEWAY_URL}/.well-known/agent.json?extended=true"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _api_key_headers() -> dict:
    return {"X-API-Key": API_KEY} if API_KEY else {}


def _a2a_post(method: str, params: dict, headers: dict | None = None, timeout: int = 10) -> dict:
    """Send a non-streaming A2A JSON-RPC call and return the parsed response."""
    h = _api_key_headers()
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


def _a2a_stream(method: str, params: dict, headers: dict | None = None, timeout: int = 120) -> list[dict]:
    """
    Send a streaming A2A JSON-RPC call (tasks/send, tasks/subscribe).
    Returns list of JSON-RPC response objects collected until the final event.
    """
    h = _api_key_headers()
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
            # Final event signals end of stream
            result = data.get("result", {})
            if result.get("final"):
                break
    except Exception as e:
        logger.debug(f"SSE stream ended: {e}")

    return events


def _send_task(skill: str, payload: dict, context_id: str | None = None, timeout: int = 120) -> list[dict]:
    """
    Dispatch a task via message/stream (A2A v0.3.7) and return all SSE events.

    The returned list ends with an event where result.final == True.
    """
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


def _final_state(events: list[dict]) -> str | None:
    """Extract the A2A task state from the last event in the stream."""
    for event in reversed(events):
        result = event.get("result", {})
        status = result.get("status", {})
        if status:
            return status.get("state")
    return None


def _task_id_from_events(events: list[dict]) -> str | None:
    """Extract the task ID from SSE events."""
    for event in events:
        result = event.get("result", {})
        tid = result.get("taskId") or result.get("task_id")
        if tid:
            return tid
    return None


# ---------------------------------------------------------------------------
# JWT helpers (skipped when private key is absent)
# ---------------------------------------------------------------------------


def _load_private_key():
    """Load RSA private key from disk. Fails the test if not found."""
    if not os.path.exists(PRIVATE_KEY_PATH):
        pytest.skip(f"Private key not found at {PRIVATE_KEY_PATH} — "
                    "run `make up` to generate JWKS keys")
    from cryptography.hazmat.primitives import serialization

    with open(PRIVATE_KEY_PATH, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def _make_jwt(private_key, *, expired: bool = False, wrong_issuer: bool = False,
              wrong_audience: bool = False) -> str:
    import jwt as pyjwt

    now = datetime.now(tz=timezone.utc)
    return pyjwt.encode(
        {
            "iss": "https://wrong-issuer.e2e" if wrong_issuer else JWT_ISSUER,
            "aud": "wrong-audience" if wrong_audience else JWT_AUDIENCE,
            "sub": "e2e-test-user",
            "iat": now,
            "exp": now - timedelta(hours=1) if expired else now + timedelta(hours=1),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key-1"},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def a2a_url():
    return _A2A_URL


@pytest.fixture(scope="session")
def api_key_headers():
    return _api_key_headers()


@pytest.fixture(scope="session")
def private_key():
    return _load_private_key()


# ---------------------------------------------------------------------------
# Agent card tests
# ---------------------------------------------------------------------------


@pytest.mark.fast
def test_agent_card_is_public():
    """Agent card is accessible without any credentials."""
    resp = requests.get(_AGENT_CARD_URL, timeout=10)
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    card = resp.json()
    assert "name" in card, "AgentCard must have a name field"
    assert "capabilities" in card, "AgentCard must have capabilities"
    logger.info(f"[+] Agent card: name={card.get('name')}")


@pytest.mark.fast
def test_agent_card_capabilities():
    """Agent card declares correct A2A capabilities."""
    resp = requests.get(_AGENT_CARD_URL, timeout=10)
    resp.raise_for_status()
    card = resp.json()
    caps = card.get("capabilities", {})
    # Gateway implements streaming
    assert caps.get("streaming") is True, f"streaming should be true, got: {caps}"
    logger.info(f"[+] Agent card capabilities: {caps}")


@pytest.mark.fast
def test_extended_agent_card_has_skills():
    """
    Extended agent card includes skills populated from DB-backed tool registry.
    Verifies that at least one A2A-enabled tool appears in the skills section.
    """
    resp = requests.get(_EXTENDED_CARD_URL, timeout=10)
    # Extended card may or may not be at a different URL depending on implementation.
    # If 404, check the regular agent card for skills.
    if resp.status_code == 404:
        resp = requests.get(_AGENT_CARD_URL, timeout=10)
    resp.raise_for_status()
    card = resp.json()
    skills = card.get("skills", [])
    assert len(skills) > 0, (
        f"Expected at least one skill in the agent card (a2a_enabled tools from DB), got: {skills}"
    )
    skill_ids = [s.get("id") or s.get("name") for s in skills]
    logger.info(f"[+] Agent card skills: {skill_ids}")


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


@pytest.mark.fast
def test_a2a_no_auth_returns_401():
    """A2A endpoint rejects unauthenticated requests."""
    resp = requests.post(
        _A2A_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": "tasks/get",
              "params": {"id": "probe-nonexistent"}},
        timeout=5,
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == -32005, f"expected JSON-RPC -32005, got: {body}"
    logger.info("[+] Unauthenticated request correctly rejected with 401 / -32005")


@pytest.mark.fast
def test_a2a_valid_api_key_passes():
    """Valid API key grants access."""
    pytest.importorskip("requests")  # sanity
    if not API_KEY:
        pytest.skip("ASYA_A2A_API_KEY not configured")
    resp = requests.post(
        _A2A_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": "tasks/get",
              "params": {"id": "probe-nonexistent"}},
        headers={"X-API-Key": API_KEY},
        timeout=5,
    )
    assert resp.status_code != 401, f"valid API key should not return 401: {resp.text}"
    logger.info("[+] Valid API key accepted")


@pytest.mark.fast
def test_a2a_wrong_api_key_returns_401():
    """Wrong API key is rejected."""
    if not API_KEY:
        pytest.skip("ASYA_A2A_API_KEY not configured")
    resp = requests.post(
        _A2A_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": "tasks/get",
              "params": {"id": "probe-nonexistent"}},
        headers={"X-API-Key": "totally-wrong-key"},
        timeout=5,
    )
    assert resp.status_code == 401
    logger.info("[+] Wrong API key correctly rejected")


@pytest.mark.fast
def test_a2a_valid_jwt_passes(private_key):
    """Valid JWT Bearer token grants access."""
    token = _make_jwt(private_key)
    resp = requests.post(
        _A2A_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": "tasks/get",
              "params": {"id": "probe-nonexistent"}},
        headers={"Authorization": f"Bearer {token}"},
        timeout=5,
    )
    assert resp.status_code != 401, f"valid JWT should not return 401: {resp.text}"
    logger.info("[+] Valid JWT accepted")


@pytest.mark.fast
def test_a2a_expired_jwt_returns_401(private_key):
    """Expired JWT is rejected."""
    token = _make_jwt(private_key, expired=True)
    resp = requests.post(
        _A2A_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": "tasks/get",
              "params": {"id": "probe-nonexistent"}},
        headers={"Authorization": f"Bearer {token}"},
        timeout=5,
    )
    assert resp.status_code == 401
    logger.info("[+] Expired JWT correctly rejected")


@pytest.mark.fast
def test_a2a_wrong_issuer_returns_401(private_key):
    """JWT with wrong issuer is rejected."""
    token = _make_jwt(private_key, wrong_issuer=True)
    resp = requests.post(
        _A2A_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": "tasks/get",
              "params": {"id": "probe-nonexistent"}},
        headers={"Authorization": f"Bearer {token}"},
        timeout=5,
    )
    assert resp.status_code == 401
    logger.info("[+] JWT with wrong issuer correctly rejected")


@pytest.mark.fast
def test_a2a_wrong_audience_returns_401(private_key):
    """JWT with wrong audience is rejected."""
    token = _make_jwt(private_key, wrong_audience=True)
    resp = requests.post(
        _A2A_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": "tasks/get",
              "params": {"id": "probe-nonexistent"}},
        headers={"Authorization": f"Bearer {token}"},
        timeout=5,
    )
    assert resp.status_code == 401
    logger.info("[+] JWT with wrong audience correctly rejected")


# ---------------------------------------------------------------------------
# Protocol tests: tasks/send, tasks/get, tasks/cancel, tasks/list,
# tasks/subscribe, multi-hop pipeline
# ---------------------------------------------------------------------------


@pytest.mark.fast
def test_message_stream_dispatches_work_and_returns_task_state():
    """
    message/stream dispatches work through the actor mesh and streams events.
    The SSE stream must end with a final event in 'completed' state.
    """
    if not API_KEY:
        pytest.skip("ASYA_A2A_API_KEY not configured")

    events = _send_task("test_echo", {"message": "a2a-hello"}, timeout=120)

    assert len(events) > 0, "message/stream must return at least one SSE event"
    final = _final_state(events)
    assert final == "completed", f"expected final state 'completed', got: {final}"
    # Verify the stream included a final=true event
    assert any(e.get("result", {}).get("final") for e in events), (
        "must have at least one event with result.final=true"
    )
    logger.info(f"[+] message/stream completed: {len(events)} events, final state={final}")


@pytest.mark.fast
def test_tasks_get_returns_task_state():
    """
    tasks/get returns the current task state for a known task.
    Sends a task first (via message/stream) then retrieves it via tasks/get.
    """
    if not API_KEY:
        pytest.skip("ASYA_A2A_API_KEY not configured")

    # Send a task and extract the server-assigned task ID from SSE events
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
    events = _a2a_stream("message/stream", params, timeout=120)
    final = _final_state(events)
    assert final == "completed", f"task must complete before tasks/get: {final}"

    task_id = _task_id_from_events(events)
    assert task_id, f"could not extract task ID from events: {events[:2]}"

    # Now retrieve via tasks/get
    result = _a2a_post("tasks/get", {"id": task_id})
    assert "result" in result, f"tasks/get must return result: {result}"
    task = result["result"]
    state = task.get("status", {}).get("state") or task.get("state")
    assert state == "completed", f"tasks/get should show completed state, got: {state}"
    logger.info(f"[+] tasks/get returned state={state} for task {task_id}")


@pytest.mark.fast
def test_tasks_resubscribe_streams_events():
    """
    tasks/resubscribe reconnects to a live task stream and receives events.
    Sends a slow task in a background thread and resubscribes concurrently.
    """
    if not API_KEY:
        pytest.skip("ASYA_A2A_API_KEY not configured")

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

    def send_in_bg():
        try:
            h = _api_key_headers()
            resp = requests.post(
                _A2A_URL,
                json={"jsonrpc": "2.0", "id": 1, "method": "message/stream", "params": send_params},
                headers=h,
                stream=True,
                timeout=120,
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
        except Exception as e:
            logger.debug(f"send_in_bg ended: {e}")

    t = threading.Thread(target=send_in_bg, daemon=True)
    t.start()

    assert task_id_ready.wait(timeout=30), "timed out waiting for task ID"
    task_id = task_id_holder[0]

    sub_events = _a2a_stream("tasks/resubscribe", {"id": task_id}, timeout=60)
    t.join(timeout=130)

    assert len(sub_events) > 0, "tasks/resubscribe must return at least one event"
    sub_final = _final_state(sub_events)
    assert sub_final == "completed", (
        f"tasks/resubscribe should return completed, got: {sub_final}"
    )
    logger.info(f"[+] tasks/resubscribe returned {len(sub_events)} events, final={sub_final}")


@pytest.mark.fast
def test_tasks_resubscribe_live_stream():
    """
    tasks/resubscribe delivers updates as a slow actor pipeline progresses.
    Sends a slow task in a background thread and resubscribes concurrently.
    """
    if not API_KEY:
        pytest.skip("ASYA_A2A_API_KEY not configured")

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
    send_error: list = []

    def send_in_bg():
        try:
            h = _api_key_headers()
            resp = requests.post(
                _A2A_URL,
                json={"jsonrpc": "2.0", "id": 1, "method": "message/stream", "params": send_params},
                headers=h,
                stream=True,
                timeout=120,
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
        except Exception as e:
            send_error.append(e)

    t = threading.Thread(target=send_in_bg, daemon=True)
    t.start()

    assert task_id_ready.wait(timeout=30), "timed out waiting for task ID"
    task_id = task_id_holder[0]

    sub_events = _a2a_stream("tasks/resubscribe", {"id": task_id}, timeout=60)
    t.join(timeout=130)

    if send_error:
        logger.warning(f"message/stream background thread error: {send_error[0]}")

    assert len(sub_events) > 0, "tasks/resubscribe should deliver at least one event"
    logger.info(
        f"[+] Live resubscribe: {len(sub_events)} resubscribe events, "
        f"{len(send_events)} stream events"
    )


@pytest.mark.fast
def test_tasks_cancel_transitions_to_cancelled():
    """
    tasks/cancel transitions a pending/running task to cancelled state.
    Uses test_slow_boundary to ensure the task is still running when cancelled.
    """
    if not API_KEY:
        pytest.skip("ASYA_A2A_API_KEY not configured")

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

    def send_in_bg():
        try:
            h = _api_key_headers()
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

    t = threading.Thread(target=send_in_bg, daemon=True)
    t.start()

    assert task_id_ready.wait(timeout=30), "timed out waiting for task ID"
    task_id = task_id_holder[0]

    # Cancel the task (returns JSON Task, not SSE stream)
    cancel_result = _a2a_post("tasks/cancel", {"id": task_id}, timeout=15)
    t.join(timeout=65)

    assert "result" in cancel_result, f"tasks/cancel must return result: {cancel_result}"
    task = cancel_result["result"]
    cancel_state = task.get("status", {}).get("state") or task.get("state")
    assert cancel_state == "canceled", (
        f"tasks/cancel should yield 'canceled' state, got: {cancel_state}"
    )
    logger.info(f"[+] tasks/cancel returned state={cancel_state}")


@pytest.mark.fast
def test_tasks_list_returns_tasks_for_context():
    """
    tasks/list returns all tasks for a given context (session) ID.
    Sends two tasks with the same context ID and verifies both appear in list.
    """
    if not API_KEY:
        pytest.skip("ASYA_A2A_API_KEY not configured")

    ctx_id = str(uuid.uuid4())

    # Send two tasks in the same context
    for i in range(2):
        params = {
            "message": {
                "messageId": str(uuid.uuid4()),
                "contextId": ctx_id,
                "role": "user",
                "parts": [{"kind": "data", "data": {"message": f"list-test-{i}"}}],
            },
            "metadata": {"skill": "test_echo"},
        }
        events = _a2a_stream("message/stream", params, timeout=120)
        assert _final_state(events) == "completed", f"task {i} must complete for tasks/list test"

    # List tasks for this context (JSON tag is context_id, snake_case)
    result = _a2a_post("tasks/list", {"context_id": ctx_id})
    assert "result" in result, f"tasks/list must return result: {result}"
    tasks = result["result"]
    if isinstance(tasks, dict):
        tasks = tasks.get("tasks", [])

    assert len(tasks) >= 2, (
        f"tasks/list should return at least 2 tasks for context {ctx_id}, got: {len(tasks)}"
    )
    logger.info(f"[+] tasks/list returned {len(tasks)} tasks for context {ctx_id}")


@pytest.mark.fast
def test_multihop_pipeline_via_a2a():
    """
    Multi-actor pipeline via A2A: submit a multi-hop task and track to completion.

    Routes through test-doubler -> test-incrementer (the 'test_pipeline' skill).
    Verifies the final state is 'completed' after full actor chain execution.
    """
    if not API_KEY:
        pytest.skip("ASYA_A2A_API_KEY not configured")

    events = _send_task("test_pipeline", {"value": 5}, timeout=120)

    assert len(events) > 0, "multi-hop task must produce SSE events"
    final = _final_state(events)
    assert final == "completed", f"multi-hop pipeline should complete, got: {final}"
    logger.info(
        f"[+] Multi-actor pipeline via A2A: {len(events)} events, final state={final}"
    )
