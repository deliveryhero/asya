"""
Mock runtime handlers for integration and E2E tests.

This module provides test handlers covering various scenarios:
- Happy path processing (async - the common AI-workload pattern)
- Error handling (sync - error/edge-case handlers)
- Timeouts and slow processing
- Fan-out (generator/yield)
- Empty responses (return None)
- Large payloads and Unicode handling
- Pipeline processing (doubler, incrementer)

These handlers are shared across all integration and E2E tests.
Progress reporting is handled automatically by the Go sidecar.

Async handlers (async def) represent the preferred pattern for AI workloads
where long-running async calls (LLM APIs, HTTP clients) are common.
Sync handlers remain for error/edge-case testing where async adds no value.
"""

import asyncio
import time
from collections.abc import Generator
from typing import Any


# =============================================================================
# Happy Path & Basic Handlers (async - common AI-workload patterns)
# =============================================================================


async def echo_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Echo handler: Returns exact payload or echoes a message.

    Used for:
    - Simple pass-through testing
    - Message integrity verification
    - SSE streaming tests (with simulated processing time)

    Args:
        payload: Message payload dict
    """
    # If payload has a "message" field, echo it as "echoed"
    if "message" in payload:
        await asyncio.sleep(0.5)  # Simulate processing time for SSE streaming testing
        return {"echoed": payload["message"]}

    # Otherwise, return exact payload
    return payload


# =============================================================================
# Error Handling (sync - error/edge-case handlers)
# =============================================================================


def error_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Error handler: Raises ValueError to test error handling.

    Supports two modes:
    1. Conditional failure (if payload.should_fail=true)
    2. Always fails (for sidecar integration tests)

    This should result in processing_error with severity=fatal.

    Args:
        payload: Message payload dict
    """
    should_fail = payload.get("should_fail", True)  # Default to fail for sidecar tests
    if should_fail:
        raise ValueError("Intentional test failure")
    return payload


def oom_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """
    OOM handler: Raises MemoryError to test OOM detection.

    This should result in oom_error with severity=recoverable.

    Args:
        payload: Message payload dict (unused)
    """
    raise MemoryError("Simulated out of memory condition")


def cuda_oom_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """
    CUDA OOM handler: Raises CUDA-like error.

    This should result in cuda_oom_error with severity=recoverable.
    """
    raise RuntimeError("CUDA out of memory: Tried to allocate 4.0 GiB")


# =============================================================================
# Timeout & Slow Processing (sync - uses blocking time.sleep)
# =============================================================================


def timeout_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Timeout handler: Sleeps for specified duration.

    Supports two modes:
    1. Long timeout (for sidecar tests, default 60s)
    2. Configurable timeout (via payload.sleep_seconds)

    This should trigger timeout_error from the sidecar.
    """
    sleep_seconds = payload.get("sleep_seconds") or payload.get("sleep", 5)
    time.sleep(sleep_seconds)  # Simulate long operation to test timeout handling
    return payload


# =============================================================================
# Fan-out & Empty Responses (async)
# =============================================================================


def fanout_handler(payload: dict[str, Any]) -> Generator[dict[str, Any], None, None]:
    """
    Fan-out handler: Yields multiple results via generator.

    Tests that sidecar properly handles streaming fan-out responses
    and routes each result to the next actor.
    """
    count = payload.get("count", 3)

    for i in range(count):
        yield {**payload, "index": i, "message": f"Fan-out message {i}"}


def empty_response_handler(payload: dict[str, Any]) -> None:
    """
    Empty response handler: Returns None to abort pipeline.

    This should send the original message to x-sink queue.
    """
    return None


def none_response_handler(payload: dict[str, Any]) -> None:
    """
    None response handler: Returns None to abort pipeline.

    This should send the original message to x-sink queue.
    """
    return None


# =============================================================================
# Pipeline Processing (async)
# =============================================================================


async def pipeline_doubler(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Pipeline doubler: First actor in pipeline, doubles the input value.

    Part of multi-actor pipeline tests.
    """
    # Initial delay for SSE stream to connect (first actor in pipeline only)
    await asyncio.sleep(0.2)

    value = payload.get("value", 0)

    await asyncio.sleep(0.3)  # Simulate processing time for pipeline testing

    return {
        **payload,
        "value": value * 2,
        "operation": "doubled",
    }


async def pipeline_incrementer(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Pipeline incrementer: Second actor in pipeline, adds 5 to the value.

    Part of multi-actor pipeline tests.
    """
    value = payload.get("value", 0)

    await asyncio.sleep(0.3)  # Simulate processing time for pipeline testing

    return {
        **payload,
        "value": value + 5,
        "operation": "incremented",
    }


# =============================================================================
# Edge Cases & Data Handling (async)
# =============================================================================


async def large_payload_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Large payload handler: Processes and returns large data.

    Tests protocol handling of messages near size limits.
    """
    size_kb = payload.get("size_kb", 100)

    # Generate large response
    large_data = "X" * (size_kb * 1024)

    return {
        **payload,
        "data_size_kb": size_kb,
        "data": large_data,
        "handler": "large_payload",
    }


async def unicode_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Unicode handler: Handles international characters.

    Tests proper UTF-8 encoding/decoding across the protocol.
    """

    return {
        **payload,
        "message": "处理成功",
        "test_chars": "test_unicode_chars",
        "languages": {
            "chinese": "你好世界",
            "japanese": "こんにちは世界",
            "hebrew": "שלום עולם",
            "russian": "Привет мир",
        },
    }


async def nested_data_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Nested data handler: Returns deeply nested structures.

    Tests JSON parsing of complex nested objects.
    """

    # Create nested structure
    nested: dict[str, object] = {"level": 0, "data": payload}
    current: dict[str, object] = nested
    for i in range(1, 20):
        next_level: dict[str, object] = {"level": i, "data": f"level_{i}"}
        current["next"] = next_level
        current = next_level

    return {
        **payload,
        "nested_depth": 20,
        "structure": nested,
    }


async def null_values_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Null values handler: Tests handling of None/null values.

    Returns structure with null values to test JSON serialization.
    """

    return {
        **payload,
        "null_field": None,
        "list_with_nulls": [1, None, 3, None, 5],
        "nested": {
            "value_null": None,
            "value_int": 123,
        },
    }


# =============================================================================
# Conditional & Metadata Handlers
# =============================================================================


def conditional_handler(payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    Conditional handler: Behavior based on payload content.

    Used for testing specific conditions from test suite.
    Supports actions: success, error, oom, slow, empty
    """
    action = payload.get("action", "success")

    if action == "error":
        raise ValueError(f"Conditional error: {payload.get('error_msg', 'test')}")
    elif action == "oom":
        raise MemoryError("Conditional OOM")
    elif action == "slow":
        time.sleep(payload.get("sleep", 2))  # Simulate slow processing for testing
        return {**payload, "status": "slow_processing_complete"}
    elif action == "empty":
        return None
    else:
        return {**payload, "status": "success", "action": action}


def conditional_fanout_handler(payload: dict[str, Any]) -> Generator[dict[str, Any], None, None]:
    """
    Fan-out variant of conditional_handler. Yields multiple results.
    """
    count = payload.get("count", 2)
    for i in range(count):
        yield {"index": i, "action": "fanout"}


def metadata_handler(payload: dict[str, Any], route: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Metadata handler: Tests ASYA_INCLUDE_ROUTE_INFO functionality.

    When ASYA_INCLUDE_ROUTE_INFO=true, route parameter is passed.
    Otherwise, route=None (default mode).

    Args:
        payload: Message payload dict
        route: Optional route information (present when ASYA_INCLUDE_ROUTE_INFO=true)

    Returns:
        Result dict with metadata information
    """
    has_route = route is not None

    result = {
        **payload,
        "has_metadata": has_route,
    }

    if has_route and route is not None:
        result["route_info"] = {
            "actors": route.get("actors", []),
            "current": route.get("current", 0),
        }

    return result


# =============================================================================
# Route Edge Cases (sync - error/edge-case handlers)
# =============================================================================


def cyclic_route_detector(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Cyclic route detector: Tracks visits to detect infinite loops.

    Increments visit_count each time this actor is called.
    If visit_count > 10, raises error to prevent infinite loop.
    """
    visit_count = payload.get("visit_count", 0) + 1

    if visit_count > 10:
        raise ValueError(f"Cyclic route detected: actor visited {visit_count} times")

    return {
        **payload,
        "visit_count": visit_count,
        "status": f"visit_{visit_count}",
    }


def malformed_json_handler(payload: dict[str, Any]) -> str:
    """
    Malformed JSON handler: Returns invalid JSON string.

    This should trigger a parse error in the sidecar.
    """
    return "{invalid json: this is not valid JSON"


def huge_payload_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Huge payload handler: Generates payload exceeding message size limits.

    Default RabbitMQ max message size is 128MB.
    This generates a 200MB payload to test size limit handling.
    """
    size_mb = payload.get("size_mb", 200)

    # Generate huge payload (200MB of 'X' characters)
    huge_data = "X" * (size_mb * 1024 * 1024)

    return {
        **payload,
        "data_size_mb": size_mb,
        "data": huge_data,
    }


# =============================================================================
# Retry & Transient Error Handlers (sync - error/edge-case handlers)
# =============================================================================


def transient_error_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Transient error handler: Fails N times then succeeds.

    Used to test retry logic in x-sump actor.
    Tracks attempt_count in payload.
    """
    attempt_count = payload.get("attempt_count", 0) + 1
    max_failures = payload.get("max_failures", 3)

    if attempt_count <= max_failures:
        # Update attempt count before raising
        payload["attempt_count"] = attempt_count
        raise RuntimeError(f"Transient error (attempt {attempt_count}/{max_failures})")

    # Success after N failures
    return {
        **payload,
        "attempt_count": attempt_count,
        "status": "success_after_retries",
    }


def slow_then_fast_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Slow then fast handler: First call is slow, subsequent calls are fast.

    Used to test timeout at actor boundaries.
    """
    first_call = payload.get("first_call", True)

    if first_call:
        time.sleep(1.5)  # Buffer for system overhead (gateway timeout is 4s total)
        return {
            **payload,
            "first_call": False,
            "duration": "1.5s",
        }
    else:
        time.sleep(0.1)  # Fast second call to test if it completes before timeout
        return {
            **payload,
            "duration": "0.1s",
            "status": "fast_complete",
        }


# =============================================================================
# Database & State Handlers (async)
# =============================================================================


async def stateful_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Stateful handler: Tracks state across invocations.

    Used to test idempotency and duplicate detection.
    Payload must include 'idempotency_key' field.
    """
    idempotency_key = payload.get("idempotency_key")

    if not idempotency_key:
        raise ValueError("Missing idempotency_key for stateful handler")

    # In real implementation, this would check database
    # For tests, we just echo back the key
    return {
        **payload,
        "processed_key": idempotency_key,
        "timestamp": time.time(),
    }


# =============================================================================
# Parameter Flow Testing (async)
# =============================================================================


async def param_flow_actor_1(payload: dict[str, Any]) -> dict[str, Any]:
    """
    First actor in parameter flow test pipeline.

    Receives original MCP tool parameters and transforms them.
    Returns new structure to verify second actor receives this output.

    Args:
        payload: Should contain {"original_param": "value", "number": N}

    Returns:
        Transformed payload with actor_1 metadata
    """
    return {
        "actor_1_received": payload.copy(),
        "actor_1_transformed": {
            "original_param": payload.get("original_param"),
            "number_doubled": payload.get("number", 0) * 2,
        },
        "processed_by": "actor_1",
    }


async def param_flow_actor_2(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Second actor in parameter flow test pipeline.

    Should receive OUTPUT from actor_1, NOT original MCP parameters.
    This validates that multi-actor pipelines pass outputs correctly.

    Args:
        payload: Should contain output from actor_1

    Returns:
        Payload with verification of what was received
    """
    return {
        "actor_2_received": payload.copy(),
        "actor_2_verification": {
            "received_from_actor_1": "actor_1_received" in payload,
            "has_original_params": "original_param" in payload,
            "processed_by_chain": [payload.get("processed_by"), "actor_2"],
        },
        "processed_by": "actor_2",
    }


# =============================================================================
# Multi-Hop Testing (async)
# =============================================================================


async def multihop_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Multi-hop handler: Passes message through chain of actors.

    Tracks which actors have processed the message by appending to a list.
    Used for testing long actor chains (10-20 actors).

    Args:
        payload: Should contain {"hop_number": N, "processed_by": [...]}

    Returns:
        Updated payload with current hop recorded
    """
    hop_number = payload.get("hop_number", 0)
    processed_by = payload.get("processed_by", [])

    processed_by.append(f"hop-{hop_number}")

    await asyncio.sleep(0.5)  # Delay to allow SSE to capture intermediate progress updates

    return {
        **payload,
        "hop_number": hop_number + 1,
        "processed_by": processed_by,
        "timestamp": time.time(),
    }
