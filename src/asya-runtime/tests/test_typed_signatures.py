#!/usr/bin/env python3
"""Tests for typed handler signatures in asya_runtime.py."""

import dataclasses
import sys
from pathlib import Path

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


def dict_param_handler(data: dict) -> dict:
    """Handler with dict parameter - extracted by name like any other param."""
    return {"result": data.get("value", 0) * 2}


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

    def test_dict_param_not_legacy(self):
        """dict parameters are not special-cased - uniform extraction applies."""
        sig = asya_runtime.HandlerSignature(dict_param_handler)
        assert "data" in sig.params
        assert sig.params["data"]["required"] is True

    def test_typed_single_param(self):
        sig = asya_runtime.HandlerSignature(typed_simple)
        assert "value" in sig.params
        assert sig.params["value"]["required"] is True

    def test_typed_multi_params(self):
        sig = asya_runtime.HandlerSignature(typed_multi_params)
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


class TestJqPathParsing:
    """Test jq-style path parsing."""

    def test_parse_root(self):
        segments = asya_runtime._parse_jq_path(".")
        assert segments == []

    def test_parse_single_key(self):
        segments = asya_runtime._parse_jq_path(".key")
        assert segments == ["key"]

    def test_parse_nested_keys(self):
        segments = asya_runtime._parse_jq_path(".key.subkey")
        assert segments == ["key", "subkey"]

    def test_parse_array_index(self):
        segments = asya_runtime._parse_jq_path(".[0]")
        assert segments == [0]

    def test_parse_negative_index(self):
        segments = asya_runtime._parse_jq_path(".[-1]")
        assert segments == [-1]

    def test_parse_combined(self):
        segments = asya_runtime._parse_jq_path(".events[-1].data")
        assert segments == ["events", -1, "data"]

    def test_parse_key_with_array(self):
        segments = asya_runtime._parse_jq_path(".items[0].name")
        assert segments == ["items", 0, "name"]

    def test_parse_array_append(self):
        """Test parsing [+] array append syntax."""
        segments = asya_runtime._parse_jq_path(".[+]")
        assert segments == ["+"]

    def test_parse_key_with_array_append(self):
        """Test parsing key with [+] append."""
        segments = asya_runtime._parse_jq_path(".events[+]")
        assert segments == ["events", "+"]

    def test_parse_nested_with_array_append(self):
        """Test parsing nested path with [+] append."""
        segments = asya_runtime._parse_jq_path(".data.events[+]")
        assert segments == ["data", "events", "+"]

    def test_invalid_no_leading_dot(self):
        with pytest.raises(ValueError, match="must start with"):
            asya_runtime._parse_jq_path("key")

    def test_invalid_unclosed_bracket(self):
        with pytest.raises(ValueError, match="Unclosed bracket"):
            asya_runtime._parse_jq_path(".[0")

    def test_invalid_non_numeric_index(self):
        with pytest.raises(ValueError, match="Invalid array index"):
            asya_runtime._parse_jq_path(".[abc]")

    def test_invalid_negative_append(self):
        """Test that .[-] raises ValueError."""
        with pytest.raises(ValueError, match="not supported"):
            asya_runtime._parse_jq_path(".[-]")


class TestNavigatePath:
    """Test _navigate_path with parsed segments."""

    def test_navigate_root(self):
        data = {"a": 1, "b": 2}
        result = asya_runtime._navigate_path(data, [])
        assert result == data

    def test_navigate_single_key(self):
        data = {"a": 1, "b": 2}
        result = asya_runtime._navigate_path(data, ["a"])
        assert result == 1

    def test_navigate_nested_keys(self):
        data = {"user": {"profile": {"name": "Alice"}}}
        result = asya_runtime._navigate_path(data, ["user", "profile", "name"])
        assert result == "Alice"

    def test_navigate_array_index(self):
        data = {"items": [10, 20, 30]}
        result = asya_runtime._navigate_path(data, ["items", 1])
        assert result == 20

    def test_navigate_negative_index(self):
        data = {"items": [10, 20, 30]}
        result = asya_runtime._navigate_path(data, ["items", -1])
        assert result == 30

    def test_navigate_combined(self):
        data = {"events": [{"data": "first"}, {"data": "last"}]}
        result = asya_runtime._navigate_path(data, ["events", -1, "data"])
        assert result == "last"

    def test_missing_key_raises(self):
        data = {"a": 1}
        with pytest.raises(KeyError, match="Missing key"):
            asya_runtime._navigate_path(data, ["b"])

    def test_invalid_index_raises(self):
        data = {"items": [1, 2]}
        with pytest.raises(IndexError, match="out of range"):
            asya_runtime._navigate_path(data, ["items", 10])

    def test_index_non_list_raises(self):
        data = {"value": 42}
        with pytest.raises(TypeError, match="Cannot index non-list"):
            asya_runtime._navigate_path(data, ["value", 0])

    def test_key_non_dict_raises(self):
        data = {"value": 42}
        with pytest.raises(KeyError, match="Cannot access key .* in non-dict"):
            asya_runtime._navigate_path(data, ["value", "subkey"])


class TestDeepMerge:
    """Test _deep_merge recursive dict merging."""

    def test_shallow_keys(self):
        target = {"a": 1, "b": 2}
        source = {"c": 3}
        asya_runtime._deep_merge(target, source)
        assert target == {"a": 1, "b": 2, "c": 3}

    def test_overwrite_scalar(self):
        target = {"a": 1, "b": 2}
        source = {"b": 99}
        asya_runtime._deep_merge(target, source)
        assert target == {"a": 1, "b": 99}

    def test_nested_dict_merge(self):
        target = {"nested": {"a": 1, "b": 2}}
        source = {"nested": {"a": 99, "c": 3}}
        asya_runtime._deep_merge(target, source)
        assert target == {"nested": {"a": 99, "b": 2, "c": 3}}

    def test_list_overwrite(self):
        target = {"items": [1, 2, 3]}
        source = {"items": [4, 5]}
        asya_runtime._deep_merge(target, source)
        assert target == {"items": [4, 5]}

    def test_deep_nested(self):
        target = {"a": {"b": {"c": 1, "d": 2}}}
        source = {"a": {"b": {"c": 99, "e": 3}}}
        asya_runtime._deep_merge(target, source)
        assert target == {"a": {"b": {"c": 99, "d": 2, "e": 3}}}


class TestSetValueAtPath:
    """Test _set_value_at_path with jq paths and merge strategies."""

    def test_root_shallow_dict(self):
        data = {"a": 1}
        asya_runtime._set_value_at_path(data, ".", {"b": 2}, "shallow")
        assert data == {"a": 1, "b": 2}

    def test_root_deep_dict(self):
        data = {"a": 1, "nested": {"x": 10}}
        asya_runtime._set_value_at_path(data, ".", {"b": 2, "nested": {"y": 20}}, "deep")
        assert data == {"a": 1, "b": 2, "nested": {"x": 10, "y": 20}}

    def test_root_scalar_replaces(self):
        data = {"a": 1}
        result = asya_runtime._set_value_at_path(data, ".", 42, "shallow")
        assert result == 42

    def test_single_key_scalar(self):
        data = {}
        asya_runtime._set_value_at_path(data, ".result", 42, "shallow")
        assert data == {"result": 42}

    def test_single_key_dict_shallow(self):
        data = {"result": {"old": 1}}
        asya_runtime._set_value_at_path(data, ".result", {"new": 2}, "shallow")
        assert data == {"result": {"old": 1, "new": 2}}

    def test_single_key_dict_deep(self):
        data = {"result": {"nested": {"a": 1}}}
        asya_runtime._set_value_at_path(data, ".result", {"nested": {"b": 2}, "new": 3}, "deep")
        assert data == {"result": {"nested": {"a": 1, "b": 2}, "new": 3}}

    def test_nested_path_creates_intermediate(self):
        data = {}
        asya_runtime._set_value_at_path(data, ".user.profile.name", "Alice", "shallow")
        assert data == {"user": {"profile": {"name": "Alice"}}}

    def test_nested_path_merge_shallow(self):
        data = {"user": {"profile": {"age": 30, "nested": {"a": 1}}}}
        asya_runtime._set_value_at_path(data, ".user.profile", {"name": "Alice", "nested": {"b": 2}}, "shallow")
        assert data == {"user": {"profile": {"age": 30, "name": "Alice", "nested": {"b": 2}}}}

    def test_nested_path_merge_deep(self):
        data = {"user": {"profile": {"age": 30, "nested": {"a": 1}}}}
        asya_runtime._set_value_at_path(data, ".user.profile", {"name": "Alice", "nested": {"b": 2}}, "deep")
        assert data == {"user": {"profile": {"age": 30, "name": "Alice", "nested": {"a": 1, "b": 2}}}}

    def test_array_append_to_existing_list(self):
        """Test [+] appends to existing list."""
        data = {"events": [{"id": 1}, {"id": 2}]}
        asya_runtime._set_value_at_path(data, ".events[+]", {"id": 3}, "shallow")
        assert data == {"events": [{"id": 1}, {"id": 2}, {"id": 3}]}

    def test_array_append_creates_list_if_missing(self):
        """Test [+] creates list if key doesn't exist."""
        data = {}
        asya_runtime._set_value_at_path(data, ".events[+]", {"id": 1}, "shallow")
        assert data == {"events": [{"id": 1}]}

    def test_array_append_scalar_value(self):
        """Test [+] appends scalar values."""
        data = {"items": [1, 2]}
        asya_runtime._set_value_at_path(data, ".items[+]", 3, "shallow")
        assert data == {"items": [1, 2, 3]}

    def test_array_append_nested_path(self):
        """Test [+] with nested path."""
        data = {"user": {"events": [1, 2]}}
        asya_runtime._set_value_at_path(data, ".user.events[+]", 3, "shallow")
        assert data == {"user": {"events": [1, 2, 3]}}

    def test_array_append_errors_if_target_not_list(self):
        """Test [+] raises error if target is not a list."""
        data = {"items": "not a list"}
        with pytest.raises(ValueError, match="not list"):
            asya_runtime._set_value_at_path(data, ".items[+]", 42, "shallow")

    def test_array_append_creates_intermediate_dicts(self):
        """Test [+] creates intermediate dicts in path."""
        data = {}
        asya_runtime._set_value_at_path(data, ".data.events[+]", {"id": 1}, "shallow")
        assert data == {"data": {"events": [{"id": 1}]}}

    def test_array_append_root_level_invalid(self):
        """Test .[+] at root is invalid."""
        data = {}
        with pytest.raises(ValueError, match="root must be a dict"):
            asya_runtime._set_value_at_path(data, ".[+]", {"id": 1}, "shallow")


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

    def test_extract_single_param_root(self):
        payload = {"value": 42}
        sig = asya_runtime.HandlerSignature(typed_simple)

        old_value = asya_runtime.ASYA_PARAMS_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = "."
            result = asya_runtime._extract_handler_inputs(payload, sig)
            assert result == {"value": 42}
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_value

    def test_extract_multi_params(self):
        payload = {"x": 10, "y": 20}
        sig = asya_runtime.HandlerSignature(typed_multi_params)

        old_value = asya_runtime.ASYA_PARAMS_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = "."
            result = asya_runtime._extract_handler_inputs(payload, sig)
            assert result == {"x": 10, "y": 20}
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_value

    def test_extract_with_optional_provided(self):
        payload = {"x": 10, "y": 20, "z": 5}
        sig = asya_runtime.HandlerSignature(typed_multi_params)

        old_value = asya_runtime.ASYA_PARAMS_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = "."
            result = asya_runtime._extract_handler_inputs(payload, sig)
            assert result == {"x": 10, "y": 20, "z": 5}
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_value

    def test_extract_missing_required_raises(self):
        payload = {"x": 10}
        sig = asya_runtime.HandlerSignature(typed_multi_params)

        old_value = asya_runtime.ASYA_PARAMS_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = "."
            with pytest.raises(ValueError, match="Missing required parameter 'y'"):
                asya_runtime._extract_handler_inputs(payload, sig)
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_value

    def test_extract_from_nested_path(self):
        payload = {"inputs": {"value": 42}}
        sig = asya_runtime.HandlerSignature(typed_simple)

        old_value = asya_runtime.ASYA_PARAMS_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = ".inputs"
            result = asya_runtime._extract_handler_inputs(payload, sig)
            assert result == {"value": 42}
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_value

    def test_extract_from_array_index(self):
        payload = {"events": [{"value": 10}, {"value": 42}]}
        sig = asya_runtime.HandlerSignature(typed_simple)

        old_value = asya_runtime.ASYA_PARAMS_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = ".events[-1]"
            result = asya_runtime._extract_handler_inputs(payload, sig)
            assert result == {"value": 42}
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_value

    def test_extract_dict_parameter_by_name(self):
        """dict parameter is extracted by name, not passed as entire payload."""
        payload = {"data": {"value": 10}}
        sig = asya_runtime.HandlerSignature(dict_param_handler)

        old_value = asya_runtime.ASYA_PARAMS_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = "."
            result = asya_runtime._extract_handler_inputs(payload, sig)
            assert result == {"data": {"value": 10}}
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_value


class TestMergeHandlerOutput:
    """Test _merge_handler_output function."""

    def test_merge_dict_at_root_shallow(self):
        payload = {"a": 1}
        result = {"b": 2}

        old_at = asya_runtime.ASYA_RESULT_AT
        old_merge = asya_runtime.ASYA_RESULT_MERGE
        try:
            asya_runtime.ASYA_RESULT_AT = "."
            asya_runtime.ASYA_RESULT_MERGE = "shallow"
            merged = asya_runtime._merge_handler_output(payload, result)
            assert merged == {"a": 1, "b": 2}
        finally:
            asya_runtime.ASYA_RESULT_AT = old_at
            asya_runtime.ASYA_RESULT_MERGE = old_merge

    def test_merge_dict_at_root_deep(self):
        payload = {"a": 1, "nested": {"x": 10}}
        result = {"b": 2, "nested": {"y": 20}}

        old_at = asya_runtime.ASYA_RESULT_AT
        old_merge = asya_runtime.ASYA_RESULT_MERGE
        try:
            asya_runtime.ASYA_RESULT_AT = "."
            asya_runtime.ASYA_RESULT_MERGE = "deep"
            merged = asya_runtime._merge_handler_output(payload, result)
            assert merged == {"a": 1, "b": 2, "nested": {"x": 10, "y": 20}}
        finally:
            asya_runtime.ASYA_RESULT_AT = old_at
            asya_runtime.ASYA_RESULT_MERGE = old_merge

    def test_merge_scalar_at_root(self):
        payload = {"a": 1}

        old_at = asya_runtime.ASYA_RESULT_AT
        try:
            asya_runtime.ASYA_RESULT_AT = "."
            merged = asya_runtime._merge_handler_output(payload, 42)
            assert merged == 42
        finally:
            asya_runtime.ASYA_RESULT_AT = old_at

    def test_merge_dict_at_nested_path(self):
        payload = {"a": 1}
        result = {"c": 3}

        old_at = asya_runtime.ASYA_RESULT_AT
        try:
            asya_runtime.ASYA_RESULT_AT = ".result"
            merged = asya_runtime._merge_handler_output(payload, result)
            assert merged == {"a": 1, "result": {"c": 3}}
        finally:
            asya_runtime.ASYA_RESULT_AT = old_at

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
    """Test _collect_payload_frames with uniform extraction."""

    def test_dict_param_uniform_extraction(self):
        """dict parameter handler uses uniform extraction - extracts by param name."""
        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": ["actor2"]},
            "payload": {"data": {"value": 10}},
        }

        old_at = asya_runtime.ASYA_PARAMS_AT
        old_result_at = asya_runtime.ASYA_RESULT_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = "."
            asya_runtime.ASYA_RESULT_AT = "."
            frames = asya_runtime._collect_payload_frames(message, dict_param_handler)
            assert len(frames) == 1
            # Result merged at root
            assert frames[0]["payload"] == {"data": {"value": 10}, "result": 20}
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_at
            asya_runtime.ASYA_RESULT_AT = old_result_at

    def test_typed_single_param(self):
        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": ["actor2"]},
            "payload": {"value": 10},
        }

        old_at = asya_runtime.ASYA_PARAMS_AT
        old_result_at = asya_runtime.ASYA_RESULT_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = "."
            asya_runtime.ASYA_RESULT_AT = "."
            frames = asya_runtime._collect_payload_frames(message, typed_simple)
            assert len(frames) == 1
            assert frames[0]["payload"] == {"value": 10, "doubled": 20}
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_at
            asya_runtime.ASYA_RESULT_AT = old_result_at

    def test_typed_multi_params(self):
        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"x": 5, "y": 10},
        }

        old_at = asya_runtime.ASYA_PARAMS_AT
        old_result_at = asya_runtime.ASYA_RESULT_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = "."
            asya_runtime.ASYA_RESULT_AT = "."
            frames = asya_runtime._collect_payload_frames(message, typed_multi_params)
            assert len(frames) == 1
            assert frames[0]["payload"] == {"x": 5, "y": 10, "sum": 25}
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_at
            asya_runtime.ASYA_RESULT_AT = old_result_at

    def test_typed_scalar_return(self):
        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"value": 10},
        }

        old_at = asya_runtime.ASYA_PARAMS_AT
        old_result_at = asya_runtime.ASYA_RESULT_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = "."
            asya_runtime.ASYA_RESULT_AT = "."
            frames = asya_runtime._collect_payload_frames(message, typed_scalar_return)
            assert len(frames) == 1
            # Scalar at root replaces entire payload
            assert frames[0]["payload"] == 20
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_at
            asya_runtime.ASYA_RESULT_AT = old_result_at

    def test_typed_dataclass_input(self):
        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"point": {"x": 3, "y": 4}},
        }

        old_at = asya_runtime.ASYA_PARAMS_AT
        old_result_at = asya_runtime.ASYA_RESULT_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = "."
            asya_runtime.ASYA_RESULT_AT = "."
            frames = asya_runtime._collect_payload_frames(message, typed_dataclass)
            assert len(frames) == 1
            assert frames[0]["payload"]["distance"] == 5.0
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_at
            asya_runtime.ASYA_RESULT_AT = old_result_at

    def test_typed_dataclass_return(self):
        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"x": 10, "y": 20},
        }

        old_at = asya_runtime.ASYA_PARAMS_AT
        old_result_at = asya_runtime.ASYA_RESULT_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = "."
            asya_runtime.ASYA_RESULT_AT = "."
            frames = asya_runtime._collect_payload_frames(message, typed_dataclass_return)
            assert len(frames) == 1
            assert frames[0]["payload"] == {"x": 10, "y": 20}
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_at
            asya_runtime.ASYA_RESULT_AT = old_result_at

    def test_typed_none_return_empty_frames(self):
        def handler(value: int):
            return None

        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"value": 10},
        }

        old_at = asya_runtime.ASYA_PARAMS_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = "."
            frames = asya_runtime._collect_payload_frames(message, handler)
            assert len(frames) == 0
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_at

    def test_typed_missing_param_raises(self):
        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"x": 10},
        }

        old_at = asya_runtime.ASYA_PARAMS_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = "."
            with pytest.raises(ValueError, match="Missing required parameter 'y'"):
                asya_runtime._collect_payload_frames(message, typed_multi_params)
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_at

    def test_class_handler(self):
        processor = StatefulProcessor(multiplier=5)
        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"value": 10},
        }

        old_at = asya_runtime.ASYA_PARAMS_AT
        old_result_at = asya_runtime.ASYA_RESULT_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = "."
            asya_runtime.ASYA_RESULT_AT = "."
            frames = asya_runtime._collect_payload_frames(message, processor.process)
            assert len(frames) == 1
            assert frames[0]["payload"] == {"value": 10, "result": 50}
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_at
            asya_runtime.ASYA_RESULT_AT = old_result_at


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

        old_at = asya_runtime.ASYA_PARAMS_AT
        old_result_at = asya_runtime.ASYA_RESULT_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = "."
            asya_runtime.ASYA_RESULT_AT = "."
            frames = asya_runtime._collect_payload_frames(message, async_handler)
            assert len(frames) == 1
            assert frames[0]["payload"] == {"value": 10, "doubled": 20}
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_at
            asya_runtime.ASYA_RESULT_AT = old_result_at

    def test_async_generator_typed(self):
        async def async_gen(value: int):
            for i in range(3):
                yield {"index": i, "value": value * i}

        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"value": 5},
        }

        old_at = asya_runtime.ASYA_PARAMS_AT
        old_result_at = asya_runtime.ASYA_RESULT_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = "."
            asya_runtime.ASYA_RESULT_AT = "."
            frames = asya_runtime._collect_payload_frames(message, async_gen)
            assert len(frames) == 3
            assert frames[0]["payload"]["index"] == 0
            assert frames[1]["payload"]["index"] == 1
            assert frames[2]["payload"]["index"] == 2
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_at
            asya_runtime.ASYA_RESULT_AT = old_result_at


class TestKwargsSupport:
    """Test **kwargs parameter support."""

    def test_kwargs_only_handler(self):
        """Handler with only **kwargs receives all subtree keys."""

        def kwargs_handler(**kwargs):
            return {"received": kwargs}

        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"text": "hello", "lang": "en", "debug": True},
        }

        old_at = asya_runtime.ASYA_PARAMS_AT
        old_result_at = asya_runtime.ASYA_RESULT_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = "."
            asya_runtime.ASYA_RESULT_AT = "."
            frames = asya_runtime._collect_payload_frames(message, kwargs_handler)
            assert len(frames) == 1
            assert frames[0]["payload"]["received"] == {"text": "hello", "lang": "en", "debug": True}
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_at
            asya_runtime.ASYA_RESULT_AT = old_result_at

    def test_mixed_named_and_kwargs(self):
        """Handler with named params + **kwargs - named extracted first, rest to kwargs."""

        def mixed_handler(text: str, **extra):
            return {"text": text, "extra": extra}

        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"text": "hello", "lang": "en", "debug": True},
        }

        old_at = asya_runtime.ASYA_PARAMS_AT
        old_result_at = asya_runtime.ASYA_RESULT_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = "."
            asya_runtime.ASYA_RESULT_AT = "."
            frames = asya_runtime._collect_payload_frames(message, mixed_handler)
            assert len(frames) == 1
            assert frames[0]["payload"]["text"] == "hello"
            assert frames[0]["payload"]["extra"] == {"lang": "en", "debug": True}
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_at
            asya_runtime.ASYA_RESULT_AT = old_result_at

    def test_kwargs_no_extra_keys(self):
        """Handler with **kwargs but no extra keys in subtree."""

        def mixed_handler(text: str, **extra):
            return {"text": text, "extra": extra}

        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"text": "hello"},
        }

        old_at = asya_runtime.ASYA_PARAMS_AT
        old_result_at = asya_runtime.ASYA_RESULT_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = "."
            asya_runtime.ASYA_RESULT_AT = "."
            frames = asya_runtime._collect_payload_frames(message, mixed_handler)
            assert len(frames) == 1
            assert frames[0]["payload"]["text"] == "hello"
            assert frames[0]["payload"]["extra"] == {}
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_at
            asya_runtime.ASYA_RESULT_AT = old_result_at

    def test_kwargs_raw_values_no_deserialization(self):
        """Values passed to **kwargs are raw JSON - no type deserialization."""

        def kwargs_handler(**kwargs):
            return {"received": kwargs, "types": {k: type(v).__name__ for k, v in kwargs.items()}}

        message = {
            "id": "msg-1",
            "route": {"prev": [], "curr": "actor1", "next": []},
            "payload": {"num": 42, "flag": True, "nested": {"a": 1}},
        }

        old_at = asya_runtime.ASYA_PARAMS_AT
        old_result_at = asya_runtime.ASYA_RESULT_AT
        try:
            asya_runtime.ASYA_PARAMS_AT = "."
            asya_runtime.ASYA_RESULT_AT = "."
            frames = asya_runtime._collect_payload_frames(message, kwargs_handler)
            assert len(frames) == 1
            assert frames[0]["payload"]["received"]["num"] == 42
            assert frames[0]["payload"]["received"]["flag"] is True
            assert frames[0]["payload"]["received"]["nested"] == {"a": 1}
            assert frames[0]["payload"]["types"]["num"] == "int"
            assert frames[0]["payload"]["types"]["flag"] == "bool"
            assert frames[0]["payload"]["types"]["nested"] == "dict"
        finally:
            asya_runtime.ASYA_PARAMS_AT = old_at
            asya_runtime.ASYA_RESULT_AT = old_result_at


class TestArgsRejection:
    """Test that *args parameters are rejected at handler load time."""

    def test_args_only_rejected(self):
        """Handler with only *args is rejected at load time."""

        def args_handler(*args):
            return {"args": list(args)}

        with pytest.raises(RuntimeError, match="declares \\*args which is not supported"):
            asya_runtime.HandlerSignature(args_handler)

    def test_args_mixed_with_named_rejected(self):
        """Handler with named params + *args is rejected at load time."""

        def mixed_handler(x: int, *args):
            return {"x": x, "args": list(args)}

        with pytest.raises(RuntimeError, match="declares \\*args which is not supported"):
            asya_runtime.HandlerSignature(mixed_handler)

    def test_args_with_kwargs_rejected(self):
        """Handler with *args and **kwargs is rejected at load time."""

        def full_handler(x: int, *args, **kwargs):
            return {"x": x, "args": list(args), "kwargs": kwargs}

        with pytest.raises(RuntimeError, match="declares \\*args which is not supported"):
            asya_runtime.HandlerSignature(full_handler)


class TestArrayAppendResultMerge:
    """Test [+] array append with _merge_handler_output."""

    def test_append_to_existing_list_at_result_path(self):
        """Test merging with [+] appends to existing list."""
        payload = {"a": 1, "events": [1, 2]}
        result = {"event_id": 3}

        old_at = asya_runtime.ASYA_RESULT_AT
        try:
            asya_runtime.ASYA_RESULT_AT = ".events[+]"
            merged = asya_runtime._merge_handler_output(payload, result)
            assert merged == {"a": 1, "events": [1, 2, {"event_id": 3}]}
        finally:
            asya_runtime.ASYA_RESULT_AT = old_at

    def test_append_creates_list_at_result_path(self):
        """Test [+] creates list if missing."""
        payload = {"a": 1}
        result = {"event_id": 1}

        old_at = asya_runtime.ASYA_RESULT_AT
        try:
            asya_runtime.ASYA_RESULT_AT = ".events[+]"
            merged = asya_runtime._merge_handler_output(payload, result)
            assert merged == {"a": 1, "events": [{"event_id": 1}]}
        finally:
            asya_runtime.ASYA_RESULT_AT = old_at

    def test_append_scalar_value(self):
        """Test appending scalar values."""
        payload = {"nums": [1, 2]}
        result = 3

        old_at = asya_runtime.ASYA_RESULT_AT
        try:
            asya_runtime.ASYA_RESULT_AT = ".nums[+]"
            merged = asya_runtime._merge_handler_output(payload, result)
            assert merged == {"nums": [1, 2, 3]}
        finally:
            asya_runtime.ASYA_RESULT_AT = old_at

    def test_append_with_nested_path(self):
        """Test [+] with nested path."""
        payload = {"user": {"events": [1]}}
        result = 2

        old_at = asya_runtime.ASYA_RESULT_AT
        try:
            asya_runtime.ASYA_RESULT_AT = ".user.events[+]"
            merged = asya_runtime._merge_handler_output(payload, result)
            assert merged == {"user": {"events": [1, 2]}}
        finally:
            asya_runtime.ASYA_RESULT_AT = old_at

    def test_append_errors_if_target_not_list(self):
        """Test [+] raises error if target is not a list."""
        payload = {"events": "not a list"}
        result = {"id": 1}

        old_at = asya_runtime.ASYA_RESULT_AT
        try:
            asya_runtime.ASYA_RESULT_AT = ".events[+]"
            with pytest.raises(ValueError, match="not list"):
                asya_runtime._merge_handler_output(payload, result)
        finally:
            asya_runtime.ASYA_RESULT_AT = old_at


class TestParamsAtValidation:
    """Test ASYA_PARAMS_AT validation at startup."""

    def test_params_at_with_append_raises_at_parse(self):
        """Test that [+] in ASYA_PARAMS_AT path raises error."""
        path_with_append = ".inputs[+]"
        segments = asya_runtime._parse_jq_path(path_with_append)
        assert "+" in segments
