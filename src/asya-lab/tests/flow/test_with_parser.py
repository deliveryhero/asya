"""Unit tests for with/async with statement parsing in the flow parser."""

import textwrap

import pytest
from asya_lab.flow.errors import FlowCompileError
from asya_lab.flow.parser import ActorCall, FlowParser, Mutation, Return
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
        result = parser.parse()

        ops = result.operations

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
        result = parser.parse()

        ops = result.operations

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
        result = parser.parse()

        ops = result.operations

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
        assert config["spec_values"]["spec.resiliency.timeout.actor"] == "30"


class TestPerScopeSemantics:
    """Extracted configs carry scope information: scope_type and scope_actors."""

    def test_context_manager_scope_tracks_single_actor(self):
        """Config from context manager records the actor in its scope."""
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
        assert config["scope_type"] == "context_manager"
        assert config["scope_actors"] == ["handler"]

    def test_context_manager_scope_tracks_multiple_actors(self):
        """Config from context manager wrapping multiple actors lists all."""
        source = textwrap.dedent("""
            @flow
            async def flow(p: dict) -> dict:
                async with asyncio.timeout(30):
                    p = slow_handler(p)
                    p = another_handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        parser.parse()

        assert len(parser.extracted_configs) == 1
        config = parser.extracted_configs[0]
        assert config["scope_type"] == "context_manager"
        assert config["scope_actors"] == ["slow_handler", "another_handler"]

    def test_context_manager_scope_ignores_mutations(self):
        """Mutations in a context manager body are not counted as scope actors."""
        source = textwrap.dedent("""
            @flow
            async def flow(p: dict) -> dict:
                async with asyncio.timeout(30):
                    p["status"] = "running"
                    p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        parser.parse()

        config = parser.extracted_configs[0]
        assert config["scope_actors"] == ["handler"]

    def test_nested_context_managers_have_separate_scopes(self):
        """Nested context managers each get their own scope_actors."""
        source = textwrap.dedent("""
            @flow
            async def flow(p: dict) -> dict:
                async with asyncio.timeout(60):
                    p = outer_handler(p)
                    async with asyncio.timeout(10):
                        p = inner_handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        parser.parse()

        assert len(parser.extracted_configs) == 2
        # Inner config is appended first (recursion processes it during outer body parsing)
        inner = parser.extracted_configs[0]
        outer = parser.extracted_configs[1]
        assert inner["scope_type"] == "context_manager"
        assert inner["scope_actors"] == ["inner_handler"]
        assert inner["spec_values"]["spec.resiliency.timeout.actor"] == "10"
        assert outer["scope_type"] == "context_manager"
        assert outer["scope_actors"] == ["outer_handler", "inner_handler"]
        assert outer["spec_values"]["spec.resiliency.timeout.actor"] == "60"

    def test_multiple_with_items_share_scope(self):
        """Multiple context managers in one `with` share the same scope_actors."""
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
        parser.parse()

        assert len(parser.extracted_configs) == 2
        for config in parser.extracted_configs:
            assert config["scope_type"] == "context_manager"
            assert config["scope_actors"] == ["handler"]

    def test_scope_type_present_in_parse_result(self):
        """extracted_configs in ParseResult also carry scope info."""
        source = textwrap.dedent("""
            @flow
            async def flow(p: dict) -> dict:
                async with asyncio.timeout(30):
                    p = handler_a(p)
                    p = handler_b(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        result = parser.parse()

        config = result.extracted_configs[0]
        assert config["scope_type"] == "context_manager"
        assert config["scope_actors"] == ["handler_a", "handler_b"]

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
        result = parser.parse()

        ops = result.operations

        assert len(ops) == 2
        assert isinstance(ops[0], ActorCall)
        assert isinstance(ops[1], Return)


class TestInlineRuleWith:
    """Inline with blocks are no longer supported in the simplified compiler."""

    def test_inline_with_rejected(self):
        source = textwrap.dedent("""
            @flow
            def flow(p: dict) -> dict:
                with custom_ctx():
                    p = handler(p)
                return p
        """)
        rules = _inline_rules("custom_ctx")
        parser = FlowParser(source, "test.py", rules=rules)
        with pytest.raises(FlowCompileError, match="not supported"):
            parser.parse()

    def test_async_with_inline_rejected(self):
        source = textwrap.dedent("""
            @flow
            async def flow(p: dict) -> dict:
                async with custom_ctx():
                    p = handler(p)
                return p
        """)
        rules = _inline_rules("custom_ctx")
        parser = FlowParser(source, "test.py", rules=rules)
        with pytest.raises(FlowCompileError, match="not supported"):
            parser.parse()


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
        result = parser.parse()

        ops = result.operations

        assert len(ops) == 2
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "handler"
        assert isinstance(ops[1], Return)

    def test_nested_inline_managers_produce_nested_with_blocks(self):
        """Nested inline with blocks are rejected."""
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
        with pytest.raises(FlowCompileError, match="not supported"):
            parser.parse()

    def test_nested_config_then_inline(self):
        """Outer config + inner inline → inner inline is rejected."""
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
        with pytest.raises(FlowCompileError, match="not supported"):
            parser.parse()


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
        result = parser.parse()

        ops = result.operations

        assert len(ops) == 2
        assert isinstance(ops[0], ActorCall)
        assert isinstance(ops[1], Return)

    def test_multiple_inline_items_combined_in_expr(self):
        """Multiple inline with items are rejected."""
        source = textwrap.dedent("""
            @flow
            def flow(p: dict) -> dict:
                with ctx_a(), ctx_b():
                    p = handler(p)
                return p
        """)
        rules = _inline_rules("ctx_a", "ctx_b")
        parser = FlowParser(source, "test.py", rules=rules)
        with pytest.raises(FlowCompileError, match="not supported"):
            parser.parse()

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
        with pytest.raises(FlowCompileError):
            parser.parse()
