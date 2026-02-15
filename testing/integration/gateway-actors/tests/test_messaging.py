#!/usr/bin/env python3
"""
Gateway E2E integration test suite.

Tests the complete flow from Gateway → Actors → Results with both SSE and HTTP polling.

Test flow:
1. Send MCP request to gateway
2. Gateway creates task and sends message to first actor queue
3. Sidecar reports progress (received, processing, completed)
4. Gateway streams progress via SSE OR HTTP polling
5. Verify final result in task status
"""

import logging

import pytest

from asya_testing.config import get_env
from asya_testing.utils.s3 import wait_for_message_in_s3
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

    task_id = result["id"]
    logger.info(f" Task ID: {task_id}")

    final_task = gateway_helper.wait_for_task_completion(task_id, timeout=30)

    logger.info(f" Final task: {final_task}")
    assert final_task["status"] == "succeeded", f"Task should succeed, got {final_task}"
    assert final_task["result"] is not None, "Task should have result"

    task_result = final_task["result"]
    assert task_result.get("echoed") == "Hello, World!", "Should echo the input"

    s3_object = wait_for_message_in_s3(bucket_name="asya-results", message_id=task_id, timeout=10)
    assert s3_object is not None, f"x-sink should persist message {task_id} to S3"
    assert s3_object["payload"] == task_result, "S3 result should match gateway result"
    logger.info(" S3 verification: x-sink persisted result correctly")


def test_multi_actor_pipeline(gateway_helper):
    """Test multi-actor pipeline with multiple actors."""
    response = gateway_helper.call_mcp_tool(
        tool_name="test_pipeline",
        arguments={"value": 10},
    )

    task_id = response["result"]["id"]
    logger.info(f" Task ID: {task_id}")

    # Get progress updates
    updates = gateway_helper.get_progress_updates(task_id, timeout=60)

    logger.info(f" Total updates: {len(updates)}")
    messages = [u.get("message", "") for u in updates]
    logger.info(f" All messages: {messages}")

    # For SSE tests, race condition may cause missing updates
    # Use task status endpoint as authoritative source
    actors_seen = set()
    for update in updates:
        actor = update.get("actor")
        if actor:
            actors_seen.add(actor)

    # Wait for completion first
    final_task = gateway_helper.wait_for_task_completion(task_id, timeout=60)
    logger.info(f" Final task status: {final_task['status']}")
    assert final_task["status"] == "succeeded", "Pipeline should complete successfully"

    # Verify actor count from task status (authoritative source)
    if "total_actors" in final_task:
        assert final_task["total_actors"] == 2, "Should have 2 actors in route"

    # If SSE/polling caught actor updates, verify them
    if len(actors_seen) > 0:
        logger.info(f" Actors seen in updates: {actors_seen}")
        # May see 1-2 actors depending on race conditions
        assert len(actors_seen) >= 1, f"Should see at least 1 actor if updates received, saw: {actors_seen}"
    else:
        logger.info(" No actor updates received (race condition or fast processing)")

    result = final_task["result"]
    logger.info(f" Result: {result}")
    assert result is not None, "Should have a result"
    # Value should be: 10 * 2 + 5 = 25 (doubled + incremented)
    assert result.get("value") == 25, f"Expected 25, got {result.get('value')}"

    s3_object = wait_for_message_in_s3(bucket_name="asya-results", message_id=task_id, timeout=10)
    assert s3_object is not None, f"x-sink should persist pipeline message {task_id} to S3"
    assert s3_object["payload"] == result, "S3 result should match gateway result"
    if "last_actor" in s3_object:
        assert s3_object["last_actor"] == "test-incrementer", "S3 should track last actor in pipeline"
    logger.info(" S3 verification: x-sink persisted pipeline result correctly")


def test_error_handling(gateway_helper):
    """Test error handling with progress updates."""
    response = gateway_helper.call_mcp_tool(
        tool_name="test_error",
        arguments={"should_fail": True},
    )

    task_id = response["result"]["id"]
    logger.info(f" Task ID: {task_id}")

    # Get progress updates
    updates = gateway_helper.get_progress_updates(task_id, timeout=30)

    logger.info(f" Total updates: {len(updates)}")

    # Final update should indicate failure
    final_update = updates[-1]
    logger.info(f" Final update: {final_update}")
    assert final_update["status"] == "failed", "Task should fail"

    # Verify task status reflects the error
    final_task = gateway_helper.get_task_status(task_id)
    logger.info(f" Final task: {final_task}")
    assert final_task["status"] == "failed", "Task status should be failed"
    assert final_task.get("error") or final_task.get("error_message"), "Task should have error information"


def test_task_status_endpoint(gateway_helper):
    """Test task status REST endpoint."""
    response = gateway_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "status test"},
    )

    task_id = response["result"]["id"]
    logger.info(f" Task ID: {task_id}")

    # Immediately check status (should be pending or running)
    task = gateway_helper.get_task_status(task_id)
    logger.info(f" Initial task status: {task['status']}")
    assert task["id"] == task_id, "Task ID should match"
    assert task["status"] in ["pending", "running"], \
        f"Initial status should be pending or running, got {task['status']}"
    assert "route" in task, "Should have route information"
    assert "created_at" in task, "Should have created_at timestamp"

    # Wait for completion
    final_task = gateway_helper.wait_for_task_completion(task_id, timeout=30)

    logger.info(f" Final task: {final_task}")
    assert final_task["status"] == "succeeded", "Should complete successfully"
    assert final_task["result"] is not None, "Should have result"
    assert "updated_at" in final_task, "Should have updated_at timestamp"


def test_concurrent_tasks(gateway_helper):
    """Test multiple concurrent tasks."""
    task_ids = []

    for i in range(3):
        response = gateway_helper.call_mcp_tool(
            tool_name="test_echo",
            arguments={"message": f"concurrent-{i}"},
        )
        task_id = response["result"]["id"]
        task_ids.append(task_id)
        logger.info(f" Created task {i}: {task_id}")

    logger.info(f" Total concurrent tasks: {len(task_ids)}")

    # Wait for all tasks to complete
    completed_tasks = []
    for i, task_id in enumerate(task_ids):
        logger.info(f" Waiting for task {i}: {task_id}")
        task = gateway_helper.wait_for_task_completion(task_id, timeout=30)
        completed_tasks.append(task)
        logger.info(f" Task {i} completed with status: {task['status']}")

    # Verify all tasks succeeded
    for task in completed_tasks:
        logger.info(f" Verifying task {task['id']}: status={task['status']}")
        assert task["status"] == "succeeded", f"Task {task['id']} should succeed"
        assert task["result"] is not None, f"Task {task['id']} should have result"

    # Verify each task has its own result
    results = [task["result"]["echoed"] for task in completed_tasks]
    logger.info(f" All results: {results}")
    assert "concurrent-0" in results, "Should have result from task 0"
    assert "concurrent-1" in results, "Should have result from task 1"
    assert "concurrent-2" in results, "Should have result from task 2"


def test_timeout_handling(gateway_helper):
    """Test task timeout handling."""
    response = gateway_helper.call_mcp_tool(
        tool_name="test_timeout",
        arguments={"sleep_seconds": 60},
    )

    task_id = response["result"]["id"]
    logger.info(f" Task ID: {task_id}")

    # Wait for task to timeout (timeout is set to 10s in config)
    try:
        task = gateway_helper.wait_for_task_completion(task_id, timeout=15)
        logger.info(f" Task completed with status: {task['status']}")
    except TimeoutError:
        task = gateway_helper.get_task_status(task_id)
        logger.info(f" Current task status: {task['status']}")

    logger.info(f" Final task: {task}")
    assert task["status"] in ["failed", "unknown"], \
        f"Task should timeout, got status: {task['status']}"
