"""
Envelope-mode wrapper handlers for integration and E2E tests.

This module wraps all payload-mode handlers from mock_payload_handlers.py
to work in envelope mode. All business logic is reused - these wrappers only
handle message extraction and reconstruction.

Message wire format:
{
  "id": "<message-id>",
  "route": {"actors": ["q1", "q2"], "current": 0},
  "headers": {"trace_id": "...", "priority": "high"},
  "payload": <arbitrary JSON>
}

Wrapper pattern:
1. Extract payload from message
2. Call original payload handler
3. Reconstruct message with handler result as new payload
4. Preserve route and headers (automatic behavior)
"""

import inspect
from typing import Any

from . import payload as payload_handlers


def _wrap_payload_handler(handler_func):
    """
    Generic wrapper to convert payload handler to envelope handler.

    Preserves async/sync nature: if the inner handler is async, the wrapper
    is async too, so inspect.iscoroutinefunction() detection works correctly
    in the runtime's _call_handler().

    Args:
        handler_func: Payload-mode handler function (sync or async)

    Returns:
        Envelope-mode wrapper function (matching sync/async of input)
    """

    def _build_response(result_payload, message):
        output_route = message["route"].copy()
        output_route["current"] = message["route"]["current"] + 1

        if isinstance(result_payload, list):
            return [
                {"payload": item, "route": output_route, "headers": message.get("headers", {})}
                for item in result_payload
            ]

        if result_payload is None:
            return None

        return {"payload": result_payload, "route": output_route, "headers": message.get("headers", {})}

    if inspect.iscoroutinefunction(handler_func):

        async def async_envelope_wrapper(message: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]] | None:
            result_payload = await handler_func(message["payload"])
            return _build_response(result_payload, message)

        async_envelope_wrapper.__doc__ = f"Envelope-mode wrapper for {handler_func.__name__}"
        return async_envelope_wrapper

    def envelope_wrapper(message: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]] | None:
        result_payload = handler_func(message["payload"])
        return _build_response(result_payload, message)

    envelope_wrapper.__doc__ = f"Envelope-mode wrapper for {handler_func.__name__}"
    return envelope_wrapper


echo_handler = _wrap_payload_handler(payload_handlers.echo_handler)
error_handler = _wrap_payload_handler(payload_handlers.error_handler)
oom_handler = _wrap_payload_handler(payload_handlers.oom_handler)
cuda_oom_handler = _wrap_payload_handler(payload_handlers.cuda_oom_handler)
timeout_handler = _wrap_payload_handler(payload_handlers.timeout_handler)
fanout_handler = _wrap_payload_handler(payload_handlers.fanout_handler)
empty_response_handler = _wrap_payload_handler(payload_handlers.empty_response_handler)
none_response_handler = _wrap_payload_handler(payload_handlers.none_response_handler)
pipeline_doubler = _wrap_payload_handler(payload_handlers.pipeline_doubler)
pipeline_incrementer = _wrap_payload_handler(payload_handlers.pipeline_incrementer)
large_payload_handler = _wrap_payload_handler(payload_handlers.large_payload_handler)
unicode_handler = _wrap_payload_handler(payload_handlers.unicode_handler)
nested_data_handler = _wrap_payload_handler(payload_handlers.nested_data_handler)
null_values_handler = _wrap_payload_handler(payload_handlers.null_values_handler)
conditional_handler = _wrap_payload_handler(payload_handlers.conditional_handler)
cyclic_route_detector = _wrap_payload_handler(payload_handlers.cyclic_route_detector)
malformed_json_handler = _wrap_payload_handler(payload_handlers.malformed_json_handler)
huge_payload_handler = _wrap_payload_handler(payload_handlers.huge_payload_handler)
transient_error_handler = _wrap_payload_handler(payload_handlers.transient_error_handler)
slow_then_fast_handler = _wrap_payload_handler(payload_handlers.slow_then_fast_handler)
stateful_handler = _wrap_payload_handler(payload_handlers.stateful_handler)
param_flow_actor_1 = _wrap_payload_handler(payload_handlers.param_flow_actor_1)
param_flow_actor_2 = _wrap_payload_handler(payload_handlers.param_flow_actor_2)


def invalid_route_current_handler(message: dict[str, Any]) -> dict[str, Any]:
    """
    Handler that returns route.current out of range.

    This tests sidecar behavior when ASYA_ENABLE_VALIDATION=false in runtime
    and the handler incorrectly sets route.current beyond the actors array length.

    The sidecar should handle this gracefully by routing to happy-end.
    """
    payload = message["payload"]
    output_route = message["route"].copy()

    # Set current to an invalid index (beyond actors array)
    actors_length = len(output_route["actors"])
    output_route["current"] = actors_length + 5

    return {"payload": payload, "route": output_route, "headers": message.get("headers", {})}
