"""
Gateway test helper for integration and E2E tests.

Provides functionality for:
- Calling MCP tools via REST API
- Getting task status
- Waiting for task completion
- Streaming SSE progress updates
- HTTP polling for progress

FAIL-FAST: ASYA_GATEWAY_URL must be set by docker-compose.
"""

import json
import logging
import os
import time

import requests
from sseclient import SSEClient

from asya_testing.config import require_env


logger = logging.getLogger(__name__)


class GatewayTestHelper:
    """
    Helper class for gateway integration and E2E testing.

    Supports two progress monitoring methods:
    - SSE streaming (real-time updates)
    - HTTP polling (discrete status checks)

    Provides common functionality for:
    - Calling MCP tools via REST API
    - Getting task status
    - Waiting for task completion
    - Streaming SSE progress updates
    """

    def __init__(
        self,
        gateway_url: str | None = None,
        progress_method: str = "sse",
        mesh_gateway_url: str | None = None,
        mcp_url: str | None = None,
    ):
        if gateway_url is None:
            gateway_url = os.getenv("ASYA_MESH_API_URL") or require_env("ASYA_GATEWAY_URL")
        if mesh_gateway_url is None:
            mesh_gateway_url = os.getenv("ASYA_MESH_API_INTERNAL_URL", gateway_url)
        # MCP adapter runs on a separate port in the new multi-container gateway.
        # Fall back to gateway_url/tools/call for backward compat with old single-container gateway.
        if mcp_url is None:
            mcp_url = os.getenv("ASYA_MCP_URL", gateway_url)
        self.gateway_url = gateway_url
        self.mesh_gateway_url = mesh_gateway_url
        self.mcp_url = mcp_url
        # tools_url is the new mesh-api dispatch endpoint; legacy tests use actor name as tool name
        self.tools_url = f"{gateway_url}/api/v1/mesh/"
        self.tasks_url = f"{gateway_url}/api/v1/mesh"
        self.progress_method = progress_method
        logger.debug(f"Initialized GatewayTestHelper with progress_method={progress_method}")

    def call_mcp_tool(
        self,
        tool_name: str,
        arguments: dict,
        timeout: int = 300,
    ) -> dict:
        """
        Dispatch a task to an actor via the mesh API.

        Uses POST /api/v1/mesh/?actor={tool_name} (new multi-container gateway).
        Returns a dict compatible with the old MCP /tools/call response shape.
        The timeout sets the task deadline (seconds) — use ≥120 for actors with
        KEDA cold starts. The HTTP request itself times out after 10 seconds.
        """
        # Map MCP tool name to actor name. The new mesh-api uses actor names directly.
        # Legacy tool names from flows.yaml map to their flow entrypoint actor.
        # For most tools, underscore-to-hyphen conversion suffices (test_echo → test-echo).
        # Some flows start with a different actor than the tool name suggests.
        tool_to_actor = {
            "test_pipeline": "test-doubler",  # flows.yaml: entrypoint: test-doubler
            "test_empty_response": "test-empty",  # flows.yaml: entrypoint: test-empty
            "test_nested_flow": "start-test-nested-flow",  # flows.yaml: entrypoint: start-test-nested-flow
            "test_multihop": "test-multihop-0",  # flows.yaml: entrypoint: test-multihop-0
        }
        actor_name = tool_to_actor.get(tool_name, tool_name.replace("_", "-"))
        logger.debug(f"Dispatching actor task: {actor_name} with arguments: {arguments}")

        response = requests.post(
            self.tools_url,
            params={"actor": actor_name},
            json={"payload": arguments, "timeout": timeout},
            timeout=10,  # HTTP request timeout; task deadline is the 'timeout' body field
        )
        logger.debug(f"Dispatch response status: {response.status_code}")
        response.raise_for_status()

        data = response.json()
        task_id = data.get("id")
        logger.debug(f"Dispatched task ID: {task_id}")

        return {
            "result": {
                "task_id": task_id,
                "id": task_id,
                "message": f"Envelope created successfully with ID: {task_id}",
                "status_url": f"{self.tasks_url}/{task_id}",
                "stream_url": f"{self.tasks_url}/{task_id}/events",
                "metadata": None,
            }
        }

    def get_task_status(self, task_id: str, timeout: int = 5) -> dict:
        """Get task status via REST API.

        Returns a normalized dict with top-level 'status' and fields from the
        message data merged in, compatible with the old monolith gateway shape.
        """
        logger.debug(f"Getting task status for: {task_id}")
        response = requests.get(f"{self.tasks_url}/{task_id}", timeout=timeout)
        response.raise_for_status()
        raw = response.json()
        logger.debug(f"Task status raw: {raw}")

        # New mesh-api wraps actor data under 'data'. Merge it so that tests
        # written for the old gateway still see 'status', 'result', etc. at
        # the top level. Top-level fields (id, status) take precedence.
        normalized: dict = {}
        if isinstance(raw.get("data"), dict):
            normalized.update(raw["data"])
        normalized.update({k: v for k, v in raw.items() if k != "data"})
        return normalized

    def stream_task_progress(
        self,
        task_id: str,
        timeout: int = 30,
    ) -> list[dict]:
        """
        Stream task progress via SSE.

        Returns list of all progress update events (event="update") received before completion.
        """
        logger.debug(f"Starting SSE stream for task: {task_id}")
        updates = []

        response = requests.get(
            f"{self.tasks_url}/{task_id}/events",
            stream=True,
            timeout=timeout,
            headers={"Accept": "text/event-stream"},
        )
        response.raise_for_status()
        logger.debug(f"SSE stream connected, status: {response.status_code}")

        client = SSEClient(response)

        try:
            for event in client.events():
                # New mesh-api emits event: status; old gateway emitted event: update
                if event.event in ("update", "status") and event.data:
                    data = json.loads(event.data)
                    logger.debug(
                        f"SSE event: {event.event} data={event.data[:100] if len(event.data) > 100 else event.data}"
                    )

                    if "actor" not in data and "current_actor_name" in data:
                        data["actor"] = data["current_actor_name"]

                    updates.append(data)

                    if data.get("status") in ["succeeded", "failed", "canceled"]:
                        logger.debug(f"Final status reached: {data.get('status')}")
                        break

        except Exception as e:
            logger.debug(f"SSE stream ended with exception: {e}")

        logger.debug(f"SSE stream complete. Received {len(updates)} updates")
        return updates

    def stream_progress_updates(
        self,
        task_id: str,
        timeout: int = 30,
    ) -> list[dict]:
        """
        Alias for stream_task_progress for backward compatibility.
        """
        return self.stream_task_progress(task_id, timeout)

    def poll_task_progress(
        self,
        task_id: str,
        timeout: int = 30,
        interval: float = 0.5,
    ) -> list[dict]:
        """
        Poll task status via HTTP until completion.

        Returns list of all status updates collected during polling.
        """
        logger.debug(f"Starting HTTP polling for task: {task_id}")
        updates: list[dict] = []
        start_time = time.time()

        while time.time() - start_time < timeout:
            task = self.get_task_status(task_id)
            elapsed = time.time() - start_time

            current_actor = task.get("current_actor_name", "")
            progress_percent = task.get("progress_percent", 0)
            status = task["status"]
            message = task.get("message", "")

            update = {
                "status": status,
                "progress_percent": progress_percent,
                "actor": current_actor,
                "message": message,
                "timestamp": elapsed,
            }

            if (
                not updates
                or updates[-1]["status"] != update["status"]
                or updates[-1].get("progress_percent") != update.get("progress_percent")
                or updates[-1].get("actor") != update.get("actor")
                or updates[-1].get("message") != update.get("message")
            ):
                updates.append(update)
                logger.debug(
                    f"HTTP poll update: status={update['status']} progress={update['progress_percent']} actor={current_actor} message={message}"
                )

            if task["status"] in ["succeeded", "failed", "canceled", "unknown"]:
                logger.debug(f"Final status reached via HTTP polling: {task['status']}")
                break

            time.sleep(interval)  # Polling interval for HTTP progress check

        logger.debug(f"HTTP polling complete. Collected {len(updates)} updates")
        return updates

    def get_progress_updates(
        self,
        task_id: str,
        timeout: int = 30,
    ) -> list[dict]:
        """
        Get progress updates using configured method (SSE or HTTP polling).

        Returns list of progress updates in a normalized format.
        """
        if self.progress_method == "sse":
            return self.stream_task_progress(task_id, timeout)
        else:
            return self.poll_task_progress(task_id, timeout)

    def stream_task_events(
        self,
        task_id: str,
        timeout: int = 30,
    ) -> dict[str, list]:
        """
        Stream task events via SSE, collecting both partial and update events separately.

        Returns dict with:
        - "partial": list of partial event payloads (from event: partial)
        - "update": list of update event dicts (from event: update)
        """
        logger.debug(f"Starting SSE stream for task (all events): {task_id}")
        result: dict[str, list] = {"partial": [], "update": []}

        response = requests.get(
            f"{self.tasks_url}/{task_id}/events",
            stream=True,
            timeout=timeout,
            headers={"Accept": "text/event-stream"},
        )
        response.raise_for_status()
        logger.debug(f"SSE stream connected, status: {response.status_code}")

        client = SSEClient(response)

        try:
            for event in client.events():
                logger.debug(
                    f"SSE event type={event.event} data={event.data[:100] if event.data and len(event.data) > 100 else event.data}"
                )

                if event.event in ("partial", "fly") and event.data:
                    data = json.loads(event.data)
                    # Unwrap the {"payload": ...} wrapper from runtime SSE
                    if "payload" in data and len(data) == 1:
                        data = data["payload"]
                    result["partial"].append(data)
                elif event.event in ("update", "status") and event.data:
                    data = json.loads(event.data)

                    if "actor" not in data and "current_actor_name" in data:
                        data["actor"] = data["current_actor_name"]

                    result["update"].append(data)

                    if data.get("status") in ["succeeded", "failed", "canceled"]:
                        logger.debug(f"Final status reached: {data.get('status')}")
                        break

        except Exception as e:
            logger.debug(f"SSE stream ended with exception: {e}")

        logger.debug(
            f"SSE stream complete. Received {len(result['partial'])} partial events, {len(result['update'])} updates"
        )
        return result

    def stream_task_events_live(
        self,
        task_id: str,
        timeout: int = 30,
    ) -> dict[str, list]:
        """
        Stream task events via SSE in real-time, collecting partial and update events.
        Connects immediately and blocks until terminal status or timeout.

        Use this for ephemeral FLY events that are not persisted for replay.
        """
        logger.debug(f"Starting live SSE stream for task: {task_id}")
        result: dict[str, list] = {"partial": [], "update": []}

        response = requests.get(
            f"{self.tasks_url}/{task_id}/events",
            stream=True,
            timeout=timeout,
            headers={"Accept": "text/event-stream"},
        )
        response.raise_for_status()

        client = SSEClient(response)

        try:
            for event in client.events():
                logger.debug(
                    f"SSE event type={event.event} data={event.data[:100] if event.data and len(event.data) > 100 else event.data}"
                )

                if event.event in ("partial", "fly") and event.data:
                    data = json.loads(event.data)
                    if "payload" in data and len(data) == 1:
                        data = data["payload"]
                    result["partial"].append(data)
                elif event.event in ("update", "status") and event.data:
                    data = json.loads(event.data)
                    if "actor" not in data and "current_actor_name" in data:
                        data["actor"] = data["current_actor_name"]
                    result["update"].append(data)

                    if data.get("status") in ["succeeded", "failed", "canceled"]:
                        logger.debug(f"Final status reached: {data.get('status')}")
                        break
        except Exception as e:
            logger.debug(f"SSE stream ended: {e}")

        return result

    def wait_for_task_completion(
        self,
        task_id: str,
        timeout: int = 20,
        interval: float = 0.5,
    ) -> dict:
        """
        Poll task status until it reaches end state.

        Returns the final task object when status is succeeded, failed, or unknown.
        """
        logger.debug(f"Waiting for task completion: {task_id} (timeout={timeout}s)")
        start_time = time.time()

        i = 0
        while time.time() - start_time < timeout:
            task = self.get_task_status(task_id)
            elapsed = time.time() - start_time

            if task["status"] in ["succeeded", "failed", "canceled", "unknown"]:
                logger.info(f"Task completed after {elapsed:.2f}s with status: {task['status']}")
                return task
            i += 1
            if i % int(5 / interval) == 0:
                logger.debug(f"Task still {task['status']} after {elapsed:.2f}s, waiting...")
            time.sleep(interval)  # Polling interval for task completion

        raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")
