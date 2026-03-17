"""Integration tests for with/async with compilation (parse → group → codegen)."""

import ast
import textwrap

import pytest
from asya_lab.flow.codegen import CodeGenerator
from asya_lab.flow.grouper import OperationGrouper
from asya_lab.flow.parser import FlowParser
from asya_lab.flow.rules import CompilerRule, CompilerRules


def _compile(source: str, rules: CompilerRules | None = None) -> str:
    """Full compilation pipeline: parse → group → codegen."""
    source = textwrap.dedent(source)
    parser = FlowParser(source, "test.py", rules=rules)
    flow_name, ops = parser.parse()
    grouper = OperationGrouper(flow_name, ops)
    routers = grouper.group()
    codegen = CodeGenerator(flow_name, routers, "test.py")
    return codegen.generate()


def _inline_rules(*names: str) -> CompilerRules:
    return CompilerRules({name: CompilerRule(treat_as="inline") for name in names})


class TestConfigWithCompilation:
    """Config context managers are stripped; generated code has no `with` statement."""

    def test_asyncio_timeout_generates_valid_python(self):
        source = """\
        @flow
        async def flow(p: dict) -> dict:
            async with asyncio.timeout(30):
                p = slow_handler(p)
            return p
        """
        code = _compile(source)
        try:
            ast.parse(code)
        except SyntaxError as e:
            pytest.fail(f"Generated code is not valid Python: {e}")

    def test_asyncio_timeout_no_with_in_output(self):
        source = """\
        @flow
        async def flow(p: dict) -> dict:
            async with asyncio.timeout(30):
                p = slow_handler(p)
            return p
        """
        code = _compile(source)
        assert "async with" not in code
        assert " with " not in code

    def test_asyncio_timeout_actor_present_in_output(self):
        source = """\
        @flow
        async def flow(p: dict) -> dict:
            async with asyncio.timeout(30):
                p = slow_handler(p)
            return p
        """
        code = _compile(source)
        assert "slow_handler" in code

    def test_config_multiple_actors_in_scope(self):
        source = """\
        @flow
        async def flow(p: dict) -> dict:
            async with asyncio.timeout(30):
                p = handler_a(p)
                p = handler_b(p)
            return p
        """
        code = _compile(source)
        ast.parse(code)
        assert "handler_a" in code
        assert "handler_b" in code
        assert "async with" not in code


class TestInlineWithCompilation:
    """Inline context managers appear as `with expr:` blocks in generated code."""

    def test_inline_with_generates_valid_python(self):
        source = """\
        @flow
        def flow(p: dict) -> dict:
            with custom_ctx():
                p = handler(p)
            return p
        """
        code = _compile(source, _inline_rules("custom_ctx"))
        try:
            ast.parse(code)
        except SyntaxError as e:
            pytest.fail(f"Generated code is not valid Python: {e}")

    def test_inline_with_produces_with_keyword_in_output(self):
        source = """\
        @flow
        def flow(p: dict) -> dict:
            with custom_ctx():
                p = handler(p)
            return p
        """
        code = _compile(source, _inline_rules("custom_ctx"))
        assert "with custom_ctx():" in code

    def test_inline_async_with_produces_async_with_in_output(self):
        source = """\
        @flow
        async def flow(p: dict) -> dict:
            async with custom_ctx():
                p = handler(p)
            return p
        """
        code = _compile(source, _inline_rules("custom_ctx"))
        assert "async with custom_ctx():" in code

    def test_inline_with_actor_present_in_output(self):
        source = """\
        @flow
        def flow(p: dict) -> dict:
            with custom_ctx():
                p = handler(p)
            return p
        """
        code = _compile(source, _inline_rules("custom_ctx"))
        assert "handler" in code

    def test_inline_with_multiple_actors_valid_python(self):
        source = """\
        @flow
        def flow(p: dict) -> dict:
            with custom_ctx():
                p = handler_a(p)
                p = handler_b(p)
            return p
        """
        code = _compile(source, _inline_rules("custom_ctx"))
        ast.parse(code)
        assert "handler_a" in code
        assert "handler_b" in code

    def test_inline_with_mutations_generates_valid_python(self):
        source = """\
        @flow
        def flow(p: dict) -> dict:
            with custom_ctx():
                p["status"] = "running"
                p = handler(p)
            return p
        """
        code = _compile(source, _inline_rules("custom_ctx"))
        ast.parse(code)

    def test_inline_nested_with_generates_valid_python(self):
        source = """\
        @flow
        def flow(p: dict) -> dict:
            with outer_ctx():
                with inner_ctx():
                    p = handler(p)
            return p
        """
        rules = _inline_rules("outer_ctx", "inner_ctx")
        code = _compile(source, rules)
        ast.parse(code)
        assert "outer_ctx()" in code
        assert "inner_ctx()" in code


class TestWithAfterOtherOps:
    """Context managers work correctly when combined with other flow constructs."""

    def test_with_after_actor_call(self):
        source = """\
        @flow
        async def flow(p: dict) -> dict:
            p = first_handler(p)
            async with asyncio.timeout(30):
                p = slow_handler(p)
            return p
        """
        code = _compile(source)
        ast.parse(code)
        assert "first_handler" in code
        assert "slow_handler" in code

    def test_with_before_mutation(self):
        source = """\
        @flow
        async def flow(p: dict) -> dict:
            async with asyncio.timeout(30):
                p = slow_handler(p)
            p["done"] = True
            return p
        """
        code = _compile(source)
        ast.parse(code)

    def test_inline_with_before_condition(self):
        source = """\
        @flow
        def flow(p: dict) -> dict:
            with custom_ctx():
                p = handler(p)
            if p["ok"]:
                p = success_handler(p)
            return p
        """
        code = _compile(source, _inline_rules("custom_ctx"))
        ast.parse(code)
