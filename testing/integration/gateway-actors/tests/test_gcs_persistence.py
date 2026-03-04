"""
Integration tests for GCS persistence in x-sink and x-sump actors.

Tests that end actors properly persist results and errors to GCS (fake-gcs-server).
The checkpointer stores complete message envelopes (metadata + payload) as JSON objects.
"""

import json
import logging
import os
import time

import pytest
import requests

storage = os.getenv("ASYA_STORAGE", "s3")
if storage != "gcs":
    pytest.skip("GCS persistence tests only run with GCS storage", allow_module_level=True)

from asya_testing.utils.gcs import delete_all_objects_in_bucket, wait_for_envelope_in_gcs

from asya_testing.config import require_env

logger = logging.getLogger(__name__)

ASYA_GATEWAY_URL = require_env("ASYA_GATEWAY_URL")
RESULTS_BUCKET = "asya-results"
ERRORS_BUCKET = "asya-errors"


@pytest.fixture(autouse=True)
def cleanup_gcs():
    """Clean up GCS buckets before and after each test."""
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
    text_content = mcp_result["content"][0].get("text", "")
    response_data = json.loads(text_content)
    task_id = response_data.get("task_id")
    if not task_id:
        raise ValueError(f"Could not extract task_id from response: {mcp_result}")
    return task_id


def get_task_status(task_id: str) -> dict:
    """Get task status from gateway."""
    response = requests.get(f"{ASYA_GATEWAY_URL}/mesh/{task_id}", timeout=5)
    response.raise_for_status()
    return response.json()


def wait_for_completion(task_id: str, timeout: int = 60) -> dict:
    """Wait for task to complete."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        task = get_task_status(task_id)
        if task["status"] in ["succeeded", "failed", "unknown"]:
            return task
        time.sleep(0.5)  # Poll gateway for task completion
    raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")


def test_x_sink_persists_to_gcs():
    """
    Test that x-sink actor persists successful results to GCS.

    Inventory:
    - Submit echo request via gateway
    - Wait for completion
    - Verify result saved to asya-results bucket
    - Verify GCS object structure matches checkpointer envelope schema
    """
    logger.info("=== test_x_sink_persists_to_gcs ===")

    task_id = call_mcp_tool("test_echo", {"message": "test gcs persistence"})
    logger.info(f"Created task {task_id}")

    final_task = wait_for_completion(task_id, timeout=60)
    assert final_task["status"] == "succeeded", f"Task failed: {final_task}"

    logger.info(f"Task {task_id} completed successfully")

    gcs_object = wait_for_envelope_in_gcs(RESULTS_BUCKET, task_id, timeout=15)

    assert gcs_object is not None, f"Envelope {task_id} not found in {RESULTS_BUCKET}"
    assert isinstance(gcs_object, dict), f"GCS object should be a dict, got {type(gcs_object)}"
    assert gcs_object["id"] == task_id, f"Expected envelope id {task_id}, got {gcs_object.get('id')}"
    assert "payload" in gcs_object, f"GCS object missing 'payload' key: {gcs_object}"
    assert gcs_object["payload"]["echoed"] == "test gcs persistence", (
        f"Expected echoed message in payload, got {gcs_object['payload']}"
    )

    logger.info(f"GCS envelope validated: {gcs_object}")
    logger.info("=== test_x_sink_persists_to_gcs: PASSED ===")


def test_x_sump_persists_to_gcs():
    """
    Test that x-sump actor persists errors to GCS.

    Inventory:
    - Submit request that triggers error
    - Wait for failure
    - Verify error saved to asya-errors bucket
    - Verify GCS object structure includes envelope metadata
    """
    logger.info("=== test_x_sump_persists_to_gcs ===")

    task_id = call_mcp_tool("test_error", {"should_fail": True})
    logger.info(f"Created task {task_id}")

    final_task = wait_for_completion(task_id, timeout=60)
    assert final_task["status"] == "failed", f"Expected failure but got: {final_task}"

    logger.info(f"Task {task_id} failed as expected")

    gcs_object = wait_for_envelope_in_gcs(ERRORS_BUCKET, task_id, timeout=15)

    assert gcs_object is not None, f"Envelope {task_id} not found in {ERRORS_BUCKET}"
    assert isinstance(gcs_object, dict), f"GCS object should be a dict, got {type(gcs_object)}"
    assert gcs_object["id"] == task_id, f"Expected envelope id {task_id}, got {gcs_object.get('id')}"
    assert "payload" in gcs_object, f"GCS object missing 'payload' key: {gcs_object}"

    logger.info(f"GCS error envelope validated: {gcs_object}")
    logger.info("=== test_x_sump_persists_to_gcs: PASSED ===")


def test_pipeline_result_persists_to_gcs():
    """
    Test that multi-actor pipeline results are persisted to GCS.

    Inventory:
    - Submit pipeline request (doubler + incrementer: 10*2=20, 20+5=25)
    - Wait for completion
    - Verify final result saved to asya-results bucket
    - Verify payload contains expected pipeline output
    """
    logger.info("=== test_pipeline_result_persists_to_gcs ===")

    task_id = call_mcp_tool("test_pipeline", {"value": 10})
    logger.info(f"Created pipeline task {task_id}")

    final_task = wait_for_completion(task_id, timeout=60)
    assert final_task["status"] == "succeeded", f"Pipeline failed: {final_task}"

    logger.info(f"Pipeline task {task_id} completed successfully")

    gcs_object = wait_for_envelope_in_gcs(RESULTS_BUCKET, task_id, timeout=15)

    assert gcs_object is not None, f"Envelope {task_id} not found in {RESULTS_BUCKET}"
    assert isinstance(gcs_object, dict), f"GCS object should be a dict, got {type(gcs_object)}"
    assert gcs_object["id"] == task_id, f"Expected envelope id {task_id}, got {gcs_object.get('id')}"
    assert "payload" in gcs_object, f"GCS object missing 'payload' key: {gcs_object}"
    assert gcs_object["payload"]["value"] == 25, (
        f"Expected pipeline result value 25, got {gcs_object['payload'].get('value')}"
    )

    logger.info(f"Pipeline GCS envelope validated: {gcs_object}")
    logger.info("=== test_pipeline_result_persists_to_gcs: PASSED ===")
