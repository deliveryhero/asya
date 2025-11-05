"""
Mock runtime handlers for integration and E2E tests.

This module provides test handlers covering various scenarios:
- Happy path processing
- Error handling (ValueError, MemoryError, CUDA OOM)
- Timeouts and slow processing
- Fan-out (returning multiple results)
- Empty responses
- Large payloads and Unicode handling
- Pipeline processing (doubler, incrementer)
- Progress tracking

These handlers are shared across all integration and E2E tests.
Progress reporting is handled automatically by the Go sidecar.
"""

import time
from typing import Any, Dict, List, Union, Optional


# =============================================================================
# Happy Path & Basic Handlers
# =============================================================================

def echo_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
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
        time.sleep(0.5)  # Simulate processing time for SSE streaming testing
        return {"echoed": payload["message"]}

    # Otherwise, return exact payload
    return payload


# =============================================================================
# Error Handling
# =============================================================================

def error_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
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



def oom_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    OOM handler: Raises MemoryError to test OOM detection.

    This should result in oom_error with severity=recoverable.

    Args:
        payload: Message payload dict (unused)
    """
    raise MemoryError("Simulated out of memory condition")


def cuda_oom_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    CUDA OOM handler: Raises CUDA-like error.

    This should result in cuda_oom_error with severity=recoverable.
    """
    raise RuntimeError("CUDA out of memory: Tried to allocate 4.0 GiB")


# =============================================================================
# Timeout & Slow Processing
# =============================================================================

def timeout_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
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
# Fan-out & Empty Responses
# =============================================================================

def fanout_handler(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Fan-out handler: Returns multiple results.

    Tests that sidecar properly handles list responses and routes
    each result to the next step.
    """
    count = payload.get("count", 3)

    return [
        {**payload, "index": i, "message": f"Fan-out message {i}"}
        for i in range(count)
    ]


def empty_response_handler(payload: Dict[str, Any]) -> list:
    """
    Empty response handler: Returns empty list to abort pipeline.

    This should send the original message to happy-end queue.
    """
    return []


def none_response_handler(payload: Dict[str, Any]) -> list:
    """
    None response handler: Returns None to abort pipeline.

    This should send the original message to happy-end queue.
    """
    return None

# =============================================================================
# Pipeline Processing
# =============================================================================

def pipeline_doubler(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pipeline doubler: First step in pipeline, doubles the input value.

    Part of multi-step pipeline tests.
    """
    value = payload.get("value", 0)

    time.sleep(0.3)  # Simulate processing time for pipeline testing

    return {
        **payload,
        "value": value * 2,
        "operation": "doubled",
    }


def pipeline_incrementer(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pipeline incrementer: Second step in pipeline, adds 5 to the value.

    Part of multi-step pipeline tests.
    """
    value = payload.get("value", 0)

    time.sleep(0.3)  # Simulate processing time for pipeline testing

    return {
        **payload,
        "value": value + 5,
        "operation": "incremented",
    }


# =============================================================================
# Progress Tracking
# =============================================================================

def progress_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Progress handler: Simulates progress with multiple processing steps.

    Tests SSE progress streaming via automatic sidecar reporting.
    """
    steps = payload.get("steps", 3)

    for _ in range(steps):
        time.sleep(0.3)  # Simulate processing time for each step

    return {
        **payload,
        "steps_completed": steps,
    }


# =============================================================================
# Edge Cases & Data Handling
# =============================================================================

def large_payload_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
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


def unicode_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Unicode handler: Handles international characters.

    Tests proper UTF-8 encoding/decoding across the protocol.
    """

    return {
        **payload,
        "message": "处理成功 ✓",
        "emoji": "🚀🎉🌍",
        "languages": {
            "chinese": "你好世界",
            "japanese": "こんにちは世界",
            "arabic": "مرحبا بالعالم",
            "russian": "Привет мир",
        },
    }


def nested_data_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Nested data handler: Returns deeply nested structures.

    Tests JSON parsing of complex nested objects.
    """

    # Create nested structure
    nested = {"level": 0, "data": payload}
    current = nested
    for i in range(1, 20):
        current["next"] = {"level": i, "data": f"level_{i}"}
        current = current["next"]

    return {
        **payload,
        "nested_depth": 20,
        "structure": nested,
    }


def null_values_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
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

def conditional_handler(payload: Dict[str, Any]) -> Union[Dict[str, Any], List[Dict[str, Any]], None]:
    """
    Conditional handler: Behavior based on payload content.

    Used for testing specific conditions from test suite.
    Supports actions: success, error, oom, slow, fanout, empty
    """
    action = payload.get("action", "success")

    if action == "error":
        raise ValueError(f"Conditional error: {payload.get('error_msg', 'test')}")
    elif action == "oom":
        raise MemoryError("Conditional OOM")
    elif action == "slow":
        time.sleep(payload.get("sleep", 2))  # Simulate slow processing for testing
        return {**payload, "status": "slow_processing_complete"}
    elif action == "fanout":
        count = payload.get("count", 2)
        return [{"index": i, "action": "fanout"} for i in range(count)]
    elif action == "empty":
        return None
    else:
        return {**payload, "status": "success", "action": action}


def metadata_handler(payload: Dict[str, Any], route: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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

    if has_route:
        result["route_info"] = {
            "steps": route.get("steps", []),
            "current": route.get("current", 0),
        }

    return result
