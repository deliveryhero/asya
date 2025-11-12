"""
Gateway test helper for integration and E2E tests.

Provides functionality for:
- Calling MCP tools via REST API
- Getting envelope status
- Waiting for envelope completion
- Streaming SSE progress updates
- HTTP polling for progress

FAIL-FAST: ASYA_GATEWAY_URL must be set by docker-compose.
"""

import json
import logging
import re
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
    - Getting envelope status
    - Waiting for envelope completion
    - Streaming SSE progress updates
    """

    def __init__(
        self,
        gateway_url: str | None = None,
        progress_method: str = "sse",
    ):
        if gateway_url is None:
            gateway_url = require_env("ASYA_GATEWAY_URL")
        self.gateway_url = gateway_url
        self.tools_url = f"{gateway_url}/tools/call"
        self.envelopes_url = f"{gateway_url}/envelopes"
        self.progress_method = progress_method
        logger.debug(f"Initialized GatewayTestHelper with progress_method={progress_method}")

    def call_mcp_tool(
        self,
        tool_name: str,
        arguments: dict,
        timeout: int = 10,
    ) -> dict:
        """
        Call an MCP tool via REST API.

        Returns dict with structure:
        {
            "result": {
                "envelope_id": "<uuid>",  # or "id" for compatibility
                "message": "<response text>"
            }
        }
        """
        logger.debug(f"Calling tool: {tool_name} with arguments: {arguments}")

        payload = {
            "name": tool_name,
            "arguments": arguments,
        }

        response = requests.post(
            self.tools_url,
            json=payload,
            timeout=timeout,
        )
        logger.debug(f"Tool call response status: {response.status_code}")
        response.raise_for_status()

        mcp_result = response.json()
        logger.debug(f"MCP result: {mcp_result}")

        if mcp_result.get("isError", False):
            error_text = ""
            if "content" in mcp_result and len(mcp_result["content"]) > 0:
                error_text = mcp_result["content"][0].get("text", "")
            raise RuntimeError(f"MCP tool call failed: {error_text}")

        text_content = ""
        if "content" in mcp_result and len(mcp_result["content"]) > 0:
            text_content = mcp_result["content"][0].get("text", "")

        envelope_id = None
        response_data = {}

        try:
            response_data = json.loads(text_content)
            envelope_id = response_data.get("envelope_id")
            logger.debug(f"Extracted envelope_id from JSON: {envelope_id}")
        except (json.JSONDecodeError, ValueError):
            logger.warning(f"Could not parse response as JSON, falling back to regex: {text_content[:100]}")
            if "Envelope created successfully with ID:" in text_content:
                match = re.search(r"ID: ([a-f0-9-]+)", text_content)
                if match:
                    envelope_id = match.group(1)
                    logger.debug(f"Extracted envelope_id via regex: {envelope_id}")
                    response_data = {"message": text_content}

        return {
            "result": {
                "envelope_id": envelope_id,
                "id": envelope_id,
                "message": response_data.get("message", text_content),
                "status_url": response_data.get("status_url"),
                "stream_url": response_data.get("stream_url"),
                "metadata": response_data.get("metadata"),
            }
        }

    def get_envelope_status(self, envelope_id: str, timeout: int = 5) -> dict:
        """Get envelope status via REST API."""
        logger.debug(f"Getting envelope status for: {envelope_id}")
        response = requests.get(f"{self.envelopes_url}/{envelope_id}", timeout=timeout)
        response.raise_for_status()
        envelope_status = response.json()
        logger.debug(f"Envelope status: {envelope_status}")
        return envelope_status

    def stream_envelope_progress(
        self,
        envelope_id: str,
        timeout: int = 30,
    ) -> list[dict]:
        """
        Stream envelope progress via SSE.

        Returns list of all progress update events (event="update") received before completion.
        """
        logger.debug(f"Starting SSE stream for envelope: {envelope_id}")
        updates = []

        response = requests.get(
            f"{self.envelopes_url}/{envelope_id}/stream",
            stream=True,
            timeout=timeout,
            headers={"Accept": "text/event-stream"},
        )
        response.raise_for_status()
        logger.debug(f"SSE stream connected, status: {response.status_code}")

        client = SSEClient(response)

        try:
            for event in client.events():
                if event.event == "update" and event.data:
                    data = json.loads(event.data)
                    logger.debug(
                        f"SSE event: {event.event} data={event.data[:100] if len(event.data) > 100 else event.data}"
                    )

                    if "actor" not in data and "current_actor_name" in data:
                        data["actor"] = data["current_actor_name"]

                    updates.append(data)

                    if data.get("status") in ["succeeded", "failed"]:
                        logger.debug(f"Final status reached: {data.get('status')}")
                        break

        except Exception as e:
            logger.debug(f"SSE stream ended with exception: {e}")

        logger.debug(f"SSE stream complete. Received {len(updates)} updates")
        return updates

    def stream_progress_updates(
        self,
        envelope_id: str,
        timeout: int = 30,
    ) -> list[dict]:
        """
        Alias for stream_envelope_progress for backward compatibility.
        """
        return self.stream_envelope_progress(envelope_id, timeout)

    def poll_envelope_progress(
        self,
        envelope_id: str,
        timeout: int = 30,
        interval: float = 0.5,
    ) -> list[dict]:
        """
        Poll envelope status via HTTP until completion.

        Returns list of all status updates collected during polling.
        """
        logger.debug(f"Starting HTTP polling for envelope: {envelope_id}")
        updates: list[dict] = []
        start_time = time.time()

        while time.time() - start_time < timeout:
            envelope = self.get_envelope_status(envelope_id)
            elapsed = time.time() - start_time

            current_actor = envelope.get("current_actor_name", "")
            progress_percent = envelope.get("progress_percent", 0)
            status = envelope["status"]
            message = envelope.get("message", "")

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

            if envelope["status"] in ["succeeded", "failed", "unknown"]:
                logger.debug(f"Final status reached via HTTP polling: {envelope['status']}")
                break

            time.sleep(interval)  # Polling interval for HTTP progress check

        logger.debug(f"HTTP polling complete. Collected {len(updates)} updates")
        return updates

    def get_progress_updates(
        self,
        envelope_id: str,
        timeout: int = 30,
    ) -> list[dict]:
        """
        Get progress updates using configured method (SSE or HTTP polling).

        Returns list of progress updates in a normalized format.
        """
        if self.progress_method == "sse":
            return self.stream_envelope_progress(envelope_id, timeout)
        else:
            return self.poll_envelope_progress(envelope_id, timeout)

    def wait_for_envelope_completion(
        self,
        envelope_id: str,
        timeout: int = 20,
        interval: float = 0.5,
    ) -> dict:
        """
        Poll envelope status until it reaches end state.

        Returns the final envelope object when status is succeeded, failed, or unknown.
        """
        logger.debug(f"Waiting for envelope completion: {envelope_id} (timeout={timeout}s)")
        start_time = time.time()

        i = 0
        while time.time() - start_time < timeout:
            envelope = self.get_envelope_status(envelope_id)
            elapsed = time.time() - start_time

            if envelope["status"] in ["succeeded", "failed", "unknown"]:
                logger.info(f"Envelope completed after {elapsed:.2f}s with status: {envelope['status']}")
                return envelope
            i += 1
            if i % int(5 / interval) == 0:
                logger.debug(f"Envelope still {envelope['status']} after {elapsed:.2f}s, waiting...")
            time.sleep(interval)  # Polling interval for envelope completion

        raise TimeoutError(f"Envelope {envelope_id} did not complete within {timeout}s")
