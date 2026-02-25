#!/usr/bin/env python3
"""
Streaming protocol integration tests.

Tests the full streaming path for upstream partial events:
Runtime (generator handler) -> Sidecar (SSE parser) -> Gateway (partial endpoint) -> SSE client

These tests verify that:
1. Generator handlers can yield upstream() partial events
2. Partial events flow through sidecar to gateway
3. Gateway broadcasts partial events as `event: partial` SSE events
4. Regular downstream events still work alongside partials
5. Mid-stream errors are handled correctly
"""

import logging

from asya_testing.config import get_env
from asya_testing.fixtures.gateway import gateway_helper

log_level = get_env('ASYA_LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_streaming_partial_events(gateway_helper):
    """Test that upstream partial events are received as event: partial via SSE."""
    token_count = 5

    response = gateway_helper.call_mcp_tool(
        tool_name="test_streaming",
        arguments={"token_count": token_count},
    )

    task_id = response["result"]["id"]
    logger.info(f"Task ID: {task_id}")

    # Wait for task to complete first (so all events are stored)
    final_task = gateway_helper.wait_for_task_completion(task_id, timeout=30)
    assert final_task["status"] == "succeeded", f"Task should succeed, got {final_task}"

    # Now stream all events (historical replay) and verify partials
    events = gateway_helper.stream_task_events(task_id, timeout=10)

    logger.info(f"Partial events: {len(events['partial'])}")
    logger.info(f"Update events: {len(events['update'])}")

    # Verify partial events
    assert len(events["partial"]) == token_count, (
        f"Expected {token_count} partial events, got {len(events['partial'])}"
    )

    # Verify partial event content
    for i, partial in enumerate(events["partial"]):
        assert partial.get("type") == "text_delta", f"Partial {i} should have type text_delta"
        assert partial.get("token") == f"token_{i}", f"Partial {i} should have token token_{i}"

    # Verify final result
    result = final_task["result"]
    assert result is not None, "Should have a final result"
    assert result.get("summary") == "streaming complete"
    assert result.get("total_tokens") == token_count


def test_streaming_default_token_count(gateway_helper):
    """Test streaming with default token count (3)."""
    response = gateway_helper.call_mcp_tool(
        tool_name="test_streaming",
        arguments={},
    )

    task_id = response["result"]["id"]
    logger.info(f"Task ID: {task_id}")

    final_task = gateway_helper.wait_for_task_completion(task_id, timeout=30)
    assert final_task["status"] == "succeeded", f"Task should succeed, got {final_task}"

    events = gateway_helper.stream_task_events(task_id, timeout=10)

    # Default token_count is 3
    assert len(events["partial"]) == 3, (
        f"Expected 3 partial events (default), got {len(events['partial'])}"
    )


def test_streaming_midstream_error(gateway_helper):
    """Test that mid-stream errors are handled correctly after partial events."""
    response = gateway_helper.call_mcp_tool(
        tool_name="test_streaming_error",
        arguments={},
    )

    task_id = response["result"]["id"]
    logger.info(f"Task ID: {task_id}")

    # Wait for task to reach terminal state
    final_task = gateway_helper.wait_for_task_completion(task_id, timeout=30)
    assert final_task["status"] == "failed", f"Task should fail, got {final_task}"

    # Stream events and check partials were still delivered
    events = gateway_helper.stream_task_events(task_id, timeout=10)

    logger.info(f"Partial events: {len(events['partial'])}")
    logger.info(f"Update events: {len(events['update'])}")

    # Should have at least 1 partial event (emitted before the error)
    assert len(events["partial"]) >= 1, (
        f"Expected at least 1 partial event before error, got {len(events['partial'])}"
    )

    # The partial event before error should contain the expected token
    assert events["partial"][0].get("token") == "before_error"
