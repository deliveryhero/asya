#!/usr/bin/env python3
"""
Prototype: Inline thin driver for local testing of yield-protocol actors.

This shows that a router handler file is SELF-CONTAINED:
- The handler is pure Python (async generator with yield protocol)
- The driver is 12 lines of stdlib-only code, inlined in the same file
- `python my_router.py` runs locally with zero external dependencies
- In production, asya_runtime.py drives the same handler via asend()
"""
import asyncio
import inspect


# ─── ACTOR HANDLERS (pure Python, no imports) ──────────────────────


async def simple_actor(payload: dict) -> dict:
    """Simple actor: return only. Works with or without driver."""
    return {"result": payload["input"].upper()}


async def streaming_actor(payload: dict) -> dict:
    """Streaming actor: yield only dicts. Works with simple async for."""
    for word in payload["text"].split():
        yield {"partial": True, "token": word}
    yield {"text": payload["text"].upper()}


async def conditional_router(payload: dict) -> dict:
    """Router: uses yield protocol for metadata. Needs driver."""
    route = yield ".route"
    headers = yield ".headers"

    if payload.get("priority") == "high":
        route["actors"].insert(route["current"] + 1, "fast-track")
    else:
        route["actors"].insert(route["current"] + 1, "standard-track")

    yield ".route", route
    yield payload


async def fan_out_router(payload: dict) -> dict:
    """Fan-out router: sends payloads to different routes."""
    route = yield ".route"
    original_actors = route["actors"][:]

    yield ".route", {"actors": ["path-a", "merge"], "current": 0}
    yield {**payload, "branch": "a"}

    yield ".route", {"actors": ["path-b", "merge"], "current": 0}
    yield {**payload, "branch": "b"}


async def composed_actor(payload: dict) -> dict:
    """Composition: wraps streaming_actor. No protocol needed."""
    async for event in streaming_actor(payload):
        event["seen_by"] = "composed"
        yield event


# ─── INLINE DRIVER (12 lines, stdlib only, copy-paste anywhere) ───


async def drive(fn, payload, route=None, headers=None):
    """Thin local driver for any actor (simple, streaming, or router)."""
    meta = {"route": route or {}, "headers": headers or {}, "id": "test"}
    if not inspect.isasyncgenfunction(fn):
        r = await fn(payload)
        return [r] if r is not None else []
    out, gen, v = [], fn(payload), None
    try:
        while True:
            y = await gen.asend(v); v = None
            if isinstance(y, dict): out.append(y)
            elif isinstance(y, str): v = meta.get(y.lstrip("."))
            elif isinstance(y, tuple): meta[y[0].lstrip(".")] = y[1]
    except StopAsyncIteration:
        pass
    return out


# ─── LOCAL TESTS ──────────────────────────────────────────────────


async def main():
    print("=== Simple Actor ===")
    frames = await drive(simple_actor, {"input": "hello"})
    for f in frames:
        print(f"  {f}")

    print("\n=== Streaming Actor ===")
    frames = await drive(streaming_actor, {"text": "hello world"})
    for f in frames:
        print(f"  {f}")

    print("\n=== Composed Actor ===")
    frames = await drive(composed_actor, {"text": "compose me"})
    for f in frames:
        print(f"  {f}")

    print("\n=== Conditional Router (priority=high) ===")
    frames = await drive(
        conditional_router,
        {"priority": "high", "data": "urgent"},
        route={"actors": ["router", "default", "end"], "current": 0},
    )
    for f in frames:
        print(f"  {f}")

    print("\n=== Conditional Router (priority=normal) ===")
    frames = await drive(
        conditional_router,
        {"priority": "normal", "data": "routine"},
        route={"actors": ["router", "default", "end"], "current": 0},
    )
    for f in frames:
        print(f"  {f}")

    print("\n=== Fan-out Router ===")
    frames = await drive(
        fan_out_router,
        {"content": "multimodal"},
        route={"actors": ["router", "default"], "current": 0},
    )
    for f in frames:
        print(f"  {f}")

    # Verify: drive() returns the mutated meta state too?
    # Let's check by inspecting what conditional_router did to route
    print("\n=== Verify route mutation is visible ===")
    meta_route = {"actors": ["router", "end"], "current": 0}
    frames = await drive(
        conditional_router,
        {"priority": "high"},
        route=meta_route,
    )
    print(f"  Route after drive: {meta_route}")
    # Note: meta_route is mutated in-place by the handler!


if __name__ == "__main__":
    asyncio.run(main())
