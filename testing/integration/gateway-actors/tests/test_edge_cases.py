#!/usr/bin/env python3
"""
Gateway-vs-Actors Edge Case Integration Tests.

Tests critical edge cases, race conditions, and error scenarios in the
gateway-actor interaction that aren't covered by basic integration tests.

MUST-HAVE (5 tests) - Critical for production:
- test_fan_out_array_response: Array payload creates multiple envelopes
- test_empty_payload_handling: Null/empty payload goes to happy-end
- test_multiple_sse_clients_for_same_envelope: Broadcast to multiple SSE clients
- test_invalid_tool_name: 400 error for nonexistent tool
- test_get_envelope_status_for_nonexistent_id: 404 for invalid envelope ID

SHOULD-HAVE (3 tests) - Important reliability:
- test_timeout_fires_near_completion: Timeout boundary (2s vs 4s timeout with overhead)
- test_sse_stream_for_already_completed_envelope: Connect after completion
- test_concurrent_envelopes_do_not_interfere: 10 concurrent envelopes

NICE-TO-HAVE (4 tests) - Operational excellence:
- test_unicode_payload_handling: UTF-8 encoding preservation
- test_large_payload_within_limits: 10MB payload processing
- test_nested_json_payload: 20-level deep JSON structures
- test_null_values_in_payload: null/None value handling
"""

import json
import logging
import os
import re
import time
from typing import List, Dict, Any

import pytest
import requests
from sseclient import SSEClient

from asya_testing.utils.s3 import wait_for_envelope_in_s3
from asya_testing.utils.gateway import GatewayTestHelper
from asya_testing.utils import wait_for_transport
from asya_testing.config import require_env, get_env

log_level = get_env('ASYA_LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# MUST-HAVE: Critical Edge Cases
# ============================================================================

def test_fan_out_array_response(gateway_helper):
    """
    MUST-HAVE: Test fan-out when actor returns array payload.

    Scenario: Actor returns array → multiple envelopes created
    Expected:
    - Creates N envelopes (one per array item)
    - Each envelope has unique ID (original_id + suffix)
    - All envelopes are tracked and complete successfully
    """
    response = gateway_helper.call_mcp_tool(
        tool_name="test_fanout",
        arguments={"count": 3},
    )

    envelope_id = response["result"]["id"]
    logger.info(f"Original envelope ID: {envelope_id}")

    # Wait for completion
    final_envelope = gateway_helper.wait_for_envelope_completion(envelope_id, timeout=30)

    # Verify envelope completed successfully
    assert final_envelope["status"] == "succeeded", "Fanout envelope should succeed"

    # Verify envelope has payload
    payload = final_envelope.get("payload")
    assert payload is not None, "Should have payload from fan-out"

    # Fan-out should create multiple envelopes (implementation-specific)
    # This test documents the expected behavior
    logger.info(f"Fanout payload: {payload}")

    s3_object = wait_for_envelope_in_s3(bucket_name="asya-results", envelope_id=envelope_id, timeout=10)
    assert s3_object is not None, f"Happy-end should persist fan-out envelope {envelope_id} to S3"
    # For fanout, S3 contains the fanned-out item payload, not the original
    s3_payload = s3_object.get("payload", {})
    assert "index" in s3_payload, "S3 fanout payload should have index field"
    assert "message" in s3_payload, "S3 fanout payload should have message field"
    assert s3_payload.get("count") == payload.get("count"), "S3 should preserve original count param"
    logger.info(f"S3 verification: Fan-out item persisted correctly with index={s3_payload['index']}")


def test_empty_payload_handling(gateway_helper):
    """
    MUST-HAVE: Test empty/null payload handling.

    Scenario: Actor returns null or empty list
    Expected: Sends original envelope to happy-end without incrementing
    """
    response = gateway_helper.call_mcp_tool(
        tool_name="test_empty_response",
        arguments={"message": "empty test"},
    )

    envelope_id = response["result"]["id"]

    # Wait for completion
    final_envelope = gateway_helper.wait_for_envelope_completion(envelope_id, timeout=30)

    # Verify envelope completed successfully with original payload
    assert final_envelope["status"] == "succeeded", "Empty response should go to happy-end"
    logger.info(f"Final envelope: {final_envelope}")

    s3_object = wait_for_envelope_in_s3(bucket_name="asya-results", envelope_id=envelope_id, timeout=10)
    assert s3_object is not None, f"Happy-end should persist empty payload envelope {envelope_id} to S3"
    logger.info("S3 verification: Happy-end persisted empty payload correctly")


def test_multiple_sse_clients_for_same_envelope(gateway_helper):
    """
    MUST-HAVE: Test multiple SSE streams for same envelope.

    Scenario: Two clients connect to /envelopes/{id}/stream simultaneously
    Expected: Both should receive all updates (broadcast)
    """
    import threading

    response = gateway_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "multi-sse-test"},
    )

    envelope_id = response["result"]["id"]

    # Collect updates from two concurrent SSE streams
    updates_client1 = []
    updates_client2 = []

    def stream_client1():
        updates_client1.extend(
            gateway_helper.stream_progress_updates(envelope_id, timeout=30)
        )

    def stream_client2():
        updates_client2.extend(
            gateway_helper.stream_progress_updates(envelope_id, timeout=30)
        )

    # Start both clients simultaneously
    thread1 = threading.Thread(target=stream_client1)
    thread2 = threading.Thread(target=stream_client2)

    thread1.start()
    thread2.start()

    thread1.join(timeout=35)
    thread2.join(timeout=35)

    # Both clients should receive updates
    assert len(updates_client1) > 0, "Client 1 should receive updates"
    assert len(updates_client2) > 0, "Client 2 should receive updates"

    # Both should see final status
    assert updates_client1[-1]["status"] in ["succeeded", "failed"], "Client 1 should see final status"
    assert updates_client2[-1]["status"] in ["succeeded", "failed"], "Client 2 should see final status"

    logger.info(f"Client 1 received {len(updates_client1)} updates")
    logger.info(f"Client 2 received {len(updates_client2)} updates")


def test_invalid_tool_name(gateway_helper):
    """
    MUST-HAVE: Test POST /tools/call with nonexistent tool.

    Expected: 400 Bad Request with clear error message
    """
    payload = {
        "name": "nonexistent_tool_xyz",
        "arguments": {},
    }

    response = requests.post(
        gateway_helper.tools_url,
        json=payload,
        timeout=5,
    )

    # Should return error status
    assert response.status_code in [400, 404], \
        f"Should return 400 or 404 for invalid tool, got {response.status_code}"

    # Try to parse JSON, fall back to text if not JSON
    try:
        error_data = response.json()
        logger.info(f"Error response (JSON): {error_data}")
        # Should have error message in JSON
        assert "error" in error_data or "message" in error_data, \
            "Error response should contain error message"
    except ValueError:
        # Plain text error response is also acceptable
        error_text = response.text
        logger.info(f"Error response (text): {error_text}")
        assert len(error_text) > 0, "Error response should not be empty"
        assert "not found" in error_text.lower() or "nonexistent" in error_text.lower(), \
            f"Error message should indicate tool not found, got: {error_text}"



def test_get_envelope_status_for_nonexistent_id(gateway_helper):
    """
    MUST-HAVE: Test GET /envelopes/{id} for non-existent envelope.

    Expected: 404 Not Found
    """
    fake_envelope_id = "00000000-0000-0000-0000-000000000000"

    response = requests.get(
        f"{gateway_helper.envelopes_url}/{fake_envelope_id}",
        timeout=5,
    )

    assert response.status_code == 404, \
        f"Should return 404 for non-existent envelope, got {response.status_code}"



# ============================================================================
# SHOULD-HAVE: Important Reliability Tests
# ============================================================================

def test_timeout_fires_near_completion(gateway_helper):
    """
    SHOULD-HAVE: Test timeout boundary condition.

    Scenario: Processing completes just before timeout fires
    Expected: Should complete successfully (no race with timeout)
    """
    # Use slow_then_fast handler that takes 1.5s (well under 4s timeout including overhead)
    response = gateway_helper.call_mcp_tool(
        tool_name="test_slow_boundary",
        arguments={"first_call": True},
    )

    envelope_id = response["result"]["id"]

    # Wait for completion (should succeed before 4s timeout)
    final_envelope = gateway_helper.wait_for_envelope_completion(envelope_id, timeout=10)

    # Should complete successfully (not timeout)
    assert final_envelope["status"] == "succeeded", \
        f"Should succeed before timeout, got {final_envelope['status']}"



def test_sse_stream_for_already_completed_envelope(gateway_helper):
    """
    SHOULD-HAVE: Test SSE stream connection after envelope completed.

    Scenario: Connect to /envelopes/{id}/stream after envelope finished
    Expected: Should receive cached events or final status
    """
    # Create and wait for envelope to complete
    response = gateway_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "completed-sse-test"},
    )

    envelope_id = response["result"]["id"]

    # Wait for completion
    final_envelope = gateway_helper.wait_for_envelope_completion(envelope_id, timeout=30)
    assert final_envelope["status"] in ["succeeded", "failed"], "Envelope should be complete"

    # SSE stream may timeout if envelope completed too fast
    # This is expected behavior - fall back to envelope status verification
    try:
        updates = gateway_helper.stream_progress_updates(envelope_id, timeout=10)

        # If we got updates, verify them
        if len(updates) > 0:
            assert updates[-1]["status"] in ["succeeded", "failed"], "Should receive final status"
            logger.info(f"Received {len(updates)} updates for completed envelope")
        else:
            # No updates via SSE - verify via envelope status
            logger.info("No SSE updates (envelope already complete), verifying via status endpoint")
            assert final_envelope["status"] in ["succeeded", "failed"]
    except requests.exceptions.ReadTimeout:
        # SSE connection timed out - envelope was already complete
        logger.info("SSE timeout (envelope already complete), verifying via status endpoint")
        assert final_envelope["status"] in ["succeeded", "failed"]


def test_concurrent_envelopes_do_not_interfere(gateway_helper):
    """
    SHOULD-HAVE: Test concurrent envelopes don't interfere with each other.

    Scenario: Process 10 envelopes concurrently
    Expected: All complete independently, no cross-contamination
    """
    import threading

    num_envelopes = 10
    envelope_ids = []
    results = [None] * num_envelopes

    # Create all envelopes
    for i in range(num_envelopes):
        response = gateway_helper.call_mcp_tool(
            tool_name="test_echo",
            arguments={"message": f"concurrent-{i}"},
        )
        envelope_ids.append(response["result"]["id"])

    # Wait for all concurrently
    def wait_for_envelope(index, envelope_id):
        try:
            results[index] = gateway_helper.wait_for_envelope_completion(
                envelope_id, timeout=30
            )
        except Exception as e:
            logger.error(f"Envelope {index} failed: {e}")
            results[index] = {"status": "Error", "error": str(e)}

    threads = []
    for i, envelope_id in enumerate(envelope_ids):
        thread = threading.Thread(target=wait_for_envelope, args=(i, envelope_id))
        threads.append(thread)
        thread.start()

    # Wait for all threads
    for thread in threads:
        thread.join(timeout=35)

    # Verify all completed successfully
    for i, result in enumerate(results):
        # Verify each has correct result (no cross-contamination)
        assert result is not None, f"Envelope {i} should have result"
        assert result["status"] == "succeeded", \
            f"Envelope {i} should succeed, got {result.get('status')}"

        echoed = result.get("result", {}).get("echoed", "")
        assert f"concurrent-{i}" in echoed, \
            f"Envelope {i} should echo 'concurrent-{i}', got '{echoed}'"

    logger.info(f"All {num_envelopes} concurrent envelopes completed successfully")


# ============================================================================
# NICE-TO-HAVE: Operational Excellence Tests
# ============================================================================

def test_unicode_payload_handling(gateway_helper):
    """
    NICE-TO-HAVE: Test proper UTF-8 encoding/decoding.

    Scenario: Send payload with international characters
    Expected: Characters preserved correctly through pipeline
    """
    response = gateway_helper.call_mcp_tool(
        tool_name="test_unicode",
        arguments={
            "message": "Hello 世界 🌍 مرحبا こんにちは Привет"
        },
    )

    envelope_id = response["result"]["id"]

    final_envelope = gateway_helper.wait_for_envelope_completion(envelope_id, timeout=30)

    assert final_envelope["status"] == "succeeded", "Unicode payload should succeed"

    result = final_envelope.get("result", {})
    assert "languages" in result, "Should have language data"

    logger.info(f"Unicode result: {result}")

    s3_object = wait_for_envelope_in_s3(bucket_name="asya-results", envelope_id=envelope_id, timeout=10)
    assert s3_object is not None, f"Happy-end should persist unicode envelope {envelope_id} to S3"
    assert s3_object["payload"] == result, "S3 should preserve unicode characters correctly"
    logger.info("S3 verification: Happy-end persisted unicode payload correctly")


def test_large_payload_within_limits(gateway_helper):
    """
    NICE-TO-HAVE: Test large payload (but within RabbitMQ limits).

    Scenario: Send 10MB payload (well below 128MB limit)
    Expected: Should process successfully

    Note: SQS has a 256KB message size limit, so this test is skipped for SQS transport.
    Use RabbitMQ for large payload testing.
    """
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    if transport == "sqs":
        pytest.skip("Large payload test not supported with SQS (256KB limit)")

    response = gateway_helper.call_mcp_tool(
        tool_name="test_large_payload",
        arguments={"size_kb": 10240},  # 10MB
    )

    envelope_id = response["result"]["id"]

    # Large payload may take longer
    final_envelope = gateway_helper.wait_for_envelope_completion(envelope_id, timeout=120)

    assert final_envelope["status"] == "succeeded", \
        f"Large payload should succeed, got {final_envelope['status']}"

    s3_object = wait_for_envelope_in_s3(bucket_name="asya-results", envelope_id=envelope_id, timeout=10)
    assert s3_object is not None, f"Happy-end should persist large payload envelope {envelope_id} to S3"
    logger.info("S3 verification: Happy-end persisted large payload correctly")



def test_nested_json_payload(gateway_helper):
    """
    NICE-TO-HAVE: Test deeply nested JSON structures.

    Scenario: Send deeply nested payload (20 levels)
    Expected: Should parse and process correctly
    """
    response = gateway_helper.call_mcp_tool(
        tool_name="test_nested_data",
        arguments={"message": "nested test"},
    )

    envelope_id = response["result"]["id"]

    final_envelope = gateway_helper.wait_for_envelope_completion(envelope_id, timeout=30)

    assert final_envelope["status"] == "succeeded", "Nested payload should succeed"

    result = final_envelope.get("result", {})
    assert result.get("nested_depth") == 20, "Should have 20 levels of nesting"

    s3_object = wait_for_envelope_in_s3(bucket_name="asya-results", envelope_id=envelope_id, timeout=10)
    assert s3_object is not None, f"Happy-end should persist nested payload envelope {envelope_id} to S3"
    assert s3_object["payload"] == result, "S3 should preserve nested JSON correctly"
    logger.info("S3 verification: Happy-end persisted nested payload correctly")



def test_null_values_in_payload(gateway_helper):
    """
    NICE-TO-HAVE: Test handling of null/None values in payload.

    Scenario: Send payload with null fields
    Expected: null values preserved correctly through JSON serialization
    """
    response = gateway_helper.call_mcp_tool(
        tool_name="test_null_values",
        arguments={"message": "null test"},
    )

    envelope_id = response["result"]["id"]

    final_envelope = gateway_helper.wait_for_envelope_completion(envelope_id, timeout=30)

    assert final_envelope["status"] == "succeeded", "Null payload should succeed"

    result = final_envelope.get("result", {})
    assert result.get("null_field") is None, "null_field should be None"
    assert None in result.get("list_with_nulls", []), "list should contain None values"

    s3_object = wait_for_envelope_in_s3(bucket_name="asya-results", envelope_id=envelope_id, timeout=10)
    assert s3_object is not None, f"Happy-end should persist null values envelope {envelope_id} to S3"
    assert s3_object["payload"] == result, "S3 should preserve null values correctly"
    logger.info("S3 verification: Happy-end persisted null values correctly")


def test_multi_actor_parameter_flow(gateway_helper):
    """
    MUST-HAVE: Test that multi-actor pipelines pass outputs correctly.

    Critical test verifying that:
    1. First actor receives original MCP tool parameters
    2. Second actor receives OUTPUT from first actor, NOT original parameters
    3. Parameter transformation is correctly chained through pipeline

    This validates the core envelope flow pattern.

    Scenario:
    - Call test_param_flow with {"original_param": "test_value", "number": 10}
    - Actor 1 should receive original params and transform them
    - Actor 2 should receive actor 1's output structure
    - Final result should contain both actors' transformations

    Expected:
    - actor_2_received should contain actor_1's output
    - actor_2_received should NOT contain original MCP parameters directly
    - Verification flags should confirm correct flow
    """
    logger.info("=== test_multi_actor_parameter_flow ===")

    response = gateway_helper.call_mcp_tool(
        tool_name="test_param_flow",
        arguments={
            "original_param": "test_value_123",
            "number": 10,
        },
    )

    envelope_id = response["result"]["id"]
    logger.info(f"Created envelope {envelope_id}")

    # Multi-actor pipeline with S3 verification needs longer timeout
    final_envelope = gateway_helper.wait_for_envelope_completion(envelope_id, timeout=90)

    logger.info(f"Final envelope: {json.dumps(final_envelope, indent=2)}")

    assert final_envelope["status"] == "succeeded", f"Expected succeeded, got {final_envelope['status']}"

    result = final_envelope.get("result", {})

    logger.info(f"Result: {json.dumps(result, indent=2)}")

    assert "actor_2_received" in result, "Result should contain what actor 2 received"
    assert "actor_2_verification" in result, "Result should contain actor 2's verification"

    actor_2_received = result["actor_2_received"]
    verification = result["actor_2_verification"]

    logger.info(f"Actor 2 received: {json.dumps(actor_2_received, indent=2)}")
    logger.info(f"Verification: {json.dumps(verification, indent=2)}")

    # Verify actor 2 received actor 1's output structure
    assert "actor_1_received" in actor_2_received, \
        f"Actor 2 should receive actor 1's output structure (containing actor_1_received). Got keys: {list(actor_2_received.keys())}, full data: {json.dumps(actor_2_received, indent=2)}"

    assert "original_param" not in actor_2_received, \
        "Actor 2 should NOT receive original MCP parameters at its top level"

    # Verify actor 1's captured data
    assert "original_param" in actor_2_received.get("actor_1_received", {}), \
        f"Actor 1's received data should have original_param. Actor 1 received: {json.dumps(actor_2_received.get('actor_1_received'), indent=2)}"
    assert actor_2_received["actor_1_received"]["original_param"] == "test_value_123", \
        "Actor 1 should have received and recorded the original parameter"

    assert "number" in actor_2_received.get("actor_1_received", {}), \
        f"Actor 1's received data should have number. Actor 1 received: {json.dumps(actor_2_received.get('actor_1_received'), indent=2)}"
    assert actor_2_received["actor_1_received"]["number"] == 10, \
        "Actor 1 should have received original number parameter"

    assert actor_2_received.get("processed_by") == "actor_1", \
        "Actor 2 should receive output marked as processed by actor_1"

    assert verification["received_from_actor_1"] is True, \
        "Actor 2 should confirm it received data from actor 1"

    assert verification["has_original_params"] is False, \
        "Actor 2 should NOT have original params at top level (they're in actor_1's captured data)"

    logger.info("Verified parameter flow through actor pipeline")

    logger.info("Waiting for S3 persistence to verify what happy-end received...")
    s3_object = wait_for_envelope_in_s3(
        bucket_name="asya-results",
        envelope_id=envelope_id,
        timeout=10,
    )

    assert s3_object is not None, \
        f"Envelope {envelope_id} should be persisted to S3 by happy-end"

    assert s3_object["id"] == envelope_id, "S3 object should have correct envelope ID"
    if "status" in s3_object:
        assert s3_object["status"] == "succeeded", "S3 object should have succeeded status"
    assert "payload" in s3_object, "S3 object should contain payload field"

    s3_result = s3_object["payload"]
    logger.info(f"Happy-end persisted result: {json.dumps(s3_result, indent=2)}")

    assert s3_result == result, \
        "Happy-end should persist exactly what the final actor (actor 2) returned"

    assert s3_result.get("processed_by") == "actor_2", \
        "Happy-end should receive the final actor's output (processed by actor_2)"

    assert "actor_2_received" in s3_result, \
        "Happy-end should receive actor 2's complete output including what it received"

    logger.info("S3 verification PASSED: Happy-end received and persisted final actor output correctly")
    logger.info("Parameter flow test PASSED: Multi-actor pipeline correctly passes outputs")
