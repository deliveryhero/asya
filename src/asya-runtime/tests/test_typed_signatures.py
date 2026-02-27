#!/usr/bin/env python3
"""Tests for typed handler signatures in asya_runtime.py."""

import dataclasses
import sys
from pathlib import Path
from typing import Any, Dict

import pytest


# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asya_runtime


# Pydantic is optional
try:
    from pydantic import BaseModel

    HAS_PYDANTIC = True
except ImportError:
    BaseModel = None
    HAS_PYDANTIC = False


# Test handlers


def legacy_handler(payload: dict) -> dict:
    """Legacy dict handler."""
    return {"result": payload.get("value", 0) * 2}


def typed_simple(value: int) -> dict:
    """Typed handler with single int param."""
    return {"doubled": value * 2}


def typed_multi_params(x: int, y: int, z: int = 10) -> dict:
    """Typed handler with multiple params, one optional."""
    return {"sum": x + y + z}


def typed_scalar_return(value: int) -> int:
    """Typed handler returning scalar."""
    return value * 2


def typed_list_return(values: list) -> list:
    """Typed handler returning list."""
    return [v * 2 for v in values]


@dataclasses.dataclass
class Point:
    """Test dataclass."""

    x: int
    y: int


def typed_dataclass(point: Point) -> dict:
    """Typed handler with dataclass input."""
    return {"distance": (point.x**2 + point.y**2) ** 0.5}


def typed_dataclass_return(x: int, y: int) -> Point:
    """Typed handler with dataclass output."""
    return Point(x=x, y=y)


class StatefulProcessor:
    """Test class handler."""

    def __init__(self, multiplier: int = 3):
        self.multiplier = multiplier

    def process(self, value: int) -> dict:
        return {"result": value * self.multiplier}


class TestHandlerSignature:
    """Test HandlerSignature introspection."""

    def test_legacy_detection_dict(self):
        sig = asya_runtime.HandlerSignature(legacy_handler)
        assert sig.is_legacy is True

    def test_legacy_detection_dict_capital(self):
        def handler(payload: Dict) -> dict:
            return payload

        sig = asya_runtime.HandlerSignature(handler)
        assert sig.is_legacy is True

    def test_legacy_detection_dict_typed(self):
        def handler(payload: Dict[str, Any]) -> dict:
            return payload

        sig = asya_runtime.HandlerSignature(handler)
        assert sig.is_legacy is True

    def test_legacy_detection_no_annotation(self):
        def handler(payload):
            return payload

        sig = asya_runtime.HandlerSignature(handler)
        assert sig.is_legacy is True

    def test_typed_single_param(self):
        sig = asya_runtime.HandlerSignature(typed_simple)
        assert sig.is_legacy is False
        assert "value" in sig.params
        assert sig.params["value"]["required"] is True

    def test_typed_multi_params(self):
        sig = asya_runtime.HandlerSignature(typed_multi_params)
        assert sig.is_legacy is False
        assert "x" in sig.params
        assert "y" in sig.params
        assert "z" in sig.params
        assert sig.params["x"]["required"] is True
        assert sig.params["y"]["required"] is True
        assert sig.params["z"]["required"] is False
        assert sig.params["z"]["default"] == 10

    def test_class_handler_excludes_self(self):
        processor = StatefulProcessor()
        sig = asya_runtime.HandlerSignature(processor.process)
        assert "self" not in sig.params
        assert "value" in sig.params


class TestExtractValueAtPath:
    """Test _extract_value_at_path helper."""

    def test_root_path(self):
        data = {"a": 1, "b": 2}
        result = asya_runtime._extract_value_at_path(data, "/")
        assert result == data

    def test_empty_path(self):
        data = {"a": 1, "b": 2}
        result = asya_runtime._extract_value_at_path(data, "")
        assert result == data

    def test_single_key(self):
        data = {"a": 1, "b": 2}
        result = asya_runtime._extract_value_at_path(data, "/a")
        assert result == 1

    def test_nested_path(self):
        data = {"user": {"profile": {"name": "Alice"}}}
        result = asya_runtime._extract_value_at_path(data, "/user/profile/name")
        assert result == "Alice"

    def test_missing_key_raises(self):
        data = {"a": 1}
        with pytest.raises(KeyError):
            asya_runtime._extract_value_at_path(data, "/b")

    def test_invalid_path_raises(self):
        data = {"a": 1}
        with pytest.raises(KeyError):
            asya_runtime._extract_value_at_path(data, "/a/b")


class TestSetValueAtPath:
    """Test _set_value_at_path helper."""

    def test_root_path_dict(self):
        data = {"a": 1}
        asya_runtime._set_value_at_path(data, "/", {"b": 2})
        assert data == {"a": 1, "b": 2}

    def test_single_key_scalar(self):
        data = {}
        asya_runtime._set_value_at_path(data, "/result", 42)
        assert data == {"result": 42}

    def test_single_key_dict(self):
        data = {"result": {"old": 1}}
        asya_runtime._set_value_at_path(data, "/result", {"new": 2})
        assert data == {"result": {"old": 1, "new": 2}}

    def test_nested_path_creates_intermediate(self):
        data = {}
        asya_runtime._set_value_at_path(data, "/user/profile/name", "Alice")
        assert data == {"user": {"profile": {"name": "Alice"}}}

    def test_nested_path_merge_dict(self):
        data = {"user": {"profile": {"age": 30}}}
        asya_runtime._set_value_at_path(data, "/user/profile", {"name": "Alice"})
        assert data == {"user": {"profile": {"age": 30, "name": "Alice"}}}


class TestSerializeDeserialize:
    """Test serialization and deserialization helpers."""

    def test_deserialize_basic_types(self):
        assert asya_runtime._deserialize_input(42, int) == 42
        assert asya_runtime._deserialize_input("hello", str) == "hello"
        assert asya_runtime._deserialize_input([1, 2, 3], list) == [1, 2, 3]
        assert asya_runtime._deserialize_input({"a": 1}, dict) == {"a": 1}

    def test_deserialize_dataclass(self):
        result = asya_runtime._deserialize_input({"x": 10, "y": 20}, Point)
        assert isinstance(result, Point)
        assert result.x == 10
        assert result.y == 20

    def test_serialize_basic_types(self):
        assert asya_runtime._serialize_output(42) == 42
        assert asya_runtime._serialize_output("hello") == "hello"
        assert asya_runtime._serialize_output([1, 2, 3]) == [1, 2, 3]
        assert asya_runtime._serialize_output({"a": 1}) == {"a": 1}

    def test_serialize_none(self):
        assert asya_runtime._serialize_output(None) is None

    def test_serialize_dataclass(self):
        point = Point(x=10, y=20)
        result = asya_runtime._serialize_output(point)
        assert result == {"x": 10, "y": 20}

    @pytest.mark.skipif(not HAS_PYDANTIC, reason="Pydantic not installed")
    def test_deserialize_pydantic_v2(self):
        class User(BaseModel):
            name: str
            age: int

        result = asya_runtime._deserialize_input({"name": "Alice", "age": 30}, User)
        assert isinstance(result, User)
        assert result.name == "Alice"
        assert result.age == 30

    @pytest.mark.skipif(not HAS_PYDANTIC, reason="Pydantic not installed")
    def test_serialize_pydantic_v2(self):
        class User(BaseModel):
            name: str
            age: int

        user = User(name="Alice", age=30)
        result = asya_runtime._serialize_output(user)
        assert result == {"name": "Alice", "age": 30}


class TestExtractHandlerInputs:
    """Test _extract_handler_inputs function."""

    def test_extract_single_param(self):
        payload = {"value": 42}
        sig = asya_runtime.HandlerSignature(typed_simple)
        result = asya_runtime._extract_handler_inputs(payload, sig)
        assert result == {"value": 42}

    def test_extract_multi_params(self):
        payload = {"x": 10, "y": 20}
        sig = asya_runtime.HandlerSignature(typed_multi_params)
        result = asya_runtime._extract_handler_inputs(payload, sig)
        assert result == {"x": 10, "y": 20}

    def test_extract_with_optional_provided(self):
        payload = {"x": 10, "y": 20, "z": 5}
        sig = asya_runtime.HandlerSignature(typed_multi_params)
        result = asya_runtime._extract_handler_inputs(payload, sig)
        assert result == {"x": 10, "y": 20, "z": 5}

    def test_extract_missing_required_raises(self):
        payload = {"x": 10}
        sig = asya_runtime.HandlerSignature(typed_multi_params)
        with pytest.raises(ValueError, match="Missing required parameter 'y'"):
            asya_runtime._extract_handler_inputs(payload, sig)

    def test_extract_from_nested_path(self):
        payload = {"inputs": {"value": 42}}
        sig = asya_runtime.HandlerSignature(typed_simple)

        # Set ASYA_PARAMS_AT temporarily
        old_value = asya_runtime.ASYA_PARAMS_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = "/inputs"
            result = asya_runtime._extract_handler_inputs(payload, sig)
            assert result == {"value": 42}
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_value


class TestMergeHandlerOutput:
    """Test _merge_handler_output function."""

    def test_merge_dict_at_root(self):
        payload = {"a": 1}
        result = {"b": 2}
        merged = asya_runtime._merge_handler_output(payload, result)
        assert merged == {"a": 1, "b": 2}

    def test_merge_scalar_at_root(self):
        payload = {"a": 1}
        merged = asya_runtime._merge_handler_output(payload, 42)
        assert merged == 42

    def test_merge_dict_at_nested_path(self):
        payload = {"a": 1}
        result = {"c": 3}

        old_value = asya_runtime.ASYA_RESULT_AT
        try:
            asya_runtime.ASYA_RESULT_AT = "/result"
            merged = asya_runtime._merge_handler_output(payload, result)
            assert merged == {"a": 1, "result": {"c": 3}}
        finally:
            asya_runtime.ASYA_RESULT_AT = old_value

    def test_merge_none_returns_original(self):
        payload = {"a": 1}
        merged = asya_runtime._merge_handler_output(payload, None)
        assert merged == {"a": 1}

    def test_merge_preserves_original(self):
        payload = {"a": 1}
        result = {"b": 2}
        _ = asya_runtime._merge_handler_output(payload, result)
        assert payload == {"a": 1}


class TestCollectPayloadFrames:
    """Test _collect_payload_frames with typed handlers."""

    def test_legacy_handler_unchanged(self):
        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": ["actor2"]},
            "payload": {"value": 10},
        }

        frames = asya_runtime._collect_payload_frames(message, legacy_handler)
        assert len(frames) == 1
        assert frames[0]["payload"] == {"result": 20}
        assert frames[0]["route"]["prev"] == ["actor1"]
        assert frames[0]["route"]["curr"] == "actor2"

    def test_typed_single_param(self):
        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": ["actor2"]},
            "payload": {"value": 10},
        }

        frames = asya_runtime._collect_payload_frames(message, typed_simple)
        assert len(frames) == 1
        assert frames[0]["payload"] == {"value": 10, "doubled": 20}

    def test_typed_multi_params(self):
        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"x": 5, "y": 10},
        }

        frames = asya_runtime._collect_payload_frames(message, typed_multi_params)
        assert len(frames) == 1
        assert frames[0]["payload"] == {"x": 5, "y": 10, "sum": 25}

    def test_typed_scalar_return(self):
        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"value": 10},
        }

        frames = asya_runtime._collect_payload_frames(message, typed_scalar_return)
        assert len(frames) == 1
        assert frames[0]["payload"] == 20

    def test_typed_dataclass_input(self):
        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"point": {"x": 3, "y": 4}},
        }

        frames = asya_runtime._collect_payload_frames(message, typed_dataclass)
        assert len(frames) == 1
        assert frames[0]["payload"]["distance"] == 5.0

    def test_typed_dataclass_return(self):
        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"x": 10, "y": 20},
        }

        frames = asya_runtime._collect_payload_frames(message, typed_dataclass_return)
        assert len(frames) == 1
        assert frames[0]["payload"] == {"x": 10, "y": 20}

    def test_typed_none_return_empty_frames(self):
        def handler(value: int):
            return None

        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"value": 10},
        }

        frames = asya_runtime._collect_payload_frames(message, handler)
        assert len(frames) == 0

    def test_typed_missing_param_raises(self):
        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"x": 10},
        }

        with pytest.raises(ValueError, match="Missing required parameter 'y'"):
            asya_runtime._collect_payload_frames(message, typed_multi_params)

    def test_class_handler(self):
        processor = StatefulProcessor(multiplier=5)
        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"value": 10},
        }

        frames = asya_runtime._collect_payload_frames(message, processor.process)
        assert len(frames) == 1
        assert frames[0]["payload"] == {"value": 10, "result": 50}


class TestAsyncTypedHandlers:
    """Test async typed handlers."""

    def test_async_typed_handler(self):
        async def async_handler(value: int) -> dict:
            return {"doubled": value * 2}

        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"value": 10},
        }

        frames = asya_runtime._collect_payload_frames(message, async_handler)
        assert len(frames) == 1
        assert frames[0]["payload"] == {"value": 10, "doubled": 20}

    def test_async_generator_typed(self):
        async def async_gen(value: int):
            for i in range(3):
                yield {"index": i, "value": value * i}

        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"value": 5},
        }

        frames = asya_runtime._collect_payload_frames(message, async_gen)
        assert len(frames) == 3
        assert frames[0]["payload"]["index"] == 0
        assert frames[1]["payload"]["index"] == 1
        assert frames[2]["payload"]["index"] == 2


class TestBackwardCompatibility:
    """Test that legacy handlers remain unchanged."""

    def test_legacy_dict_handler(self):
        def handler(payload: dict) -> dict:
            return {"result": payload.get("x", 0) + 1}

        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"x": 10},
        }

        frames = asya_runtime._collect_payload_frames(message, handler)
        assert len(frames) == 1
        assert frames[0]["payload"] == {"result": 11}

    def test_legacy_dict_typed_annotation(self):
        def handler(payload: Dict[str, Any]) -> dict:
            return {"result": payload.get("x", 0) + 1}

        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"x": 10},
        }

        frames = asya_runtime._collect_payload_frames(message, handler)
        assert len(frames) == 1
        assert frames[0]["payload"] == {"result": 11}

    def test_legacy_no_annotation(self):
        def handler(payload):
            return {"result": payload.get("x", 0) + 1}

        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"x": 10},
        }

        frames = asya_runtime._collect_payload_frames(message, handler)
        assert len(frames) == 1
        assert frames[0]["payload"] == {"result": 11}
