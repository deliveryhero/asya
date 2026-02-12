#!/usr/bin/env python3
"""
Integration tests for sidecar retry logic with exponential backoff.

Tests the retry behavior when the sidecar has ASYA_RESILIENCY_* env vars configured.
Three test actors are deployed:

- test-retry-fail: error_handler + retry (max_attempts=3, constant 1s delay)
  Tests retry exhaustion and status field propagation.

- test-retry-nonretryable: error_handler + non_retryable_errors=ValueError
  Tests that ValueError is classified as non-retryable and goes to error-end immediately.

- test-retry-mro: oom_handler + non_retryable_errors=Exception
  Tests MRO-based error classification (MemoryError matches via Exception ancestor).
"""

import json
import logging

import pytest

from asya_testing.config import get_env

logger = logging.getLogger(__name__)


# Queue names
RETRY_FAIL_QUEUE = "asya-default-test-retry-fail"
RETRY_NONRETRYABLE_QUEUE = "asya-default-test-retry-nonretryable"
RETRY_MRO_QUEUE = "asya-default-test-retry-mro"
ERROR_END_QUEUE = "asya-default-error-end"


# ============================================================================
# Retry exhaustion tests (SQS only — requires SendWithDelay)
# ============================================================================


def test_retry_max_attempts_exhausted(transport_helper):
    """Test that after max retry attempts, message goes to error-end with MaxRetriesExhausted.

    The actor is configured with max_attempts=3 and constant 1s delay.
    The handler always raises ValueError, so the sidecar retries 3 times
    then sends to error-end with reason=MaxRetriesExhausted.
    """
    transport = get_env("ASYA_TRANSPORT", "rabbitmq")
    if transport != "sqs":
        pytest.skip("Retry with delay requires SQS transport (RabbitMQ lacks SendWithDelay)")

    transport_helper.purge_queue(ERROR_END_QUEUE)
    message = {
        "id": "test-retry-exhausted-1",
        "route": {"actors": ["test-retry-fail"], "current": 0},
        "payload": {"test": "retry_exhausted"},
    }
    logger.info(f"Publishing message: {json.dumps(message)}")

    transport_helper.publish_message(RETRY_FAIL_QUEUE, message)

    # 3 attempts with 1s delay between each = ~3-5s total processing
    result = transport_helper.get_message(ERROR_END_QUEUE, timeout=30)
    logger.info(f"Result from error-end: {json.dumps(result, indent=2) if result else 'None'}")
    assert result is not None, "No message in error-end after retry exhaustion"

    # Verify status fields
    status = result.get("status", {})
    assert status.get("phase") == "failed", f"Expected phase=failed, got {status.get('phase')}"
    assert status.get("reason") == "MaxRetriesExhausted", f"Expected reason=MaxRetriesExhausted, got {status.get('reason')}"
    assert status.get("attempt") == 3, f"Expected attempt=3, got {status.get('attempt')}"
    assert status.get("max_attempts") == 3, f"Expected max_attempts=3, got {status.get('max_attempts')}"
    assert status.get("actor") == "test-retry-fail", f"Expected actor=test-retry-fail, got {status.get('actor')}"

    # Verify error details in status
    error_info = status.get("error", {})
    assert error_info.get("type") == "ValueError", f"Expected error type=ValueError, got {error_info.get('type')}"
    assert "Intentional test failure" in error_info.get("message", ""), f"Error message missing, got: {error_info.get('message')}"

    # Verify original payload is preserved
    payload = result.get("payload", {})
    original = payload.get("original_payload", {})
    assert original.get("test") == "retry_exhausted", f"Original payload not preserved, got: {original}"
    logger.info("=== test_retry_max_attempts_exhausted: PASSED ===")


def test_retry_status_timestamps(transport_helper):
    """Test that status timestamps are populated correctly after retry exhaustion."""
    transport = get_env("ASYA_TRANSPORT", "rabbitmq")
    if transport != "sqs":
        pytest.skip("Retry with delay requires SQS transport (RabbitMQ lacks SendWithDelay)")

    transport_helper.purge_queue(ERROR_END_QUEUE)
    message = {
        "id": "test-retry-timestamps-1",
        "route": {"actors": ["test-retry-fail"], "current": 0},
        "payload": {"test": "retry_timestamps"},
    }

    transport_helper.publish_message(RETRY_FAIL_QUEUE, message)

    result = transport_helper.get_message(ERROR_END_QUEUE, timeout=30)
    assert result is not None, "No message in error-end after retry"

    status = result.get("status", {})
    assert "created_at" in status, "Missing created_at timestamp"
    assert "updated_at" in status, "Missing updated_at timestamp"
    assert status["created_at"] <= status["updated_at"], "created_at should be <= updated_at"

    # Error traceback should be present
    error_info = status.get("error", {})
    assert "traceback" in error_info, "Missing traceback in error details"
    assert len(error_info["traceback"]) > 0, "Traceback should not be empty"
    logger.info("=== test_retry_status_timestamps: PASSED ===")


# ============================================================================
# Non-retryable error tests (both transports)
# ============================================================================


def test_retry_non_retryable_error(transport_helper):
    """Test that non-retryable errors go to error-end immediately without retry.

    The actor has non_retryable_errors=ValueError configured, so ValueError
    from error_handler is classified as non-retryable and sent directly
    to error-end with reason=NonRetryableFailure.
    """
    transport_helper.purge_queue(ERROR_END_QUEUE)
    message = {
        "id": "test-nonretryable-1",
        "route": {"actors": ["test-retry-nonretryable"], "current": 0},
        "payload": {"test": "non_retryable"},
    }
    logger.info(f"Publishing message: {json.dumps(message)}")

    transport_helper.publish_message(RETRY_NONRETRYABLE_QUEUE, message)

    result = transport_helper.get_message(ERROR_END_QUEUE, timeout=10)
    logger.info(f"Result from error-end: {json.dumps(result, indent=2) if result else 'None'}")
    assert result is not None, "Non-retryable error not routed to error-end"

    status = result.get("status", {})
    assert status.get("phase") == "failed", f"Expected phase=failed, got {status.get('phase')}"
    assert status.get("reason") == "NonRetryableFailure", f"Expected reason=NonRetryableFailure, got {status.get('reason')}"
    assert status.get("attempt") == 1, f"Expected attempt=1 (no retries), got {status.get('attempt')}"
    assert status.get("max_attempts") == 3, f"Expected max_attempts=3 (from config), got {status.get('max_attempts')}"

    # Verify error type matches configured non-retryable error
    error_info = status.get("error", {})
    assert error_info.get("type") == "ValueError", f"Expected error type=ValueError, got {error_info.get('type')}"
    logger.info("=== test_retry_non_retryable_error: PASSED ===")


def test_retry_non_retryable_via_mro(transport_helper):
    """Test MRO-based non-retryable error classification.

    The actor has non_retryable_errors=Exception configured and the handler
    raises MemoryError. MemoryError's MRO includes Exception, so the sidecar
    classifies it as non-retryable via ancestor match and sends directly to error-end.
    """
    transport_helper.purge_queue(ERROR_END_QUEUE)
    message = {
        "id": "test-mro-nonretryable-1",
        "route": {"actors": ["test-retry-mro"], "current": 0},
        "payload": {"test": "mro_classification"},
    }
    logger.info(f"Publishing message: {json.dumps(message)}")

    transport_helper.publish_message(RETRY_MRO_QUEUE, message)

    result = transport_helper.get_message(ERROR_END_QUEUE, timeout=10)
    logger.info(f"Result from error-end: {json.dumps(result, indent=2) if result else 'None'}")
    assert result is not None, "MRO-classified non-retryable error not in error-end"

    status = result.get("status", {})
    assert status.get("phase") == "failed", f"Expected phase=failed, got {status.get('phase')}"
    assert status.get("reason") == "NonRetryableFailure", f"Expected reason=NonRetryableFailure, got {status.get('reason')}"
    assert status.get("attempt") == 1, f"Expected attempt=1 (no retries), got {status.get('attempt')}"

    # Error type is MemoryError, matched via MRO ancestor "Exception"
    error_info = status.get("error", {})
    assert error_info.get("type") == "MemoryError", f"Expected error type=MemoryError, got {error_info.get('type')}"

    # MRO should contain "Exception" (the configured non-retryable match)
    mro = error_info.get("mro", [])
    assert "Exception" in mro, f"Expected 'Exception' in MRO, got {mro}"
    logger.info("=== test_retry_non_retryable_via_mro: PASSED ===")


# ============================================================================
# Transport fallback tests (RabbitMQ only)
# ============================================================================


def test_retry_delay_not_supported_fallback(transport_helper):
    """Test that when SendWithDelay is not supported, message goes to error-end.

    RabbitMQ transport returns ErrDelayNotSupported for SendWithDelay.
    The sidecar falls back to sending the message to error-end immediately.
    """
    transport = get_env("ASYA_TRANSPORT", "rabbitmq")
    if transport != "rabbitmq":
        pytest.skip("This test verifies RabbitMQ fallback for unsupported delay")

    transport_helper.purge_queue(ERROR_END_QUEUE)
    message = {
        "id": "test-delay-fallback-1",
        "route": {"actors": ["test-retry-fail"], "current": 0},
        "payload": {"test": "delay_fallback"},
    }
    logger.info(f"Publishing message: {json.dumps(message)}")

    transport_helper.publish_message(RETRY_FAIL_QUEUE, message)

    result = transport_helper.get_message(ERROR_END_QUEUE, timeout=10)
    logger.info(f"Result from error-end: {json.dumps(result, indent=2) if result else 'None'}")
    assert result is not None, "RabbitMQ fallback not routed to error-end"

    status = result.get("status", {})
    assert status.get("phase") == "failed", f"Expected phase=failed, got {status.get('phase')}"
    # SendWithDelay failure falls back with RuntimeError reason
    assert status.get("reason") == "RuntimeError", f"Expected reason=RuntimeError, got {status.get('reason')}"
    # retryMessage() increments attempt before calling SendWithDelay, so attempt=2
    assert status.get("attempt") == 2, f"Expected attempt=2, got {status.get('attempt')}"
    logger.info("=== test_retry_delay_not_supported_fallback: PASSED ===")
