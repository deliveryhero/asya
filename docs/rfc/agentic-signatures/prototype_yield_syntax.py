#!/usr/bin/env python3
"""
Prototype: Asya Actor Handler Yield Syntax RFC

Demonstrates the unified actor model with yield-based metadata access:

1. Coroutine actor    — async def returning dict (simplest)
2. Generator actor    — async def yielding dicts (streaming/fan-out)
3. Router actor       — async generator using yield protocol for route/headers

Yield protocol discrimination:
  yield dict                → PAYLOAD: emit frame to sidecar
  yield ".route"            → GET: runtime sends route back via asend()
  yield ".headers"          → GET: runtime sends headers back via asend()
  yield ".id"               → GET: runtime sends message id back via asend()
  yield (".route", value)   → SET: runtime updates route
  yield (".headers", value) → SET: runtime updates headers

Run: python prototype_yield_syntax.py
"""
import asyncio
import inspect
import json
from copy import deepcopy
from typing import Any


# ─── SIMULATED RUNTIME ─────────────────────────────────────────────


class Frame:
    """A single frame emitted by an actor, sent to the sidecar via unix socket."""

    def __init__(self, payload: dict, route: dict, headers: dict):
        self.payload = payload
        self.route = deepcopy(route)
        self.headers = deepcopy(headers)

    def __repr__(self):
        return (
            f"Frame(payload={self.payload}, "
            f"route={self.route}, "
            f"headers={self.headers})"
        )


class ActorRuntime:
    """
    Simulates asya_runtime.py behavior.

    Drives actor handlers and collects frames that would be sent to sidecar.
    Supports three handler forms:
    - Coroutine (async def → return dict)
    - Async generator (async def → yield dicts)
    - Async generator with yield protocol (yield strings/tuples for metadata)
    """

    def __init__(
        self,
        route: dict,
        headers: dict | None = None,
        msg_id: str = "msg-001",
    ):
        self.route = deepcopy(route)
        self.headers = deepcopy(headers or {})
        self.msg_id = msg_id

    async def run(self, handler, payload: dict) -> list[Frame]:
        """Run a handler and collect all emitted frames."""
        frames: list[Frame] = []

        if inspect.isasyncgenfunction(handler):
            frames = await self._run_generator(handler, payload)
        elif inspect.iscoroutinefunction(handler):
            frames = await self._run_coroutine(handler, payload)
        else:
            raise TypeError(
                f"Handler must be async function or async generator, "
                f"got {type(handler)}"
            )

        return frames

    async def _run_coroutine(self, handler, payload: dict) -> list[Frame]:
        """Drive a coroutine handler (single return value)."""
        result = await handler(payload)
        if result is None:
            return []  # abort execution
        return [Frame(result, self.route, self.headers)]

    async def _run_generator(self, handler, payload: dict) -> list[Frame]:
        """Drive an async generator handler (yield protocol)."""
        frames: list[Frame] = []
        gen = handler(payload)
        send_value: Any = None

        try:
            while True:
                value = await gen.asend(send_value)
                send_value = None

                if isinstance(value, dict):
                    # PAYLOAD → snapshot current route/headers into frame
                    frames.append(Frame(value, self.route, self.headers))

                elif isinstance(value, str) and value.startswith("."):
                    # GET metadata → send value back via asend()
                    field = value[1:]
                    if field == "route":
                        send_value = self.route
                    elif field == "headers":
                        send_value = self.headers
                    elif field == "id":
                        send_value = self.msg_id
                    else:
                        raise ValueError(f"Unknown metadata field: .{field}")

                elif isinstance(value, tuple) and len(value) == 2:
                    key, val = value
                    if isinstance(key, str) and key.startswith("."):
                        # SET metadata → update runtime state
                        field = key[1:]
                        if field == "route":
                            self.route = deepcopy(val)
                        elif field == "headers":
                            self.headers = deepcopy(val)
                        else:
                            raise ValueError(f"Unknown metadata field: .{field}")
                    else:
                        raise ValueError(
                            f"Unexpected yield tuple: {value!r}. "
                            f"SET commands must start with '.field'"
                        )
                else:
                    raise ValueError(
                        f"Unknown yield value: {value!r}. "
                        f"Expected dict (payload), '.field' (GET), "
                        f"or ('.field', value) (SET)"
                    )

        except StopAsyncIteration:
            pass

        return frames


# ─── ACTOR EXAMPLES ────────────────────────────────────────────────


# 1. Simple coroutine — the simplest possible actor (pure Python)
async def simple_actor(payload: dict) -> dict:
    """Transform input. No imports, no yield, just return."""
    return {"result": payload["input"].upper(), "processed": True}


# 2. Abort actor — returns None to stop the pipeline
async def filter_actor(payload: dict) -> dict:
    """Returns None if quality too low → message goes to happy-end."""
    if payload.get("quality", 0) < 0.5:
        return None
    return payload


# 3. Streaming actor — yields partial results then final
async def streaming_actor(payload: dict) -> dict:
    """Yields partial tokens upstream, then final result downstream.
    Sidecar distinguishes partial vs non-partial by inspecting payload."""
    words = payload["text"].split()
    for i, word in enumerate(words):
        yield {"partial": True, "token": word, "index": i}
    yield {"text": " ".join(w.upper() for w in words), "done": True}


# 4. Fan-out actor — multiple non-partial payloads
async def fan_out_actor(payload: dict) -> dict:
    """Each yield is a separate downstream message (fan-out)."""
    for lang in ["en", "fr", "de"]:
        yield {**payload, "language": lang}


# 5. Conditional router — reads route, inserts actor
async def conditional_router(payload: dict) -> dict:
    """Routes to different paths based on payload.
    Uses yield protocol to access and modify route."""
    route = yield ".route"
    headers = yield ".headers"

    if payload.get("priority") == "high":
        # Insert fast-track actor after current position
        route["actors"].insert(route["current"] + 1, "fast-track")
    else:
        route["actors"].insert(route["current"] + 1, "standard-track")

    yield ".route", route
    yield payload


# 6. Fan-out router — different routes per payload
async def fan_out_router(payload: dict) -> dict:
    """Sends different payloads to different routes.
    Each SET .route applies to subsequent yields until changed."""
    route = yield ".route"

    yield ".route", {**route, "actors": ["analyze-text", "summarize"]}
    yield {**payload, "branch": "text"}

    yield ".route", {**route, "actors": ["analyze-image", "caption"]}
    yield {**payload, "branch": "image"}


# 7. Header-aware actor — reads trace_id for observability
async def traced_actor(payload: dict) -> dict:
    """Reads headers for trace context without modifying route."""
    headers = yield ".headers"
    trace_id = headers.get("trace_id", "unknown")
    # In real code: send OTel span, custom metric, etc.
    yield {**payload, "trace_id": trace_id, "traced": True}


# 8. Composition — simple actor wrapping another simple actor
async def composed_actor(payload: dict) -> dict:
    """Composes streaming_actor, enriching each event.
    Safe because streaming_actor only yields dicts (no commands)."""
    async for event in streaming_actor(payload):
        event["enriched_by"] = "composed_actor"
        yield event


# 9. Dynamic route modification with multiple yields
async def pipeline_builder(payload: dict) -> dict:
    """Builds route dynamically based on payload content."""
    route = yield ".route"
    headers = yield ".headers"

    # Build pipeline based on what's in the payload
    new_actors = []
    if "text" in payload:
        new_actors.append("text-processor")
    if "image" in payload:
        new_actors.append("image-processor")
    if payload.get("needs_review"):
        new_actors.append("human-review")
    new_actors.append("finalizer")

    route["actors"] = route["actors"][: route["current"] + 1] + new_actors
    yield ".route", route

    # Also set a custom header
    headers["pipeline_length"] = len(new_actors)
    yield ".headers", headers

    yield payload


# ─── TEST RUNNER ───────────────────────────────────────────────────


async def run_example(
    name: str,
    handler,
    payload: dict,
    route: dict | None = None,
    headers: dict | None = None,
):
    """Run one example and print results."""
    route = route or {"actors": ["self", "next-actor", "final"], "current": 0}
    headers = headers or {"trace_id": "trace-abc"}

    runtime = ActorRuntime(route=route, headers=headers)
    frames = await runtime.run(handler, payload)

    print(f"\n{'=' * 70}")
    print(f"  {name}")
    print(f"{'=' * 70}")
    print(f"  Input:  {json.dumps(payload, default=str)}")
    print(f"  Route:  {json.dumps(route)}")
    print(f"  Frames: {len(frames)}")
    for i, frame in enumerate(frames):
        print(f"  [{i}] payload = {json.dumps(frame.payload, default=str)}")
        if frame.route != route:
            print(f"      route   = {json.dumps(frame.route)}")
        if frame.headers != headers:
            print(f"      headers = {json.dumps(frame.headers)}")
    if not frames:
        print("  (no frames emitted - execution aborted)")
    print()


async def main():
    print("=" * 70)
    print("  Asya Actor Handler Syntax Prototype")
    print("  Yield-based metadata access protocol")
    print("=" * 70)

    # ── Simple actors (pure Python, no protocol) ──

    await run_example(
        "1. Simple Actor (return dict)",
        simple_actor,
        {"input": "hello world"},
    )

    await run_example(
        "2. Filter Actor - PASSES (quality=0.8)",
        filter_actor,
        {"quality": 0.8, "data": "good"},
    )

    await run_example(
        "2. Filter Actor - ABORTS (quality=0.3)",
        filter_actor,
        {"quality": 0.3, "data": "bad"},
    )

    await run_example(
        "3. Streaming Actor (partial yields)",
        streaming_actor,
        {"text": "hello beautiful world"},
    )

    await run_example(
        "4. Fan-out Actor (multiple downstream payloads)",
        fan_out_actor,
        {"text": "translate me"},
    )

    # ── Composition (safe: sub-actor yields only dicts) ──

    await run_example(
        "8. Composed Actor (wraps streaming sub-actor)",
        composed_actor,
        {"text": "compose me please"},
    )

    # ── Routers (yield protocol for metadata) ──

    await run_example(
        "5. Conditional Router (priority=high)",
        conditional_router,
        {"priority": "high", "data": "urgent"},
        route={"actors": ["router", "default-track", "end"], "current": 0},
    )

    await run_example(
        "5. Conditional Router (priority=normal)",
        conditional_router,
        {"priority": "normal", "data": "routine"},
        route={"actors": ["router", "default-track", "end"], "current": 0},
    )

    await run_example(
        "6. Fan-out Router (different routes per payload)",
        fan_out_router,
        {"content": "multimodal data"},
        route={"actors": ["router", "default"], "current": 0},
    )

    await run_example(
        "7. Traced Actor (reads headers for observability)",
        traced_actor,
        {"data": "something"},
        headers={"trace_id": "abc-xyz-123", "priority": "high"},
    )

    await run_example(
        "9. Pipeline Builder (dynamic route construction)",
        pipeline_builder,
        {"text": "analyze this", "needs_review": True},
        route={"actors": ["pipeline-builder"], "current": 0},
    )


if __name__ == "__main__":
    asyncio.run(main())
