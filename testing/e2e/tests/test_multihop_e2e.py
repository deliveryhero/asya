#!/usr/bin/env python3
"""
Multi-hop E2E test for Asya framework.

Tests message processing through a chain of 15 actors with progress reporting.
Validates that:
1. Message is correctly routed through all actors in sequence
2. Each actor processes the message and passes it forward
3. Progress is tracked and reported correctly
4. Final result contains all processing steps

Note: these tests dispatch directly to the mesh-api (not via the MCP adapter)
so that progress SSE streaming can be observed concurrently with task execution.
The MCP adapter call_mcp_tool is blocking by design; observing in-flight progress
requires direct mesh-api dispatch.
"""

import logging
import threading

import pytest
import requests

logger = logging.getLogger(__name__)


def _dispatch_multihop(gateway_helper, message: str) -> str:
    """Dispatch test_multihop directly to mesh-api and return task_id immediately."""
    response = requests.post(
        gateway_helper.tools_url,
        params={"actor": "test-multihop-0"},
        json={"payload": {"message": message}, "timeout": 90},
        timeout=10,
    )
    response.raise_for_status()
    task_id = response.json()["id"]
    logger.info(f"Dispatched multihop task: {task_id}")
    return task_id


@pytest.mark.fast
def test_multihop_chain(gateway_helper):
    """Test message processing through 15-actor chain with progress tracking.

    Dispatches directly to mesh-api so SSE streaming can observe in-flight hops.
    The MCP adapter call_mcp_tool blocks until completion — incompatible with
    streaming intermediate progress.
    """
    logger.info("Testing multi-hop message processing through 15 actors")

    # Collect SSE events in a background thread while the chain runs
    task_id = _dispatch_multihop(gateway_helper, "Multi-hop test")

    logger.info("Streaming progress updates...")
    updates = gateway_helper.stream_task_progress(task_id=task_id, timeout=90)

    logger.info(f"[+] Received {len(updates)} progress updates")
    for i, update in enumerate(updates):
        logger.info(
            f"  Update {i+1}: status={update.get('status')}, "
            f"actor={update.get('actor', 'unknown')}, "
            f"progress={update.get('progress_percent', 0)}%"
        )

    assert len(updates) > 0, "Should receive at least one progress update"

    final_update = updates[-1]
    assert final_update.get("status") == "succeeded", (
        f"Final status should be succeeded, got {final_update.get('status')}"
    )
    assert final_update.get("progress_percent") == 100, "Final progress should be 100%"

    logger.info(f"[+] Task completed with {len(updates)} progress updates")


@pytest.mark.fast
def test_multihop_progress_percentage(gateway_helper):
    """Test that progress percentage increases monotonically through the chain.

    Dispatches directly to mesh-api and opens SSE in a background thread
    concurrently with actor processing so intermediate hops are captured.
    """
    logger.info("Testing progress percentage tracking through multi-hop chain")

    updates: list = []
    done = threading.Event()

    task_id = _dispatch_multihop(gateway_helper, "Progress percentage test")

    def _stream():
        try:
            updates.extend(gateway_helper.stream_task_progress(task_id=task_id, timeout=90))
        finally:
            done.set()

    t = threading.Thread(target=_stream, daemon=True)
    t.start()
    done.wait(timeout=100)

    progress_values = [u.get("progress_percent", 0) for u in updates]
    logger.info(f"[+] Progress values: {progress_values[:10]}... (showing first 10)")

    assert len(progress_values) > 10, (
        f"Should have many progress updates across 15 hops, got {len(progress_values)}"
    )
    assert progress_values[0] >= 0, "First progress should be >= 0"
    assert progress_values[-1] == 100, "Final progress should be 100%"

    for i in range(len(progress_values) - 1):
        assert progress_values[i] <= progress_values[i + 1] + 0.01, (
            f"Progress should be monotonic (+0.01 tolerance), "
            f"but {progress_values[i]} > {progress_values[i+1]} at index {i}"
        )

    final_update = updates[-1]
    assert final_update.get("status") == "succeeded", "Task should succeed"

    logger.info("[+] Progress percentage tracking validated successfully")
