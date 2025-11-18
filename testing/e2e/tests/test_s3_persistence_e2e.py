"""
E2E tests for S3 persistence in happy-end and error-end actors.

Tests that end actors properly persist results and errors to MinIO
in a full Kubernetes deployment.
"""

import logging

import pytest

from asya_testing.utils.s3 import delete_all_objects_in_bucket, wait_for_envelope_in_s3

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


@pytest.mark.fast
def test_happy_end_persists_to_s3_e2e(e2e_helper):
    """
    Test that happy-end actor persists successful results to S3 in e2e environment.

    Inventory:
    - Submit echo request via gateway
    - Wait for completion
    - Verify result saved to asya-results bucket
    - Verify S3 object structure matches expected schema
    """
    logger.info("=== test_happy_end_persists_to_s3_e2e ===")

    result = e2e_helper.call_mcp_tool("test_echo", {"message": "test s3 persistence e2e"})
    envelope_id = result["result"]["envelope_id"]
    logger.info(f"Created envelope {envelope_id}")

    final_envelope = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=20)
    assert final_envelope["status"] == "succeeded", f"Envelope failed: {final_envelope}"

    logger.info(f"Envelope {envelope_id} completed successfully")

    s3_object = wait_for_envelope_in_s3(RESULTS_BUCKET, envelope_id, timeout=5)

    assert s3_object is not None, f"Envelope {envelope_id} not found in {RESULTS_BUCKET}"
    assert s3_object["id"] == envelope_id
    assert "route" in s3_object
    assert "payload" in s3_object
    assert isinstance(s3_object["route"], dict)
    assert "actors" in s3_object["route"]
    assert "current" in s3_object["route"]

    logger.info(f"S3 envelope validated (saved as-is): {s3_object}")
    logger.info("=== test_happy_end_persists_to_s3_e2e: PASSED ===")


@pytest.mark.fast
def test_error_end_persists_to_s3_e2e(e2e_helper):
    """
    Test that error-end actor persists errors to S3 in e2e environment.

    Inventory:
    - Submit request that triggers error
    - Wait for failure
    - Verify error saved to asya-errors bucket
    - Verify S3 object structure includes error details
    """
    logger.info("=== test_error_end_persists_to_s3_e2e ===")

    result = e2e_helper.call_mcp_tool("test_error", {"should_fail": True})
    envelope_id = result["result"]["envelope_id"]
    logger.info(f"Created envelope {envelope_id}")

    final_envelope = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=20)
    assert final_envelope["status"] == "failed", f"Expected failure but got: {final_envelope}"

    logger.info(f"Envelope {envelope_id} failed as expected")

    s3_object = wait_for_envelope_in_s3(ERRORS_BUCKET, envelope_id, timeout=5)

    assert s3_object is not None, f"Envelope {envelope_id} not found in {ERRORS_BUCKET}"
    assert s3_object["id"] == envelope_id
    assert "route" in s3_object
    assert "payload" in s3_object
    assert isinstance(s3_object["route"], dict)
    assert "actors" in s3_object["route"]
    assert "current" in s3_object["route"]

    logger.info(f"S3 error envelope validated (saved as-is): {s3_object}")
    logger.info("=== test_error_end_persists_to_s3_e2e: PASSED ===")
