"""Tests for the AsyaRef Click parameter type."""

from __future__ import annotations

from pathlib import Path

import click
import pytest
from asya_lab.cli_types import ASYA_REF, AsyaRef


class TestAsyaRefType:
    def test_kebab_case(self):
        ref = ASYA_REF.convert("order-processing", None, None)
        assert ref == AsyaRef(name="order-processing", function="order_processing")

    def test_snake_case(self):
        ref = ASYA_REF.convert("order_processing", None, None)
        assert ref == AsyaRef(name="order-processing", function="order_processing")

    def test_single_word(self):
        ref = ASYA_REF.convert("pipeline", None, None)
        assert ref == AsyaRef(name="pipeline", function="pipeline")

    def test_py_file(self):
        ref = ASYA_REF.convert("flows/order_processing.py", None, None)
        assert ref == AsyaRef(
            name="order-processing",
            function="order_processing",
            source=Path("flows/order_processing.py"),
        )

    def test_py_file_with_function(self):
        ref = ASYA_REF.convert("flows/main.py:order_processing", None, None)
        assert ref == AsyaRef(
            name="order-processing",
            function="order_processing",
            source=Path("flows/main.py"),
        )

    def test_py_file_with_dotted_function(self):
        ref = ASYA_REF.convert("flows/main.py:my_module.handler", None, None)
        assert ref == AsyaRef(
            name="my-module-handler",
            function="my_module.handler",
            source=Path("flows/main.py"),
        )

    def test_rejects_spaces(self):
        with pytest.raises(click.exceptions.BadParameter, match="invalid target"):
            ASYA_REF.convert("Order Processing", None, None)

    def test_rejects_uppercase(self):
        with pytest.raises(click.exceptions.BadParameter, match="invalid target"):
            ASYA_REF.convert("OrderProcessing", None, None)

    def test_rejects_colon_without_py(self):
        with pytest.raises(click.exceptions.BadParameter, match="expected .py file"):
            ASYA_REF.convert("module:function", None, None)

    def test_rejects_invalid_function_after_colon(self):
        with pytest.raises(click.exceptions.BadParameter, match="valid Python identifier"):
            ASYA_REF.convert("file.py:123bad", None, None)

    def test_passthrough(self):
        original = AsyaRef(name="test", function="test")
        result = ASYA_REF.convert(original, None, None)  # type: ignore[arg-type]
        assert result is original

    def test_name_attribute(self):
        assert ASYA_REF.name == "TARGET"

    def test_kebab_to_snake_roundtrip(self):
        ref = ASYA_REF.convert("my-flow-name", None, None)
        assert ref.name == "my-flow-name"
        assert ref.function == "my_flow_name"

    def test_snake_to_kebab_roundtrip(self):
        ref = ASYA_REF.convert("my_flow_name", None, None)
        assert ref.name == "my-flow-name"
        assert ref.function == "my_flow_name"
