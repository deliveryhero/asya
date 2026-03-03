#!/usr/bin/env python3
"""
Unit tests for the S3 split-key fan-in aggregator.

Tests the aggregator handler that collects N+1 fan-in slices and emits a merged
payload once all slices have arrived. Uses tmp_path for filesystem isolation.

The aggregator returns only the merged payload dict (parent payload with sub-agent
results placed at aggregation_key). Route, headers, and id are managed by the
runtime/sidecar layer and are not part of the aggregator's return value.
"""

import json
import logging
import os
import sys
from contextlib import contextmanager
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def make_fan_in_header(
    origin_id: str,
    idx: int,
    slice_count: int,
    aggregation_key: str = "/results",
) -> dict:
    """Build the x-asya-fan-in header dict."""
    return {
        "actor": "aggregator",
        "origin_id": origin_id,
        "slice_index": idx,
        "slice_count": slice_count,
        "aggregation_key": aggregation_key,
    }


@contextmanager
def mock_vfs(
    fan_in_header: dict,
    route: dict,
    headers: dict | None = None,
    message_id: str = "",
):
    """Context manager that mocks VFS calls in the aggregator module."""
    non_transient_headers = headers or {}

    def mock_read_fan_in():
        return fan_in_header

    def mock_read_route():
        return route.copy()

    def mock_read_non_transient_headers():
        return dict(non_transient_headers)

    def mock_read_message_id():
        return message_id

    with (
        patch("asya_crew.fanin.s3_split_key._read_fan_in_header", side_effect=mock_read_fan_in),
        patch("asya_crew.fanin.s3_split_key._read_route", side_effect=mock_read_route),
        patch("asya_crew.fanin.s3_split_key._read_non_transient_headers", side_effect=mock_read_non_transient_headers),
        patch("asya_crew.fanin.s3_split_key._read_message_id", side_effect=mock_read_message_id),
    ):
        yield


def call_aggregator(msg: dict, base_dir: str) -> dict | None:
    """Call aggregator with message context, mocking VFS calls."""
    from asya_crew.fanin.s3_split_key import aggregator

    fan_in_header = msg["headers"]["x-asya-fan-in"]
    route = msg["route"].copy()
    all_headers = {k: v for k, v in msg.get("headers", {}).items() if k != "x-asya-fan-in"}
    message_id = msg.get("id", "")

    with mock_vfs(fan_in_header, route, all_headers, message_id):
        return aggregator(msg["payload"], _base_dir=base_dir)


def make_envelope(
    origin_id: str,
    idx: int,
    slice_count: int,
    payload: dict,
    route: dict | None = None,
    headers: dict | None = None,
    aggregation_key: str = "/results",
) -> dict:
    """Build a fan-in message for testing."""
    base_route = route or {
        "prev": ["sender"],
        "curr": "aggregator",
        "next": ["post-processor"],
    }
    base_headers = headers or {}
    return {
        "id": f"msg-{idx}-{origin_id}",
        "route": base_route,
        "headers": {
            **base_headers,
            "x-asya-fan-in": {
                "actor": "aggregator",
                "origin_id": origin_id,
                "slice_index": idx,
                "slice_count": slice_count,
                "aggregation_key": aggregation_key,
            },
        },
        "payload": payload,
    }


def test_full_cycle_two_slices(tmp_path):
    """Single sub-agent: slice_count=2 (index 0 + one sub-agent). Full cycle returns merged payload."""
    logger.info("=== test_full_cycle_two_slices ===")

    base_dir = str(tmp_path)
    origin_id = "test-origin-001"

    parent_payload = {"task": "analyze", "input": "document.pdf"}
    subagent_result = {"analysis": "positive", "confidence": 0.95}

    # Slice 0: parent payload
    msg0 = make_envelope(origin_id, 0, 2, parent_payload)
    result = call_aggregator(msg0, base_dir)
    assert result is None, "Should accumulate, not emit yet"

    # Slice 1: sub-agent result triggers emission
    msg1 = make_envelope(origin_id, 1, 2, subagent_result)
    result = call_aggregator(msg1, base_dir)

    assert result is not None, "Should emit merged payload"
    # Aggregator returns the merged payload dict directly (not a full message)
    assert result["task"] == "analyze"
    assert result["input"] == "document.pdf"
    # Sub-agent results placed at aggregation key
    assert result["results"] == [subagent_result]

    logger.info("=== test_full_cycle_two_slices: PASSED ===")


def test_multi_slice_in_order_arrival(tmp_path):
    """All slices arrive in order 0, 1, 2, 3. Merged on last."""
    logger.info("=== test_multi_slice_in_order_arrival ===")

    base_dir = str(tmp_path)
    origin_id = "test-origin-002"
    slice_count = 4

    parent_payload = {"task": "classify"}
    sub_results = [{"label": f"class-{i}"} for i in range(1, slice_count)]

    # Send slices 0 through N-2 — all should return None
    for i in range(slice_count - 1):
        payload = parent_payload if i == 0 else sub_results[i - 1]
        msg = make_envelope(origin_id, i, slice_count, payload)
        result = call_aggregator(msg, base_dir)
        assert result is None, f"Slice {i} should not trigger emission"

    # Last slice triggers emission
    msg_last = make_envelope(origin_id, slice_count - 1, slice_count, sub_results[-1])
    result = call_aggregator(msg_last, base_dir)

    assert result is not None
    assert result["task"] == "classify"
    assert result["results"] == sub_results

    logger.info("=== test_multi_slice_in_order_arrival: PASSED ===")


def test_out_of_order_arrival(tmp_path):
    """Slices arrive out of order: 2, 0, 1. Still merged correctly."""
    logger.info("=== test_out_of_order_arrival ===")

    base_dir = str(tmp_path)
    origin_id = "test-origin-003"
    slice_count = 3

    parent_payload = {"task": "summarize"}
    sub1 = {"summary": "part-1"}
    sub2 = {"summary": "part-2"}

    # Slice 2 arrives first
    msg2 = make_envelope(origin_id, 2, slice_count, sub2)
    result = call_aggregator(msg2, base_dir)
    assert result is None

    # Slice 0 (parent) arrives second
    msg0 = make_envelope(origin_id, 0, slice_count, parent_payload)
    result = call_aggregator(msg0, base_dir)
    assert result is None

    # Slice 1 arrives last and triggers emission
    msg1 = make_envelope(origin_id, 1, slice_count, sub1)
    result = call_aggregator(msg1, base_dir)

    assert result is not None
    assert result["task"] == "summarize"
    # Results are ordered by slice index (slice-1, slice-2) = [sub1, sub2]
    assert result["results"] == [sub1, sub2]

    logger.info("=== test_out_of_order_arrival: PASSED ===")


def test_index_zero_arrives_last(tmp_path):
    """Index 0 (parent) arrives after sub-agent slices. Merged correctly when all arrive."""
    logger.info("=== test_index_zero_arrives_last ===")

    base_dir = str(tmp_path)
    origin_id = "test-origin-004"
    slice_count = 3

    parent_payload = {"task": "translate", "lang": "fr"}
    sub1 = {"translation": "bonjour"}
    sub2 = {"translation": "monde"}

    # Sub-agents arrive first
    msg1 = make_envelope(origin_id, 1, slice_count, sub1)
    result = call_aggregator(msg1, base_dir)
    assert result is None

    msg2 = make_envelope(origin_id, 2, slice_count, sub2)
    result = call_aggregator(msg2, base_dir)
    assert result is None

    # Parent slice arrives last and triggers emission
    msg0 = make_envelope(origin_id, 0, slice_count, parent_payload)
    result = call_aggregator(msg0, base_dir)

    assert result is not None
    assert result["task"] == "translate"
    assert result["lang"] == "fr"
    assert result["results"] == [sub1, sub2]

    logger.info("=== test_index_zero_arrives_last: PASSED ===")


def test_duplicate_slice_idempotent(tmp_path):
    """Same slice_index delivered twice. Only one write occurs; second delivery is ignored."""
    logger.info("=== test_duplicate_slice_idempotent ===")

    base_dir = str(tmp_path)
    origin_id = "test-origin-005"
    slice_count = 2

    parent_payload = {"task": "deduplicate"}
    sub_result_v1 = {"data": "first-delivery"}
    sub_result_v2 = {"data": "second-delivery-ignored"}

    # Slice 0 (parent) arrives
    msg0 = make_envelope(origin_id, 0, slice_count, parent_payload)
    call_aggregator(msg0, base_dir)

    # Slice 1 arrives first time — triggers emission with v1 data
    msg1_first = make_envelope(origin_id, 1, slice_count, sub_result_v1)
    result = call_aggregator(msg1_first, base_dir)
    assert result is not None

    # Only first delivery stored
    assert result["results"] == [sub_result_v1]

    # Re-deliver slice 1 with different content (simulates at-least-once delivery)
    # After emission, directory is gone, so re-delivery starts fresh accumulation
    msg1_dup = make_envelope(origin_id, 1, slice_count, sub_result_v2)
    result_dup = call_aggregator(msg1_dup, base_dir)
    # Fresh aggregation started but idx=0 (parent) not re-delivered, so returns None
    assert result_dup is None

    logger.info("=== test_duplicate_slice_idempotent: PASSED ===")


def test_incomplete_returns_none(tmp_path):
    """N-1 slices arrive. Returns None (not yet complete)."""
    logger.info("=== test_incomplete_returns_none ===")

    base_dir = str(tmp_path)
    origin_id = "test-origin-006"
    slice_count = 5

    for i in range(slice_count - 1):
        payload = {"data": f"slice-{i}"}
        msg = make_envelope(origin_id, i, slice_count, payload)
        result = call_aggregator(msg, base_dir)
        assert result is None, f"Slice {i} of {slice_count} should not emit"

    logger.info("=== test_incomplete_returns_none: PASSED ===")


def test_concurrent_completion_exactly_once(tmp_path):
    """Simulate concurrent pod creating sentinel before aggregator. Second call returns None."""
    logger.info("=== test_concurrent_completion_exactly_once ===")

    base_dir = str(tmp_path)
    origin_id = "test-origin-007"
    slice_count = 2

    parent_payload = {"task": "race"}
    sub_result = {"winner": "first-pod"}

    # Deliver slice 0 (parent)
    msg0 = make_envelope(origin_id, 0, slice_count, parent_payload)
    call_aggregator(msg0, base_dir)

    # Manually pre-create the sentinel to simulate another pod completing first
    sentinel_path = os.path.join(base_dir, origin_id, "complete")
    with open(sentinel_path, "wb") as fh:
        fh.write(b"1")

    # Write slice-1 manually so listing shows complete
    slice_path = os.path.join(base_dir, origin_id, "slice-1.json")
    with open(slice_path, "w") as fh:
        json.dump(sub_result, fh)

    # Now call aggregator with slice 1 — sentinel already exists, should return None
    msg1 = make_envelope(origin_id, 1, slice_count, sub_result)
    result = call_aggregator(msg1, base_dir)

    assert result is None, "Should return None when sentinel already created by another pod"

    logger.info("=== test_concurrent_completion_exactly_once: PASSED ===")


def test_transient_headers_not_in_payload(tmp_path):
    """Aggregator returns merged payload; transient headers are not part of payload content."""
    logger.info("=== test_transient_headers_not_in_payload ===")

    base_dir = str(tmp_path)
    origin_id = "test-origin-008"
    slice_count = 2

    parent_payload = {"task": "strip-headers"}
    sub_result = {"data": "processed"}

    non_transient_headers = {
        "trace-id": "trace-abc-123",
        "x-custom-header": "keep-me",
    }
    transient_extra = {
        "x-asya-route-override": "some-override",
        "x-asya-route-resolved": "resolved",
        "x-asya-parent-id": "parent-123",
    }
    all_headers = {**non_transient_headers, **transient_extra}

    msg0 = make_envelope(origin_id, 0, slice_count, parent_payload, headers=all_headers)
    call_aggregator(msg0, base_dir)

    msg1 = make_envelope(origin_id, 1, slice_count, sub_result, headers=all_headers)
    result = call_aggregator(msg1, base_dir)

    assert result is not None
    # The returned value is the merged payload dict; it should contain parent fields
    assert result["task"] == "strip-headers"
    assert result["results"] == [sub_result]
    # Headers are not part of the returned payload dict
    assert "x-asya-fan-in" not in result
    assert "x-asya-route-override" not in result
    assert "trace-id" not in result

    logger.info("=== test_transient_headers_not_in_payload: PASSED ===")


def test_aggregation_key_placement(tmp_path):
    """Results placed at correct JSON Pointer in parent payload."""
    logger.info("=== test_aggregation_key_placement ===")

    base_dir = str(tmp_path)
    origin_id = "test-origin-009"
    slice_count = 3

    parent_payload = {
        "task": "nested",
        "meta": {"job_id": "j-42"},
        "analysis": {},
    }
    sub1 = {"score": 0.8}
    sub2 = {"score": 0.9}

    # Use a nested aggregation key
    aggregation_key = "/analysis/scores"

    msg0 = make_envelope(origin_id, 0, slice_count, parent_payload, aggregation_key=aggregation_key)
    call_aggregator(msg0, base_dir)

    msg1 = make_envelope(origin_id, 1, slice_count, sub1, aggregation_key=aggregation_key)
    call_aggregator(msg1, base_dir)

    msg2 = make_envelope(origin_id, 2, slice_count, sub2, aggregation_key=aggregation_key)
    result = call_aggregator(msg2, base_dir)

    assert result is not None
    # Results placed at /analysis/scores, not at /results
    assert result["analysis"]["scores"] == [sub1, sub2]
    assert "results" not in result

    logger.info("=== test_aggregation_key_placement: PASSED ===")


def test_state_cleanup_after_emission(tmp_path):
    """After emission, state directory is fully removed."""
    logger.info("=== test_state_cleanup_after_emission ===")

    base_dir = str(tmp_path)
    origin_id = "test-origin-010"
    slice_count = 2

    parent_payload = {"task": "cleanup"}
    sub_result = {"cleaned": True}

    msg0 = make_envelope(origin_id, 0, slice_count, parent_payload)
    call_aggregator(msg0, base_dir)

    msg1 = make_envelope(origin_id, 1, slice_count, sub_result)
    result = call_aggregator(msg1, base_dir)

    assert result is not None

    # State directory for this origin_id must be gone
    state_dir = os.path.join(base_dir, origin_id)
    assert not os.path.exists(state_dir), f"State directory {state_dir} should be cleaned up after emission"

    logger.info("=== test_state_cleanup_after_emission: PASSED ===")


def test_merged_payload_preserves_parent_fields(tmp_path):
    """Merged payload preserves all parent payload fields."""
    logger.info("=== test_merged_payload_preserves_parent_fields ===")

    base_dir = str(tmp_path)
    origin_id = "test-origin-011"
    slice_count = 2

    parent_payload = {
        "task": "route-check",
        "metadata": {"source": "test"},
        "tags": ["a", "b"],
    }
    sub_result = {"output": "ok"}

    msg0 = make_envelope(origin_id, 0, slice_count, parent_payload)
    call_aggregator(msg0, base_dir)

    msg1 = make_envelope(origin_id, 1, slice_count, sub_result)
    result = call_aggregator(msg1, base_dir)

    assert result is not None
    # All parent payload fields preserved
    assert result["task"] == "route-check"
    assert result["metadata"] == {"source": "test"}
    assert result["tags"] == ["a", "b"]
    # Sub-agent result appended at aggregation key
    assert result["results"] == [sub_result]

    logger.info("=== test_merged_payload_preserves_parent_fields: PASSED ===")
