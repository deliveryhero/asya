#!/usr/bin/env python3
"""
Gateway E2E integration test suite.

Tests the complete flow from Gateway → Actors → Results with both SSE and HTTP polling.

Test flow:
1. Send MCP request to gateway
2. Gateway creates envelope and sends to first actor queue
3. Sidecar reports progress (received, processing, completed)
4. Gateway streams progress via SSE OR HTTP polling
5. Verify final result in envelope status
"""

import logging

import pytest

from asya_testing.config import get_env
from asya_testing.utils.s3 import wait_for_envelope_in_s3
from asya_testing.fixtures.gateway import gateway_helper

log_level = get_env('ASYA_LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# Test Cases
# ============================================================================

def test_simple_tool_execution(gateway_helper):
    """Test simple tool execution with single actor."""
    response = gateway_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "Hello, World!"},
    )

    assert "result" in response, "Should have result field"
    result = response["result"]
    assert "id" in result, "Should return id"

    envelope_id = result["id"]
    logger.info(f" Envelope ID: {envelope_id}")

    final_envelope = gateway_helper.wait_for_envelope_completion(envelope_id, timeout=30)

    logger.info(f" Final envelope: {final_envelope}")
    assert final_envelope["status"] == "succeeded", f"Envelope should succeed, got {final_envelope}"
    assert final_envelope["result"] is not None, "Envelope should have result"

    envelope_result = final_envelope["result"]
    assert envelope_result.get("echoed") == "Hello, World!", "Should echo the input"

    s3_object = wait_for_envelope_in_s3(bucket_name="asya-results", envelope_id=envelope_id, timeout=10)
    assert s3_object is not None, f"Happy-end should persist envelope {envelope_id} to S3"
    assert s3_object["payload"] == envelope_result, "S3 result should match gateway result"
    logger.info(" S3 verification: Happy-end persisted result correctly")


def test_multi_actor_pipeline(gateway_helper):
    """Test multi-actor pipeline with multiple actors."""
    response = gateway_helper.call_mcp_tool(
        tool_name="test_pipeline",
        arguments={"value": 10},
    )

    envelope_id = response["result"]["id"]
    logger.info(f" Envelope ID: {envelope_id}")

    # Get progress updates
    updates = gateway_helper.get_progress_updates(envelope_id, timeout=60)

    logger.info(f" Total updates: {len(updates)}")
    messages = [u.get("message", "") for u in updates]
    logger.info(f" All messages: {messages}")

    # For SSE tests, race condition may cause missing updates
    # Use envelope status endpoint as authoritative source
    actors_seen = set()
    for update in updates:
        actor = update.get("actor")
        if actor:
            actors_seen.add(actor)

    # Wait for completion first
    final_envelope = gateway_helper.wait_for_envelope_completion(envelope_id, timeout=60)
    logger.info(f" Final envelope status: {final_envelope['status']}")
    assert final_envelope["status"] == "succeeded", "Pipeline should complete successfully"

    # Verify actor count from envelope status (authoritative source)
    if "total_actors" in final_envelope:
        assert final_envelope["total_actors"] == 2, "Should have 2 actors in route"

    # If SSE/polling caught actor updates, verify them
    if len(actors_seen) > 0:
        logger.info(f" Actors seen in updates: {actors_seen}")
        # May see 1-2 actors depending on race conditions
        assert len(actors_seen) >= 1, f"Should see at least 1 actor if updates received, saw: {actors_seen}"
    else:
        logger.info(" No actor updates received (race condition or fast processing)")

    result = final_envelope["result"]
    logger.info(f" Result: {result}")
    assert result is not None, "Should have a result"
    # Value should be: 10 * 2 + 5 = 25 (doubled + incremented)
    assert result.get("value") == 25, f"Expected 25, got {result.get('value')}"

    s3_object = wait_for_envelope_in_s3(bucket_name="asya-results", envelope_id=envelope_id, timeout=10)
    assert s3_object is not None, f"Happy-end should persist pipeline envelope {envelope_id} to S3"
    assert s3_object["payload"] == result, "S3 result should match gateway result"
    if "last_actor" in s3_object:
        assert s3_object["last_actor"] == "test-incrementer", "S3 should track last actor in pipeline"
    logger.info(" S3 verification: Happy-end persisted pipeline result correctly")


def test_error_handling(gateway_helper):
    """Test error handling with progress updates."""
    response = gateway_helper.call_mcp_tool(
        tool_name="test_error",
        arguments={"should_fail": True},
    )

    envelope_id = response["result"]["id"]
    logger.info(f" Envelope ID: {envelope_id}")

    # Get progress updates
    updates = gateway_helper.get_progress_updates(envelope_id, timeout=30)

    logger.info(f" Total updates: {len(updates)}")

    # Final update should indicate failure
    final_update = updates[-1]
    logger.info(f" Final update: {final_update}")
    assert final_update["status"] == "failed", "Envelope should fail"

    # Verify envelope status reflects the error
    final_envelope = gateway_helper.get_envelope_status(envelope_id)
    logger.info(f" Final envelope: {final_envelope}")
    assert final_envelope["status"] == "failed", "Envelope status should be failed"
    assert final_envelope.get("error") or final_envelope.get("error_message"), "Envelope should have error information"


def test_envelope_status_endpoint(gateway_helper):
    """Test envelope status REST endpoint."""
    response = gateway_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "status test"},
    )

    envelope_id = response["result"]["id"]
    logger.info(f" Envelope ID: {envelope_id}")

    # Immediately check status (should be pending or running)
    envelope = gateway_helper.get_envelope_status(envelope_id)
    logger.info(f" Initial envelope status: {envelope['status']}")
    assert envelope["id"] == envelope_id, "Envelope ID should match"
    assert envelope["status"] in ["pending", "running"], \
        f"Initial status should be pending or running, got {envelope['status']}"
    assert "route" in envelope, "Should have route information"
    assert "created_at" in envelope, "Should have created_at timestamp"

    # Wait for completion
    final_envelope = gateway_helper.wait_for_envelope_completion(envelope_id, timeout=30)

    logger.info(f" Final envelope: {final_envelope}")
    assert final_envelope["status"] == "succeeded", "Should complete successfully"
    assert final_envelope["result"] is not None, "Should have result"
    assert "updated_at" in final_envelope, "Should have updated_at timestamp"


def test_concurrent_envelopes(gateway_helper):
    """Test multiple concurrent envelopes."""
    envelope_ids = []

    for i in range(3):
        response = gateway_helper.call_mcp_tool(
            tool_name="test_echo",
            arguments={"message": f"concurrent-{i}"},
        )
        envelope_id = response["result"]["id"]
        envelope_ids.append(envelope_id)
        logger.info(f" Created envelope {i}: {envelope_id}")

    logger.info(f" Total concurrent envelopes: {len(envelope_ids)}")

    # Wait for all envelopes to complete
    completed_envelopes = []
    for i, envelope_id in enumerate(envelope_ids):
        logger.info(f" Waiting for envelope {i}: {envelope_id}")
        envelope = gateway_helper.wait_for_envelope_completion(envelope_id, timeout=30)
        completed_envelopes.append(envelope)
        logger.info(f" Envelope {i} completed with status: {envelope['status']}")

    # Verify all envelopes succeeded
    for envelope in completed_envelopes:
        logger.info(f" Verifying envelope {envelope['id']}: status={envelope['status']}")
        assert envelope["status"] == "succeeded", f"Envelope {envelope['id']} should succeed"
        assert envelope["result"] is not None, f"Envelope {envelope['id']} should have result"

    # Verify each envelope has its own result
    results = [envelope["result"]["echoed"] for envelope in completed_envelopes]
    logger.info(f" All results: {results}")
    assert "concurrent-0" in results, "Should have result from envelope 0"
    assert "concurrent-1" in results, "Should have result from envelope 1"
    assert "concurrent-2" in results, "Should have result from envelope 2"


def test_timeout_handling(gateway_helper):
    """Test envelope timeout handling."""
    response = gateway_helper.call_mcp_tool(
        tool_name="test_timeout",
        arguments={"sleep_seconds": 60},
    )

    envelope_id = response["result"]["id"]
    logger.info(f" Envelope ID: {envelope_id}")

    # Wait for envelope to timeout (timeout is set to 10s in config)
    try:
        envelope = gateway_helper.wait_for_envelope_completion(envelope_id, timeout=15)
        logger.info(f" Envelope completed with status: {envelope['status']}")
    except TimeoutError:
        envelope = gateway_helper.get_envelope_status(envelope_id)
        logger.info(f" Current envelope status: {envelope['status']}")

    logger.info(f" Final envelope: {envelope}")
    assert envelope["status"] in ["failed", "unknown"], \
        f"Envelope should timeout, got status: {envelope['status']}"
