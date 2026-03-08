#!/usr/bin/env python3
"""Tests for smart JSON serialization: pydantic, dataclasses, namedtuples, etc."""

import dataclasses
import json
import sys
from collections import namedtuple
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import asya_runtime
from tests.test_asya_runtime import call_invoke


# ---------------------------------------------------------------------------
# Mock objects that duck-type pydantic / dataclass protocols
# (no pydantic import needed — runtime is dependency-free)
# ---------------------------------------------------------------------------


class _PydanticV2Model:
    """Duck-typed pydantic v2 BaseModel."""

    def __init__(self, **fields):
        self._fields = fields

    def model_dump(self, mode=None):
        if mode == "json":
            return {k: str(v) if isinstance(v, bytes) else v for k, v in self._fields.items()}
        return dict(self._fields)


class _PydanticV1Model:
    """Duck-typed pydantic v1 BaseModel (has both .dict() and .__fields__)."""

    __fields__ = {}

    def __init__(self, **fields):
        self._fields = fields
        self.__fields__ = {k: None for k in fields}

    def dict(self):
        return dict(self._fields)


@dataclasses.dataclass
class _SimpleDataclass:
    name: str
    value: int


Point = namedtuple("Point", ["x", "y"])


# ---------------------------------------------------------------------------
# Envelope builder helper
# ---------------------------------------------------------------------------


def _envelope(payload=None, next_actors=None):
    return {
        "id": "test-id",
        "route": {"prev": [], "curr": "actor-a", "next": next_actors or []},
        "payload": payload or {},
    }


# ---------------------------------------------------------------------------
# Unit tests for _json_default
# ---------------------------------------------------------------------------


class TestJsonDefault:
    """Unit tests for the _json_default serialization hook."""

    def test_pydantic_v2_model_serialized_via_model_dump(self):
        obj = _PydanticV2Model(status="done", count=3)
        result = asya_runtime._json_default(obj)
        assert result == {"status": "done", "count": 3}

    def test_pydantic_v2_mode_json_used(self):
        """model_dump(mode='json') is called, not model_dump()."""
        calls = []

        class TrackingModel:
            def model_dump(self, mode=None):
                calls.append(mode)
                return {"x": 1}

        asya_runtime._json_default(TrackingModel())
        assert calls == ["json"]

    def test_pydantic_v1_model_serialized_via_dict(self):
        obj = _PydanticV1Model(name="alice", score=42)
        result = asya_runtime._json_default(obj)
        assert result == {"name": "alice", "score": 42}

    def test_dataclass_serialized_via_asdict(self):
        obj = _SimpleDataclass(name="widget", value=7)
        result = asya_runtime._json_default(obj)
        assert result == {"name": "widget", "value": 7}

    def test_namedtuple_serialized_via_asdict(self):
        obj = Point(x=10, y=20)
        result = asya_runtime._json_default(obj)
        assert result == {"x": 10, "y": 20}

    def test_datetime_serialized_as_isoformat(self):
        obj = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = asya_runtime._json_default(obj)
        assert result == "2024-06-01T12:00:00+00:00"

    def test_date_serialized_as_isoformat(self):
        obj = date(2024, 6, 1)
        result = asya_runtime._json_default(obj)
        assert result == "2024-06-01"

    def test_bytes_serialized_as_base64(self):
        obj = b"hello"
        result = asya_runtime._json_default(obj)
        assert result == "aGVsbG8="

    def test_set_serialized_as_list(self):
        obj = {1, 2, 3}
        result = asya_runtime._json_default(obj)
        assert sorted(result) == [1, 2, 3]

    def test_frozenset_serialized_as_list(self):
        obj = frozenset(["a", "b"])
        result = asya_runtime._json_default(obj)
        assert sorted(result) == ["a", "b"]

    def test_unsupported_type_raises_type_error(self):
        class Opaque:
            pass

        with pytest.raises(TypeError, match="Not JSON serializable: Opaque"):
            asya_runtime._json_default(Opaque())

    def test_unsupported_callable_raises_type_error(self):
        with pytest.raises(TypeError, match="Not JSON serializable"):
            asya_runtime._json_default(lambda: None)


# ---------------------------------------------------------------------------
# Integration: function handler returning typed objects
# ---------------------------------------------------------------------------


class TestFunctionHandlerSmartSerialization:
    """Function handlers can return typed objects; runtime serializes them."""

    def test_function_returns_pydantic_v2_model(self):
        def handler(payload):
            return _PydanticV2Model(result="ok", value=42)

        frames = call_invoke(_envelope(), handler)
        assert len(frames) == 1
        assert frames[0]["payload"] == {"result": "ok", "value": 42}

    def test_function_returns_dataclass(self):
        def handler(payload):
            return _SimpleDataclass(name="thing", value=99)

        frames = call_invoke(_envelope(), handler)
        assert len(frames) == 1
        assert frames[0]["payload"] == {"name": "thing", "value": 99}

    def test_function_returns_dict_with_nested_pydantic_value(self):
        def handler(payload):
            return {"artifact": _PydanticV2Model(type="text", data="hello")}

        frames = call_invoke(_envelope(), handler)
        assert len(frames) == 1
        assert frames[0]["payload"] == {"artifact": {"type": "text", "data": "hello"}}

    def test_function_returns_dict_with_datetime_value(self):
        def handler(payload):
            return {"ts": datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)}

        frames = call_invoke(_envelope(), handler)
        assert len(frames) == 1
        assert frames[0]["payload"]["ts"] == "2024-01-15T10:00:00+00:00"

    def test_plain_dict_regression(self):
        def handler(payload):
            return {"echo": payload.get("x")}

        frames = call_invoke(_envelope(payload={"x": 5}), handler)
        assert len(frames) == 1
        assert frames[0]["payload"] == {"echo": 5}

    def test_function_returns_pydantic_v1_model(self):
        def handler(payload):
            return _PydanticV1Model(name="bob", score=100)

        frames = call_invoke(_envelope(), handler)
        assert len(frames) == 1
        assert frames[0]["payload"] == {"name": "bob", "score": 100}


# ---------------------------------------------------------------------------
# Integration: generator handler yielding typed objects
# ---------------------------------------------------------------------------


class TestGeneratorHandlerSmartSerialization:
    """Generator handlers can yield typed objects as payload frames."""

    def test_generator_yields_pydantic_v2_model_as_frame(self):
        def handler(payload):
            yield _PydanticV2Model(result="gen-ok")

        frames = call_invoke(_envelope(), handler)
        assert len(frames) == 1
        assert frames[0]["payload"] == {"result": "gen-ok"}

    def test_generator_yields_dataclass_as_frame(self):
        def handler(payload):
            yield _SimpleDataclass(name="gen-thing", value=7)

        frames = call_invoke(_envelope(), handler)
        assert len(frames) == 1
        assert frames[0]["payload"] == {"name": "gen-thing", "value": 7}

    def test_generator_yields_multiple_typed_frames(self):
        def handler(payload):
            yield _PydanticV2Model(part=1)
            yield _PydanticV2Model(part=2)

        frames = call_invoke(_envelope(), handler)
        assert len(frames) == 2
        assert frames[0]["payload"] == {"part": 1}
        assert frames[1]["payload"] == {"part": 2}

    def test_generator_yields_dict_with_nested_pydantic(self):
        def handler(payload):
            yield {"artifact": _PydanticV2Model(type="text")}

        frames = call_invoke(_envelope(), handler)
        assert len(frames) == 1
        assert frames[0]["payload"] == {"artifact": {"type": "text"}}


# ---------------------------------------------------------------------------
# Integration: async function and async generator handlers
# ---------------------------------------------------------------------------


class TestAsyncHandlerSmartSerialization:
    """Async handlers serialize typed objects the same way."""

    def test_async_function_returns_pydantic_v2_model(self):
        async def handler(payload):
            return _PydanticV2Model(result="async-ok")

        frames = call_invoke(_envelope(), handler)
        assert len(frames) == 1
        assert frames[0]["payload"] == {"result": "async-ok"}

    def test_async_generator_yields_pydantic_v2_model(self):
        async def handler(payload):
            yield _PydanticV2Model(chunk=1)
            yield _PydanticV2Model(chunk=2)

        frames = call_invoke(_envelope(), handler)
        assert len(frames) == 2
        assert frames[0]["payload"] == {"chunk": 1}
        assert frames[1]["payload"] == {"chunk": 2}


# ---------------------------------------------------------------------------
# Integration: FLY events with typed objects
# ---------------------------------------------------------------------------


class TestFlyEventSmartSerialization:
    """FLY events (SSE upstream) can carry typed objects."""

    def _collect_fly_payloads(self, handler_func):
        """Run generator and collect FLY payloads as JSON-serialized+parsed dicts."""
        import inspect

        envelope = _envelope()
        ctx = asya_runtime._AbiContext(envelope)
        fly_events = []

        def on_fly(payload):
            serialized = json.dumps({"payload": payload}, default=asya_runtime._json_default)
            fly_events.append(json.loads(serialized)["payload"])

        if inspect.isasyncgenfunction(handler_func):
            import asyncio

            asyncio.run(
                asya_runtime._drive_async_generator(
                    handler_func(envelope["payload"]), ctx, on_fly=on_fly
                )
            )
        else:
            asya_runtime._drive_generator(
                handler_func(envelope["payload"]), ctx, on_fly=on_fly
            )
        return fly_events

    def test_fly_with_pydantic_v2_model(self):
        def handler(payload):
            yield "FLY", _PydanticV2Model(type="text_delta", token="hello")

        fly_events = self._collect_fly_payloads(handler)
        assert fly_events == [{"type": "text_delta", "token": "hello"}]

    def test_fly_with_dict_containing_pydantic(self):
        def handler(payload):
            yield "FLY", {"event": _PydanticV2Model(type="status", state="working")}

        fly_events = self._collect_fly_payloads(handler)
        assert fly_events == [{"event": {"type": "status", "state": "working"}}]

    def test_fly_plain_dict_regression(self):
        def handler(payload):
            yield "FLY", {"type": "text_delta", "token": "world"}

        fly_events = self._collect_fly_payloads(handler)
        assert fly_events == [{"type": "text_delta", "token": "world"}]
