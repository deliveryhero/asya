"""
Pytest fixtures for unit-testing actor handler functions locally.

These fixtures drive generator handlers and capture all emitted events
without filtering — downstream frames, FLY streaming events, and ABI
commands are all available for assertion.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest


@dataclass
class HandlerResult:
    """
    Captured output from running a handler generator in a test.

    Attributes:
        frames: Downstream payloads — dicts yielded by the handler,
                routed to the next actor by the sidecar in production.
        fly:    Upstream streaming events — the data portion of every
                ``yield "FLY", {...}`` call, delivered via SSE to the
                gateway in production.
        abi:    Other ABI commands — every ``("SET", ..)``, ``("GET", ...)``,
                or ``("DEL", ...)`` tuple yielded by the handler.
    """

    frames: list[dict] = field(default_factory=list)
    fly: list[dict] = field(default_factory=list)
    abi: list[tuple] = field(default_factory=list)

    @property
    def payload(self) -> dict:
        """
        The single emitted downstream frame.

        Raises AssertionError if the handler emitted zero or more than one
        frame — use ``frames`` directly for fan-out handlers.
        """
        if len(self.frames) != 1:
            raise AssertionError(f"Expected exactly 1 downstream frame, got {len(self.frames)}: {self.frames}")
        return self.frames[0]


@pytest.fixture
def run_handler():
    """
    Drive a generator handler and capture all emitted events.

    Usage::

        async def test_routing(run_handler):
            result = await run_handler(my_handler({"text": "hello"}))
            assert result.payload["label"] == "greeting"
            assert ("SET", ".route.next", ["reviewer"]) in result.abi

        async def test_streaming(run_handler):
            result = await run_handler(llm_handler({"query": "hi"}))
            assert len(result.fly) > 0
            assert result.fly[0]["type"] == "text_delta"

    Returns a ``HandlerResult`` with:

    - ``frames`` — downstream payloads (yielded dicts, forwarded to next actor)
    - ``fly``    — upstream SSE events (FLY payloads, delivered to gateway)
    - ``abi``    — other ABI commands (SET / GET / DEL tuples)

    Nothing is filtered or muted — all events are captured for assertion.
    Plain function handlers (non-generator) are also supported: their
    return value is wrapped into a single-frame result automatically.
    """

    async def _run(handler_call: Any, get_responses: dict | None = None) -> HandlerResult:
        """Drive a handler and capture all emitted events.

        Args:
            handler_call: The result of calling a handler function — an async
                generator, sync generator, or coroutine.
            get_responses: Optional mapping of ABI path → value to send back
                for ``yield "GET", path`` calls. Use this when testing
                generators that read envelope metadata via GET.
                Example: ``{"headers": {"trace_id": "abc"}, ".route.prev": []}``
        """
        import inspect

        result = HandlerResult()
        responses = get_responses or {}

        def _classify(event: Any) -> None:
            if isinstance(event, tuple) and len(event) >= 2 and event[0] == "FLY":
                result.fly.append(event[1])
            elif isinstance(event, tuple):
                result.abi.append(event)
            else:
                result.frames.append(event)

        def _get_send_value(event: Any) -> Any:
            """Return the value to send back for a GET verb."""
            if isinstance(event, tuple) and len(event) == 2 and event[0] == "GET":
                path = event[1]
                # Try exact path match first, then strip leading dot
                if path in responses:
                    return responses[path]
                stripped = path.lstrip(".")
                if stripped in responses:
                    return responses[stripped]
            return None

        if inspect.isasyncgen(handler_call):
            send_val: Any = None
            gen = handler_call
            while True:
                try:
                    event = await gen.asend(send_val)
                    send_val = _get_send_value(event)
                    _classify(event)
                except StopAsyncIteration:
                    break
        elif inspect.isgenerator(handler_call):
            send_val = None
            sync_gen = handler_call
            while True:
                try:
                    event = sync_gen.send(send_val)
                    send_val = _get_send_value(event)
                    _classify(event)
                except StopIteration:
                    break
        elif inspect.iscoroutine(handler_call):
            ret = await handler_call
            if ret is not None:
                frames = ret if isinstance(ret, list) else [ret]
                result.frames.extend(frames)
        else:
            raise TypeError(f"Expected an async generator, sync generator, or coroutine, got {type(handler_call)}")

        return result

    return _run
