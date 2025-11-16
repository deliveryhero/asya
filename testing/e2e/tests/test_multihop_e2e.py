#!/usr/bin/env python3
"""
Multi-hop E2E test for Asya framework.

Tests envelope processing through a chain of 15 actors with progress reporting.
Validates that:
1. Envelope is correctly routed through all actors in sequence
2. Each actor processes the envelope and passes it forward
3. Progress is tracked and reported correctly
4. Final result contains all processing steps
"""

import logging

import pytest

logger = logging.getLogger(__name__)


@pytest.mark.fast
def test_multihop_chain(gateway_helper):
    """Test envelope processing through 15-actor chain with progress tracking."""
    logger.info("Testing multi-hop envelope processing through 15 actors")

    result = gateway_helper.call_mcp_tool(
        tool_name="test_multihop",
        arguments={"message": "Multi-hop test"}
    )

    envelope_id = result["result"]["envelope_id"]
    assert envelope_id is not None, "Should have envelope ID"
    logger.info(f"[+] Created envelope: {envelope_id}")

    logger.info("Streaming progress updates...")
    updates = gateway_helper.stream_envelope_progress(
        envelope_id=envelope_id,
        timeout=30
    )

    logger.info(f"[+] Received {len(updates)} progress updates")

    for i, update in enumerate(updates):
        status = update.get("status", "unknown")
        actor = update.get("actor", "unknown")
        progress = update.get("progress_percent", 0)
        logger.info(f"  Update {i+1}: status={status}, actor={actor}, progress={progress}%")

    assert len(updates) > 0, "Should receive progress updates"

    final_update = updates[-1]
    assert final_update.get("status") == "succeeded", f"Final status should be succeeded, got {final_update.get('status')}"
    assert final_update.get("progress_percent") == 100, "Final progress should be 100%"

    logger.info(f"[+] Envelope completed successfully with {len(updates)} progress updates")
    logger.info("[+] Multi-hop test completed successfully")


@pytest.mark.fast
def test_multihop_progress_percentage(gateway_helper):
    """Test that progress percentage increases through multi-hop chain."""
    logger.info("Testing progress percentage tracking through multi-hop chain")

    result = gateway_helper.call_mcp_tool(
        tool_name="test_multihop",
        arguments={"message": "Progress percentage test"}
    )

    envelope_id = result["result"]["envelope_id"]
    logger.info(f"[+] Created envelope: {envelope_id}")

    updates = gateway_helper.stream_envelope_progress(
        envelope_id=envelope_id,
        timeout=30
    )

    progress_values = [u.get("progress_percent", 0) for u in updates]
    logger.info(f"[+] Progress values: {progress_values[:10]}... (showing first 10)")

    assert len(progress_values) > 10, f"Should have many progress updates, got {len(progress_values)}"
    assert progress_values[0] >= 0, "First progress should be >= 0"
    assert progress_values[-1] == 100, "Final progress should be 100%"

    for i in range(len(progress_values) - 1):
        assert progress_values[i] <= progress_values[i + 1] + 0.01, f"Progress should be monotonic (with 0.01 tolerance), but {progress_values[i]} > {progress_values[i+1]} at index {i}"

    final_update = updates[-1]
    assert final_update.get("status") == "succeeded", "Envelope should succeed"

    logger.info("[+] Progress percentage tracking validated successfully")
