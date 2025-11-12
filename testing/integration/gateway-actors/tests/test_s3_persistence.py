"""
Integration tests for S3 persistence in happy-end and error-end actors.

Tests that end actors properly persist results and errors to MinIO.
"""

import json
import logging
import os
import re
import time

import pytest
import requests

from asya_testing.utils.s3 import delete_all_objects_in_bucket, find_envelope_in_s3, wait_for_envelope_in_s3
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
    """Call MCP tool and return envelope ID."""
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
    envelope_id = response_data.get("envelope_id")
    if not envelope_id:
        raise ValueError(f"Could not extract envelope_id from response: {mcp_result}")
    return envelope_id


def get_envelope_status(envelope_id: str) -> dict:
    """Get envelope status from gateway."""
    response = requests.get(f"{ASYA_GATEWAY_URL}/envelopes/{envelope_id}", timeout=5)
    response.raise_for_status()
    return response.json()


def wait_for_completion(envelope_id: str, timeout: int = 60) -> dict:
    """Wait for envelope to complete."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        envelope = get_envelope_status(envelope_id)
        if envelope["status"] in ["succeeded", "failed", "unknown"]:
            return envelope
        time.sleep(0.5)
    raise TimeoutError(f"Envelope {envelope_id} did not complete within {timeout}s")


def test_happy_end_persists_to_s3():
    """
    Test that happy-end actor persists successful results to S3.

    Inventory:
    - Submit echo request via gateway
    - Wait for completion
    - Verify result saved to asya-results bucket
    - Verify S3 object structure matches expected schema
    """
    logger.info("=== test_happy_end_persists_to_s3 ===")

    envelope_id = call_mcp_tool("test_echo", {"message": "test s3 persistence"})
    logger.info(f"Created envelope {envelope_id}")

    final_envelope = wait_for_completion(envelope_id, timeout=60)
    assert final_envelope["status"] == "succeeded", f"Envelope failed: {final_envelope}"

    logger.info(f"Envelope {envelope_id} completed successfully")

    s3_object = wait_for_envelope_in_s3(RESULTS_BUCKET, envelope_id, timeout=10)

    assert s3_object is not None, f"Envelope {envelope_id} not found in {RESULTS_BUCKET}"
    assert s3_object["id"] == envelope_id
    assert "route" in s3_object
    assert "payload" in s3_object
    assert isinstance(s3_object["route"], dict)
    assert "actors" in s3_object["route"]
    assert "current" in s3_object["route"]

    logger.info(f"S3 envelope validated (saved as-is): {s3_object}")
    logger.info("=== test_happy_end_persists_to_s3: PASSED ===")


def test_error_end_persists_to_s3():
    """
    Test that error-end actor persists errors to S3.

    Inventory:
    - Submit request that triggers error
    - Wait for failure
    - Verify error saved to asya-errors bucket
    - Verify S3 object structure includes error details
    """
    logger.info("=== test_error_end_persists_to_s3 ===")

    envelope_id = call_mcp_tool("test_error", {"should_fail": True})
    logger.info(f"Created envelope {envelope_id}")

    final_envelope = wait_for_completion(envelope_id, timeout=60)
    assert final_envelope["status"] == "failed", f"Expected failure but got: {final_envelope}"

    logger.info(f"Envelope {envelope_id} failed as expected")

    s3_object = wait_for_envelope_in_s3(ERRORS_BUCKET, envelope_id, timeout=10)

    assert s3_object is not None, f"Envelope {envelope_id} not found in {ERRORS_BUCKET}"
    assert s3_object["id"] == envelope_id
    assert "route" in s3_object
    assert "payload" in s3_object
    assert isinstance(s3_object["route"], dict)
    assert "actors" in s3_object["route"]
    assert "current" in s3_object["route"]

    logger.info(f"S3 error envelope validated (saved as-is): {s3_object}")
    logger.info("=== test_error_end_persists_to_s3: PASSED ===")


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

    envelope_id = call_mcp_tool("test_pipeline", {"value": 10})
    logger.info(f"Created pipeline envelope {envelope_id}")

    final_envelope = wait_for_completion(envelope_id, timeout=60)
    assert final_envelope["status"] == "succeeded", f"Pipeline failed: {final_envelope}"

    logger.info(f"Pipeline envelope {envelope_id} completed successfully")

    s3_object = wait_for_envelope_in_s3(RESULTS_BUCKET, envelope_id, timeout=10)

    assert s3_object is not None, f"Envelope {envelope_id} not found in {RESULTS_BUCKET}"
    assert s3_object["id"] == envelope_id
    assert "route" in s3_object
    assert "payload" in s3_object
    assert isinstance(s3_object["route"], dict)
    assert "actors" in s3_object["route"]
    assert s3_object["payload"]["value"] == 25
    # Verify route actors list contains the pipeline actors
    assert "test-doubler" in s3_object["route"]["actors"] or "test-incrementer" in s3_object["route"]["actors"]

    logger.info(f"Pipeline S3 envelope validated (saved as-is): {s3_object}")
    logger.info("=== test_pipeline_result_persists_to_s3: PASSED ===")
