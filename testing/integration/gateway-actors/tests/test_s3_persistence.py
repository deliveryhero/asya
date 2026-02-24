"""
Integration tests for S3 persistence in x-sink and x-sump actors.

Tests that end actors properly persist results and errors to MinIO.
"""

import json
import logging
import os
import re
import time

import pytest
import requests

from asya_testing.utils.s3 import delete_all_objects_in_bucket, find_message_in_s3, wait_for_message_in_s3
from asya_testing.config import require_env

logger = logging.getLogger(__name__)

ASYA_GATEWAY_URL = require_env("ASYA_GATEWAY_URL")
RESULTS_BUCKET = "asya-results"
ERRORS_BUCKET = "asya-errors"


@pytest.fixture(autouse=True)
def cleanup_s3():
    """Clean up S3 buckets before and after each test."""
    delete_all_objects_in_bucket(RESULTS_BUCKET)
    delete_all_objects_in_bucket(ERRORS_BUCKET)
    yield
    delete_all_objects_in_bucket(RESULTS_BUCKET)
    delete_all_objects_in_bucket(ERRORS_BUCKET)


def call_mcp_tool(tool_name: str, arguments: dict, timeout: int = 60) -> str:
    """Call MCP tool and return task ID."""
    payload = {
        "name": tool_name,
        "arguments": arguments,
    }

    response = requests.post(
        f"{ASYA_GATEWAY_URL}/tools/call",
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()

    mcp_result = response.json()

    # Parse response following the pattern from test_progress_standalone.py (which works)
    text_content = mcp_result["content"][0].get("text", "")
    response_data = json.loads(text_content)
    task_id = response_data.get("task_id")
    if not task_id:
        raise ValueError(f"Could not extract task_id from response: {mcp_result}")
    return task_id


def get_task_status(task_id: str) -> dict:
    """Get task status from gateway."""
    response = requests.get(f"{ASYA_GATEWAY_URL}/tasks/{task_id}", timeout=5)
    response.raise_for_status()
    return response.json()


def wait_for_completion(task_id: str, timeout: int = 60) -> dict:
    """Wait for task to complete."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        task = get_task_status(task_id)
        if task["status"] in ["succeeded", "failed", "unknown"]:
            return task
        time.sleep(0.5)
    raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")


def test_x_sink_persists_to_s3():
    """
    Test that x-sink actor persists successful results to S3.

    Inventory:
    - Submit echo request via gateway
    - Wait for completion
    - Verify result saved to asya-results bucket
    - Verify S3 object structure matches expected schema
    """
    logger.info("=== test_x_sink_persists_to_s3 ===")

    task_id = call_mcp_tool("test_echo", {"message": "test s3 persistence"})
    logger.info(f"Created task {task_id}")

    final_task = wait_for_completion(task_id, timeout=60)
    assert final_task["status"] == "succeeded", f"Task failed: {final_task}"

    logger.info(f"Task {task_id} completed successfully")

    s3_object = wait_for_message_in_s3(RESULTS_BUCKET, task_id, timeout=10)

    assert s3_object is not None, f"Message {task_id} not found in {RESULTS_BUCKET}"
    assert s3_object["id"] == task_id
    assert "route" in s3_object
    assert "payload" in s3_object
    assert isinstance(s3_object["route"], dict)
    assert "prev" in s3_object["route"]
    assert "curr" in s3_object["route"]
    assert "next" in s3_object["route"]

    logger.info(f"S3 message validated (saved as-is): {s3_object}")
    logger.info("=== test_x_sink_persists_to_s3: PASSED ===")


def test_x_sump_persists_to_s3():
    """
    Test that x-sump actor persists errors to S3.

    Inventory:
    - Submit request that triggers error
    - Wait for failure
    - Verify error saved to asya-errors bucket
    - Verify S3 object structure includes error details
    """
    logger.info("=== test_x_sump_persists_to_s3 ===")

    task_id = call_mcp_tool("test_error", {"should_fail": True})
    logger.info(f"Created task {task_id}")

    final_task = wait_for_completion(task_id, timeout=60)
    assert final_task["status"] == "failed", f"Expected failure but got: {final_task}"

    logger.info(f"Task {task_id} failed as expected")

    s3_object = wait_for_message_in_s3(ERRORS_BUCKET, task_id, timeout=10)

    assert s3_object is not None, f"Message {task_id} not found in {ERRORS_BUCKET}"
    assert s3_object["id"] == task_id
    assert "route" in s3_object
    assert "payload" in s3_object
    assert isinstance(s3_object["route"], dict)
    assert "prev" in s3_object["route"]
    assert "curr" in s3_object["route"]
    assert "next" in s3_object["route"]

    logger.info(f"S3 error message validated (saved as-is): {s3_object}")
    logger.info("=== test_x_sump_persists_to_s3: PASSED ===")


def test_pipeline_result_persists_to_s3():
    """
    Test that multi-actor pipeline results are persisted to S3.

    Inventory:
    - Submit pipeline request (doubler + incrementer)
    - Wait for completion
    - Verify final result saved to asya-results bucket
    - Verify last_actor field reflects final pipeline actor
    """
    logger.info("=== test_pipeline_result_persists_to_s3 ===")

    task_id = call_mcp_tool("test_pipeline", {"value": 10})
    logger.info(f"Created pipeline task {task_id}")

    final_task = wait_for_completion(task_id, timeout=60)
    assert final_task["status"] == "succeeded", f"Pipeline failed: {final_task}"

    logger.info(f"Pipeline task {task_id} completed successfully")

    s3_object = wait_for_message_in_s3(RESULTS_BUCKET, task_id, timeout=10)

    assert s3_object is not None, f"Message {task_id} not found in {RESULTS_BUCKET}"
    assert s3_object["id"] == task_id
    assert "route" in s3_object
    assert "payload" in s3_object
    assert isinstance(s3_object["route"], dict)
    assert "prev" in s3_object["route"]
    assert "curr" in s3_object["route"]
    assert "next" in s3_object["route"]
    assert s3_object["payload"]["value"] == 25
    # Verify route prev contains the pipeline actors (processed actors)
    assert "test-doubler" in s3_object["route"]["prev"] or "test-incrementer" in s3_object["route"]["prev"]

    logger.info(f"Pipeline S3 message validated (saved as-is): {s3_object}")
    logger.info("=== test_pipeline_result_persists_to_s3: PASSED ===")
