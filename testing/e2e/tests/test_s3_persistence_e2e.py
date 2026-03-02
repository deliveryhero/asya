"""
E2E tests for S3 persistence in x-sink and x-sump actors.

Tests that end actors properly persist results and errors to MinIO
in a full Kubernetes deployment.
"""

import logging

import pytest

from asya_testing.utils.s3 import delete_all_objects_in_bucket, wait_for_message_in_s3

logger = logging.getLogger(__name__)

RESULTS_BUCKET = "asya-results"
ERRORS_BUCKET = "asya-errors"


@pytest.fixture(autouse=True)
def cleanup_s3():
    """Clean up S3 buckets before and after each test."""
    try:
        delete_all_objects_in_bucket(RESULTS_BUCKET)
        delete_all_objects_in_bucket(ERRORS_BUCKET)
    except Exception as e:
        logger.warning(f"Failed to clean up S3 before test: {e}")

    yield

    try:
        delete_all_objects_in_bucket(RESULTS_BUCKET)
        delete_all_objects_in_bucket(ERRORS_BUCKET)
    except Exception as e:
        logger.warning(f"Failed to clean up S3 after test: {e}")


@pytest.mark.skip(
    reason="S3 persistence requires state-proxy connector on x-sink",
)
@pytest.mark.fast
def test_x_sink_persists_to_s3_e2e(e2e_helper, transport_timeouts):
    """
    Test that x-sink actor persists successful results to S3 in e2e environment.

    Inventory:
    - Submit echo request via gateway
    - Wait for completion
    - Verify result saved to asya-results bucket
    - Verify S3 object structure matches expected schema
    """
    logger.info("=== test_x_sink_persists_to_s3_e2e ===")

    result = e2e_helper.call_mcp_tool("test_echo", {"message": "test s3 persistence e2e"})
    task_id = result["result"]["task_id"]
    logger.info(f"Created task {task_id}")

    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=transport_timeouts.task_completion_short)
    assert final_task["status"] == "succeeded", f"Task failed: {final_task}"

    logger.info(f"Task {task_id} completed successfully")

    s3_object = wait_for_message_in_s3(RESULTS_BUCKET, task_id, timeout=5)

    assert s3_object is not None, f"Message {task_id} not found in {RESULTS_BUCKET}"
    # S3 stores just the payload dict (not the full message message)
    assert isinstance(s3_object, dict), f"S3 object should be a dict, got {type(s3_object)}"
    assert s3_object.get("echoed") == "test s3 persistence e2e", f"S3 payload should contain echoed message, got {s3_object}"

    logger.info(f"S3 payload validated: {s3_object}")
    logger.info("=== test_x_sink_persists_to_s3_e2e: PASSED ===")


@pytest.mark.skip(
    reason="S3 persistence requires state-proxy connector on x-sump",
)
@pytest.mark.fast
def test_x_sump_persists_to_s3_e2e(e2e_helper, transport_timeouts):
    """
    Test that x-sump actor persists errors to S3 in e2e environment.

    Inventory:
    - Submit request that triggers error
    - Wait for failure
    - Verify error saved to asya-errors bucket
    - Verify S3 object structure includes error details
    """
    logger.info("=== test_x_sump_persists_to_s3_e2e ===")

    result = e2e_helper.call_mcp_tool("test_error", {"should_fail": True})
    task_id = result["result"]["task_id"]
    logger.info(f"Created task {task_id}")

    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=transport_timeouts.task_completion_short)
    assert final_task["status"] == "failed", f"Expected failure but got: {final_task}"

    logger.info(f"Task {task_id} failed as expected")

    s3_object = wait_for_message_in_s3(ERRORS_BUCKET, task_id, timeout=5)

    assert s3_object is not None, f"Message {task_id} not found in {ERRORS_BUCKET}"
    # S3 stores just the payload dict (not the full message message)
    assert isinstance(s3_object, dict), f"S3 object should be a dict, got {type(s3_object)}"

    logger.info(f"S3 error payload validated: {s3_object}")
    logger.info("=== test_x_sump_persists_to_s3_e2e: PASSED ===")
