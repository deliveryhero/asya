"""Integration tests for pause/resume flow end-to-end.

Tests the full lifecycle:
  1. Call MCP tool with route [test-echo, x-pause, test-incrementer]
  2. test-echo processes the payload
  3. x-pause persists state and signals pause via x-asya-pause header
  4. Gateway transitions task to "paused"
  5. Client sends A2A resume with new input
  6. x-resume loads persisted state, merges user input, restores route
  7. test-incrementer processes merged payload
  8. x-sink stores final result, gateway shows "succeeded"
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)


def _poll_for_status(helper, task_id, target_status, timeout=30, interval=0.5):
    """Poll task status until it matches target_status or times out."""
    start = time.time()
    while time.time() - start < timeout:
        task = helper.get_task_status(task_id)
        if task["status"] == target_status:
            return task
        time.sleep(interval)  # Poll gateway for target task status
    raise TimeoutError(
        f"Task {task_id} did not reach '{target_status}' within {timeout}s "
        f"(last status: {task['status']})"
    )


def _send_a2a_resume(gateway_url, task_id, skill, resume_data):
    """Send A2A JSON-RPC message/send to resume a paused task."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "message/send",
        "params": {
            "skill": skill,
            "taskId": task_id,
            "message": {
                "role": "user",
                "parts": [{"type": "data", "data": resume_data}],
            },
        },
    }
    resp = requests.post(f"{gateway_url}/a2a/", json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


class TestPauseResumeFlow:
    """End-to-end tests for the pause/resume lifecycle."""

    def test_basic_pause_and_resume(self, gateway_helper):
        """Test that a pipeline pauses at x-pause and resumes through to completion."""
        # 1. Trigger pipeline: test-echo -> x-pause -> test-incrementer
        result = gateway_helper.call_mcp_tool(
            "test_pause_resume",
            {"message": "pause-resume-test"},
        )
        task_id = result["result"]["task_id"]
        assert task_id, "Expected task_id in MCP tool response"
        logger.info(f"Task created: {task_id}")

        # 2. Wait for task to reach "paused" status
        paused_task = _poll_for_status(gateway_helper, task_id, "paused", timeout=30)
        assert paused_task["status"] == "paused"
        logger.info(f"Task paused: {task_id}")

        # 3. Verify pause_metadata is present
        assert "pause_metadata" in paused_task, "Expected pause_metadata on paused task"

        # 4. Send resume via A2A protocol with additional data
        resume_data = {"approved": True, "reviewer": "integration-test"}
        resume_resp = _send_a2a_resume(
            gateway_helper.gateway_url,
            task_id,
            "test_pause_resume",
            resume_data,
        )
        logger.info(f"Resume response: {resume_resp}")

        # Verify A2A response structure
        assert "result" in resume_resp, f"Expected 'result' in A2A response: {resume_resp}"
        assert "error" not in resume_resp, f"Unexpected error in A2A response: {resume_resp}"

        # 5. Wait for task to reach "succeeded"
        final_task = gateway_helper.wait_for_task_completion(task_id, timeout=30)
        assert final_task["status"] == "succeeded", (
            f"Expected 'succeeded' but got '{final_task['status']}': {final_task}"
        )
        logger.info(f"Task succeeded: {task_id}")

    def test_pause_has_correct_metadata(self, gateway_helper):
        """Test that pause metadata includes prompt and fields from the handler."""
        result = gateway_helper.call_mcp_tool(
            "test_pause_resume",
            {"message": "metadata-check"},
        )
        task_id = result["result"]["task_id"]

        paused_task = _poll_for_status(gateway_helper, task_id, "paused", timeout=30)

        # Default pause metadata has prompt and empty fields
        meta = paused_task["pause_metadata"]
        assert "prompt" in meta, f"Expected 'prompt' in pause_metadata: {meta}"
        assert "fields" in meta, f"Expected 'fields' in pause_metadata: {meta}"

        # Resume to clean up
        _send_a2a_resume(
            gateway_helper.gateway_url,
            task_id,
            "test_pause_resume",
            {"cleanup": True},
        )
        final = gateway_helper.wait_for_task_completion(task_id, timeout=30)
        assert final["status"] == "succeeded"

    def test_resume_merges_user_input(self, gateway_helper):
        """Test that x-resume merges resume data into the paused payload."""
        result = gateway_helper.call_mcp_tool(
            "test_pause_resume",
            {"message": "merge-test", "value": 10},
        )
        task_id = result["result"]["task_id"]

        _poll_for_status(gateway_helper, task_id, "paused", timeout=30)

        # Resume with additional fields
        _send_a2a_resume(
            gateway_helper.gateway_url,
            task_id,
            "test_pause_resume",
            {"extra_field": "from-resume"},
        )

        # test-incrementer adds 5 to "value" and sets operation="incremented"
        final = gateway_helper.wait_for_task_completion(task_id, timeout=30)
        assert final["status"] == "succeeded", (
            f"Expected 'succeeded' but got '{final['status']}': {final}"
        )
        result_payload = final.get("result", {})
        assert result_payload.get("extra_field") == "from-resume", (
            f"Resume data 'extra_field' not merged into result: {result_payload}"
        )
        assert result_payload.get("value") == 15, (
            f"Expected value=15 (10+5 from incrementer), got: {result_payload.get('value')}"
        )

    def test_resume_nonexistent_task_fails(self, gateway_helper):
        """Test that resuming a non-paused task returns an error."""
        resume_resp = _send_a2a_resume(
            gateway_helper.gateway_url,
            "00000000-0000-0000-0000-000000000000",
            "test_pause_resume",
            {"data": "should-fail"},
        )
        # A2A should return a JSON-RPC error for non-existent tasks
        assert "error" in resume_resp, (
            f"Expected error for nonexistent task resume, but got: {resume_resp}"
        )
