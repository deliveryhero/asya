"""Tests for the ValueExtractor — compiler rule where-tree evaluation."""

from __future__ import annotations

import ast

import pytest
from asya_lab.compiler.extractor import ValueExtractor
from asya_lab.compiler.rules import CompilerRule, TreatAs, WhereNode


def _parse_call(source: str) -> ast.Call:
    """Parse a single expression and return the Call node."""
    tree = ast.parse(source, mode="eval")
    assert isinstance(tree.body, ast.Call)
    return tree.body


# -- simple kwarg extraction -----------------------------------------------


class TestSimpleKwargExtraction:
    def test_single_kwarg_from_rule(self):
        """asyncio.timeout(30) with param 'delay' -> spec.resiliency.timeout."""
        rule = CompilerRule(
            match="asyncio.timeout",
            treat_as=TreatAs.CONFIG,
            where=[
                WhereNode(
                    param="delay",
                    assign_to="spec.resiliency.timeout",
                ),
            ],
        )
        node = _parse_call("asyncio.timeout(delay=30)")
        extractor = ValueExtractor()
        result = extractor.extract(node, rule)
        assert result == {"spec.resiliency.timeout": 30}

    def test_multiple_kwargs(self):
        """stamina.retry(attempts=5, timeout=30.0) with two where nodes."""
        rule = CompilerRule(
            match="stamina.retry",
            treat_as=TreatAs.CONFIG,
            where=[
                WhereNode(param="attempts", assign_to="spec.resiliency.retry.maxAttempts"),
                WhereNode(param="timeout", assign_to="spec.resiliency.timeout"),
            ],
        )
        node = _parse_call("stamina.retry(attempts=5, timeout=30.0)")
        extractor = ValueExtractor()
        result = extractor.extract(node, rule)
        assert result == {
            "spec.resiliency.retry.maxAttempts": 5,
            "spec.resiliency.timeout": 30.0,
        }


# -- empty / missing args -------------------------------------------------


class TestNoArgs:
    def test_no_args_returns_empty(self):
        rule = CompilerRule(
            match="asyncio.timeout",
            treat_as=TreatAs.CONFIG,
            where=[
                WhereNode(param="delay", assign_to="spec.resiliency.timeout"),
            ],
        )
        node = _parse_call("asyncio.timeout()")
        extractor = ValueExtractor()
        result = extractor.extract(node, rule)
        assert result == {}

    def test_no_where_returns_empty(self):
        rule = CompilerRule(match="asyncio.timeout", treat_as=TreatAs.CONFIG)
        node = _parse_call("asyncio.timeout(delay=30)")
        extractor = ValueExtractor()
        result = extractor.extract(node, rule)
        assert result == {}


# -- positional arg binding ------------------------------------------------


class TestPositionalArgBinding:
    def test_positional_arg_via_inspect(self):
        """asyncio.timeout(30) — positional, resolved via inspect.signature."""
        rule = CompilerRule(
            match="asyncio.timeout",
            treat_as=TreatAs.CONFIG,
            where=[
                WhereNode(param="delay", assign_to="spec.resiliency.timeout"),
            ],
        )
        node = _parse_call("asyncio.timeout(30)")
        extractor = ValueExtractor()
        result = extractor.extract(node, rule)
        assert result == {"spec.resiliency.timeout": 30}

    def test_positional_fallback_index(self):
        """Unknown function falls back to index-based binding."""
        rule = CompilerRule(
            match="unknown_lib.unknown_func",
            treat_as=TreatAs.CONFIG,
            where=[
                WhereNode(param="0", assign_to="spec.foo"),
            ],
        )
        node = _parse_call("unknown_lib.unknown_func(42)")
        extractor = ValueExtractor()
        result = extractor.extract(node, rule)
        assert result == {"spec.foo": 42}


# -- _extract_value --------------------------------------------------------


class TestExtractValue:
    @pytest.fixture()
    def extractor(self):
        return ValueExtractor()

    def _val(self, source: str) -> object:
        tree = ast.parse(source, mode="eval")
        return ValueExtractor._extract_value(tree.body)

    def test_int(self):
        assert self._val("42") == 42

    def test_float(self):
        assert self._val("3.14") == 3.14

    def test_string(self):
        assert self._val("'hello'") == "hello"

    def test_bool_true(self):
        assert self._val("True") is True

    def test_bool_false(self):
        assert self._val("False") is False

    def test_name_as_string(self):
        """ast.Name should return the identifier as a string."""
        assert self._val("SomeException") == "SomeException"

    def test_tuple_of_names(self):
        """Tuple of names should be comma-joined."""
        assert self._val("(ValueError, TypeError)") == "ValueError, TypeError"

    def test_negative_int(self):
        assert self._val("-5") == -5

    def test_negative_float(self):
        assert self._val("-2.5") == -2.5

    def test_complex_expr_returns_none(self):
        """A function call is too complex to statically evaluate."""
        assert self._val("foo()") is None


# -- nested where tree (match + children) ----------------------------------


class TestNestedWhereTree:
    def test_nested_call_extraction(self):
        """Nested where: param points to a call, children extract from it."""
        rule = CompilerRule(
            match="tenacity.retry",
            treat_as=TreatAs.CONFIG,
            where=[
                WhereNode(
                    param="stop",
                    where=[
                        WhereNode(
                            param="max_attempt_number",
                            assign_to="spec.resiliency.retry.maxAttempts",
                        ),
                    ],
                ),
            ],
        )
        node = _parse_call("tenacity.retry(stop=stop_after_attempt(max_attempt_number=3))")
        extractor = ValueExtractor()
        result = extractor.extract(node, rule)
        assert result == {"spec.resiliency.retry.maxAttempts": 3}

    def test_match_node_recurses_children(self):
        """A match-only node (no param) should recurse children with same bindings."""
        rule = CompilerRule(
            match="stamina.retry",
            treat_as=TreatAs.CONFIG,
            where=[
                WhereNode(
                    match="stamina.retry",
                    where=[
                        WhereNode(
                            param="attempts",
                            assign_to="spec.resiliency.retry.maxAttempts",
                        ),
                    ],
                ),
            ],
        )
        node = _parse_call("stamina.retry(attempts=5)")
        extractor = ValueExtractor()
        result = extractor.extract(node, rule)
        assert result == {"spec.resiliency.retry.maxAttempts": 5}


# -- BinOp flattening -----------------------------------------------------


class TestBinOpFlattening:
    def test_flatten_pipe_operator(self):
        """a | b | c should flatten to three Call nodes."""
        tree = ast.parse("a() | b() | c()", mode="eval")
        calls = ValueExtractor._flatten_binop(tree.body)
        assert len(calls) == 3
        func_names = [ValueExtractor._resolve_func_name(c.func) for c in calls]
        assert func_names == ["a", "b", "c"]

    def test_binop_param_extraction(self):
        """Where node whose param points to a BinOp should extract from each call."""
        rule = CompilerRule(
            match="tenacity.retry",
            treat_as=TreatAs.CONFIG,
            where=[
                WhereNode(
                    param="wait",
                    where=[
                        WhereNode(
                            param="min",
                            assign_to="spec.resiliency.retry.waitMin",
                        ),
                        WhereNode(
                            param="max",
                            assign_to="spec.resiliency.retry.waitMax",
                        ),
                    ],
                ),
            ],
        )
        node = _parse_call("tenacity.retry(wait=wait_exponential(min=1) | wait_random(max=10))")
        extractor = ValueExtractor()
        result = extractor.extract(node, rule)
        assert result == {
            "spec.resiliency.retry.waitMin": 1,
            "spec.resiliency.retry.waitMax": 10,
        }


# -- _resolve_func_name ---------------------------------------------------


class TestResolveFuncName:
    def _parse_call(self, code: str) -> ast.Call:
        tree = ast.parse(code, mode="eval")
        assert isinstance(tree.body, ast.Call)
        return tree.body

    def test_simple_name(self):
        call = self._parse_call("foo()")
        assert ValueExtractor._resolve_func_name(call.func) == "foo"

    def test_dotted_name(self):
        call = self._parse_call("asyncio.timeout()")
        assert ValueExtractor._resolve_func_name(call.func) == "asyncio.timeout"

    def test_deep_dotted_name(self):
        call = self._parse_call("a.b.c.d()")
        assert ValueExtractor._resolve_func_name(call.func) == "a.b.c.d"

    def test_non_name_returns_none(self):
        call = self._parse_call("(lambda: 1)()")
        assert ValueExtractor._resolve_func_name(call.func) is None


# -- non-Call input --------------------------------------------------------


class TestNonCallInput:
    def test_non_call_returns_empty(self):
        """Passing a non-Call expression returns empty dict."""
        rule = CompilerRule(
            match="asyncio.timeout",
            treat_as=TreatAs.CONFIG,
            where=[
                WhereNode(param="delay", assign_to="spec.resiliency.timeout"),
            ],
        )
        tree = ast.parse("42", mode="eval")
        extractor = ValueExtractor()
        result = extractor.extract(tree.body, rule)
        assert result == {}
