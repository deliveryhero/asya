"""Unit tests for with/async with statement parsing in the flow parser."""

import textwrap

import pytest
from asya_lab.flow.errors import FlowCompileError
from asya_lab.flow.ir import ActorCall, Mutation, Return, WithBlock
from asya_lab.flow.parser import FlowParser
from asya_lab.flow.rules import CompilerRule, CompilerRules


def _make_rules(**overrides: CompilerRule) -> CompilerRules:
    """Build a CompilerRules with named rules added/overriding defaults."""
    base = {
        "asyncio.timeout": CompilerRule(
            treat_as="config",
            extract={"delay": "ASYA_RESILIENCY_ACTOR_TIMEOUT"},
        ),
    }
    base.update(overrides)
    return CompilerRules(base)


def _inline_rules(*names: str) -> CompilerRules:
    """Build a CompilerRules where all given names are treat-as: inline."""
    return _make_rules(**{name: CompilerRule(treat_as="inline") for name in names})


class TestWithParserRejectsUnknown:
    """Unknown context managers (no rule) must raise FlowCompileError."""

    def test_unknown_context_manager_raises_error(self):
        source = textwrap.dedent("""
            @flow
            def flow(p: dict) -> dict:
                with unknown_ctx():
                    p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py", rules=CompilerRules.empty())
        with pytest.raises(FlowCompileError, match="unknown_ctx"):
            parser.parse()

    def test_async_with_unknown_raises_error(self):
        source = textwrap.dedent("""
            @flow
            async def flow(p: dict) -> dict:
                async with unknown_ctx():
                    p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py", rules=CompilerRules.empty())
        with pytest.raises(FlowCompileError, match="unknown_ctx"):
            parser.parse()

    def test_default_rules_reject_unknown_context_manager(self):
        source = textwrap.dedent("""
            @flow
            def flow(p: dict) -> dict:
                with totally_unknown():
                    p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="totally_unknown"):
            parser.parse()


class TestConfigRuleWith:
    """`treat-as: config` strips the context manager, body ops pass through."""

    def test_asyncio_timeout_body_ops_returned(self):
        source = textwrap.dedent("""
            @flow
            async def flow(p: dict) -> dict:
                async with asyncio.timeout(30):
                    p = slow_handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 2
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "slow_handler"
        assert isinstance(ops[1], Return)

    def test_config_with_multiple_body_actors(self):
        source = textwrap.dedent("""
            @flow
            async def flow(p: dict) -> dict:
                async with asyncio.timeout(30):
                    p = slow_handler(p)
                    p = another_handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 3
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "slow_handler"
        assert isinstance(ops[1], ActorCall)
        assert ops[1].name == "another_handler"
        assert isinstance(ops[2], Return)

    def test_config_with_body_mutations(self):
        source = textwrap.dedent("""
            @flow
            async def flow(p: dict) -> dict:
                async with asyncio.timeout(30):
                    p["status"] = "running"
                    p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 3
        assert isinstance(ops[0], Mutation)
        assert isinstance(ops[1], ActorCall)
        assert isinstance(ops[2], Return)

    def test_config_extracts_args_into_metadata(self):
        source = textwrap.dedent("""
            @flow
            async def flow(p: dict) -> dict:
                async with asyncio.timeout(30):
                    p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        parser.parse()

        assert len(parser.extracted_configs) == 1
        config = parser.extracted_configs[0]
        assert config["symbol"] == "asyncio.timeout"
        assert config["args"]["delay"] == "30"

    def test_sync_with_config_rule(self):
        """Sync `with` also works when rules match."""
        rules = _make_rules(
            my_timeout=CompilerRule(
                treat_as="config",
                extract={"seconds": "ASYA_RESILIENCY_ACTOR_TIMEOUT"},
            )
        )
        source = textwrap.dedent("""
            @flow
            def flow(p: dict) -> dict:
                with my_timeout(60):
                    p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py", rules=rules)
        _, ops = parser.parse()

        assert len(ops) == 2
        assert isinstance(ops[0], ActorCall)
        assert isinstance(ops[1], Return)


class TestInlineRuleWith:
    """`treat-as: inline` wraps body ops in a WithBlock IR node."""

    def test_inline_produces_with_block(self):
        source = textwrap.dedent("""
            @flow
            def flow(p: dict) -> dict:
                with custom_ctx():
                    p = handler(p)
                return p
        """)
        rules = _inline_rules("custom_ctx")
        parser = FlowParser(source, "test.py", rules=rules)
        _, ops = parser.parse()

        assert len(ops) == 2
        assert isinstance(ops[0], WithBlock)
        wb = ops[0]
        assert wb.expr == "custom_ctx()"
        assert wb.is_async is False
        assert len(wb.body) == 1
        assert isinstance(wb.body[0], ActorCall)
        assert wb.body[0].name == "handler"

    def test_async_with_inline_produces_async_with_block(self):
        source = textwrap.dedent("""
            @flow
            async def flow(p: dict) -> dict:
                async with custom_ctx():
                    p = handler(p)
                return p
        """)
        rules = _inline_rules("custom_ctx")
        parser = FlowParser(source, "test.py", rules=rules)
        _, ops = parser.parse()

        assert len(ops) == 2
        assert isinstance(ops[0], WithBlock)
        wb = ops[0]
        assert wb.is_async is True
        assert wb.expr == "custom_ctx()"

    def test_inline_with_mutations_in_body(self):
        source = textwrap.dedent("""
            @flow
            def flow(p: dict) -> dict:
                with custom_ctx():
                    p["status"] = "running"
                    p = handler(p)
                return p
        """)
        rules = _inline_rules("custom_ctx")
        parser = FlowParser(source, "test.py", rules=rules)
        _, ops = parser.parse()

        assert len(ops) == 2
        assert isinstance(ops[0], WithBlock)
        wb = ops[0]
        assert len(wb.body) == 2
        assert isinstance(wb.body[0], Mutation)
        assert isinstance(wb.body[1], ActorCall)

    def test_inline_with_block_preserves_lineno(self):
        source = textwrap.dedent("""
            @flow
            def flow(p: dict) -> dict:
                with custom_ctx():
                    p = handler(p)
                return p
        """)
        rules = _inline_rules("custom_ctx")
        parser = FlowParser(source, "test.py", rules=rules)
        _, ops = parser.parse()

        assert isinstance(ops[0], WithBlock)
        assert ops[0].lineno == 4

    def test_inline_with_as_binding_includes_alias_in_expr(self):
        """Optional `as name` binding preserved in expr string."""
        source = textwrap.dedent("""
            @flow
            def flow(p: dict) -> dict:
                with custom_ctx() as cm:
                    p = handler(p)
                return p
        """)
        rules = _inline_rules("custom_ctx")
        parser = FlowParser(source, "test.py", rules=rules)
        _, ops = parser.parse()

        assert isinstance(ops[0], WithBlock)
        assert "custom_ctx()" in ops[0].expr
        assert "as cm" in ops[0].expr


class TestNestedWith:
    """Nested context managers are supported."""

    def test_nested_config_managers_both_stripped(self):
        """Outer config + inner config → all stripped, body ops returned."""
        rules = _make_rules(
            outer_timeout=CompilerRule(treat_as="config", extract={}),
        )
        source = textwrap.dedent("""
            @flow
            async def flow(p: dict) -> dict:
                async with asyncio.timeout(30):
                    async with asyncio.timeout(10):
                        p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py", rules=rules)
        _, ops = parser.parse()

        assert len(ops) == 2
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "handler"
        assert isinstance(ops[1], Return)

    def test_nested_inline_managers_produce_nested_with_blocks(self):
        """Outer inline wraps inner inline: outer `WithBlock` contains inner `WithBlock`."""
        source = textwrap.dedent("""
            @flow
            def flow(p: dict) -> dict:
                with outer_ctx():
                    with inner_ctx():
                        p = handler(p)
                return p
        """)
        rules = _inline_rules("outer_ctx", "inner_ctx")
        parser = FlowParser(source, "test.py", rules=rules)
        _, ops = parser.parse()

        assert len(ops) == 2
        outer = ops[0]
        assert isinstance(outer, WithBlock)
        assert "outer_ctx" in outer.expr

        assert len(outer.body) == 1
        inner = outer.body[0]
        assert isinstance(inner, WithBlock)
        assert "inner_ctx" in inner.expr

        assert len(inner.body) == 1
        assert isinstance(inner.body[0], ActorCall)

    def test_nested_config_then_inline(self):
        """Outer config stripped → remaining op is inline WithBlock."""
        source = textwrap.dedent("""
            @flow
            async def flow(p: dict) -> dict:
                async with asyncio.timeout(30):
                    with custom_ctx():
                        p = handler(p)
                return p
        """)
        rules2 = CompilerRules(
            {
                "asyncio.timeout": CompilerRule(treat_as="config", extract={"delay": "ASYA_RESILIENCY_ACTOR_TIMEOUT"}),
                "custom_ctx": CompilerRule(treat_as="inline"),
            }
        )
        parser = FlowParser(source, "test.py", rules=rules2)
        _, ops = parser.parse()

        assert len(ops) == 2
        assert isinstance(ops[0], WithBlock)
        assert "custom_ctx" in ops[0].expr
        assert isinstance(ops[1], Return)


class TestMultipleWithItems:
    """Multiple withitems in a single `with` statement."""

    def test_multiple_config_items_all_stripped(self):
        """Two config items → body ops returned, both extracted."""
        rules = CompilerRules(
            {
                "asyncio.timeout": CompilerRule(
                    treat_as="config",
                    extract={"delay": "ASYA_RESILIENCY_ACTOR_TIMEOUT"},
                ),
                "another_config": CompilerRule(treat_as="config", extract={}),
            }
        )
        source = textwrap.dedent("""
            @flow
            async def flow(p: dict) -> dict:
                async with asyncio.timeout(30), another_config():
                    p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py", rules=rules)
        _, ops = parser.parse()

        assert len(ops) == 2
        assert isinstance(ops[0], ActorCall)
        assert isinstance(ops[1], Return)

    def test_multiple_inline_items_combined_in_expr(self):
        """Two inline items → single WithBlock with both in expr."""
        source = textwrap.dedent("""
            @flow
            def flow(p: dict) -> dict:
                with ctx_a(), ctx_b():
                    p = handler(p)
                return p
        """)
        rules = _inline_rules("ctx_a", "ctx_b")
        parser = FlowParser(source, "test.py", rules=rules)
        _, ops = parser.parse()

        assert len(ops) == 2
        assert isinstance(ops[0], WithBlock)
        wb = ops[0]
        assert "ctx_a()" in wb.expr
        assert "ctx_b()" in wb.expr

    def test_mixed_treat_as_raises_error(self):
        """Config + inline in the same `with` statement is unsupported."""
        source = textwrap.dedent("""
            @flow
            async def flow(p: dict) -> dict:
                async with asyncio.timeout(30), custom_ctx():
                    p = handler(p)
                return p
        """)
        rules = CompilerRules(
            {
                "asyncio.timeout": CompilerRule(treat_as="config", extract={}),
                "custom_ctx": CompilerRule(treat_as="inline"),
            }
        )
        parser = FlowParser(source, "test.py", rules=rules)
        with pytest.raises(FlowCompileError, match="mixed"):
            parser.parse()
