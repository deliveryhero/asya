"""Tests for inline comment directive parsing, call-site decoration, and definition-site decorators."""

import textwrap

import pytest
from asya_lab.flow.errors import FlowCompileError
from asya_lab.flow.parser import ActorCall, FlowParser, Mutation, Return


class TestInlineCommentDirectives:
    """# asya: actor / # asya: inline comment overrides."""

    def test_treat_as_actor_keeps_actor_call(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = handler(p)  # asya: actor
                return p
        """)
        ops = FlowParser(source, "test.py").parse().operations
        assert len(ops) == 2
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "handler"

    def test_treat_as_inline_converts_call_to_mutation(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = uuid_inject(p)  # asya: inline
                return p
        """)
        ops = FlowParser(source, "test.py").parse().operations
        assert len(ops) == 2
        assert isinstance(ops[0], Mutation)
        assert "uuid_inject" in ops[0].code

    def test_treat_as_inline_with_await(self):
        source = textwrap.dedent("""
            @flow
            async def my_flow(p: dict) -> dict:
                p = await enrich(p)  # asya: inline
                return p
        """)
        ops = FlowParser(source, "test.py").parse().operations
        assert isinstance(ops[0], Mutation)
        assert "enrich" in ops[0].code

    def test_comment_without_asya_prefix_is_ignored(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = handler(p)  # treat-as-inline (no asya: prefix)
                return p
        """)
        ops = FlowParser(source, "test.py").parse().operations
        assert isinstance(ops[0], ActorCall)

    def test_unknown_treat_as_value_raises_error(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = handler(p)  # asya: decompose
                return p
        """)
        with pytest.raises(FlowCompileError, match="decompose"):
            FlowParser(source, "test.py").parse()

    def test_flow_directive_inlines_flow_body(self):
        source = textwrap.dedent("""
            @flow
            def sub_flow(p: dict) -> dict:
                p = inner_handler(p)
                return p

            @flow
            def my_flow(p: dict) -> dict:
                p = sub_flow(p)  # asya: flow
                return p
        """)
        result = FlowParser(source, "test.py").parse()
        actor_names = [op.name for op in result.operations if isinstance(op, ActorCall)]
        assert "inner_handler" in actor_names

    def test_unfold_directive_inlines_function_body(self):
        source = textwrap.dedent("""
            def helper(p: dict) -> dict:
                p = inner_handler(p)
                return p

            @flow
            def my_flow(p: dict) -> dict:
                p = helper(p)  # asya: unfold
                return p
        """)
        result = FlowParser(source, "test.py").parse()
        actor_names = [op.name for op in result.operations if isinstance(op, ActorCall)]
        assert "inner_handler" in actor_names

    def test_flow_directive_without_definition_raises_error(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = unknown_flow(p)  # asya: flow
                return p
        """)
        with pytest.raises(FlowCompileError, match="not found"):
            FlowParser(source, "test.py").parse()


class TestCallSiteDecoration:
    """actor(handler)(p) and inline(fn)(p) call-site patterns."""

    def test_actor_wrapper_produces_actor_call(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = actor(handler)(p)
                return p
        """)
        ops = FlowParser(source, "test.py").parse().operations
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "handler"

    def test_inline_wrapper_produces_mutation(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = inline(uuid_inject)(p)
                return p
        """)
        ops = FlowParser(source, "test.py").parse().operations
        assert isinstance(ops[0], Mutation)
        assert "uuid_inject" in ops[0].code

    def test_actor_wrapper_with_module_attribute(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = actor(handlers.process)(p)
                return p
        """)
        ops = FlowParser(source, "test.py").parse().operations
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "handlers.process"

    def test_await_actor_wrapper(self):
        source = textwrap.dedent("""
            @flow
            async def my_flow(p: dict) -> dict:
                p = await actor(handler)(p)
                return p
        """)
        ops = FlowParser(source, "test.py").parse().operations
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "handler"

    def test_unknown_wrapper_raises_error(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = unknown_wrapper(handler)(p)
                return p
        """)
        with pytest.raises(FlowCompileError, match="unknown_wrapper"):
            FlowParser(source, "test.py").parse()

    def test_wrapper_with_non_name_inner_arg_raises_error(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = actor("not_a_name")(p)
                return p
        """)
        with pytest.raises(FlowCompileError):
            FlowParser(source, "test.py").parse()

    def test_inline_wrapper_with_module_attribute(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = inline(utils.inject)(p)
                return p
        """)
        ops = FlowParser(source, "test.py").parse().operations
        assert isinstance(ops[0], Mutation)
        assert "utils.inject" in ops[0].code

    def test_wrapper_with_multiple_inner_args_raises_error(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = actor(handler_a, handler_b)(p)
                return p
        """)
        with pytest.raises(FlowCompileError):
            FlowParser(source, "test.py").parse()

    def test_inline_directive_overrides_actor_wrapper(self):
        # Inline comment has higher priority than call-site wrapper.
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = actor(stamp_timestamp)(p)  # asya: inline
                return p
        """)
        ops = FlowParser(source, "test.py").parse().operations
        assert isinstance(ops[0], Mutation)
        assert "stamp_timestamp" in ops[0].code

    def test_await_preserved_for_inline_call_site_wrapper(self):
        source = textwrap.dedent("""
            @flow
            async def my_flow(p: dict) -> dict:
                p = await inline(enrich)(p)
                return p
        """)
        ops = FlowParser(source, "test.py").parse().operations
        assert isinstance(ops[0], Mutation)
        assert "await" in ops[0].code
        assert "enrich" in ops[0].code

    def test_custom_wrapper_names(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = asya_actor(handler)(p)
                return p
        """)
        custom = frozenset({"asya_actor", "asya_flow", "asya_inline", "asya_unfold"})
        ops = FlowParser(source, "test.py", known_wrappers=custom).parse().operations
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "handler"

    def test_custom_wrapper_rejects_default_names(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = actor(handler)(p)
                return p
        """)
        custom = frozenset({"asya_actor", "asya_flow"})
        with pytest.raises(FlowCompileError, match="actor"):
            FlowParser(source, "test.py", known_wrappers=custom).parse()


class TestDefinitionSiteDecorators:
    """@actor / @inline decorators on function definitions in the same file."""

    def test_actor_decorator_produces_actor_call(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = handler(p)
                return p

            @actor
            def handler(p: dict) -> dict:
                return p
        """)
        ops = FlowParser(source, "test.py").parse().operations
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "handler"

    def test_inline_decorator_produces_mutation(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = uuid_inject(p)
                return p

            @inline
            def uuid_inject(p: dict) -> dict:
                return p
        """)
        ops = FlowParser(source, "test.py").parse().operations
        assert isinstance(ops[0], Mutation)
        assert "uuid_inject" in ops[0].code

    def test_unknown_decorator_local_function_unfolds(self):
        """Local function with unknown decorator defaults to unfold (body expanded)."""
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = handler(p)
                return p

            @some_framework_decorator
            def handler(p: dict) -> dict:
                return p
        """)
        ops = FlowParser(source, "test.py").parse().operations
        # Local function without @actor -> unfold (body expanded into flow)
        assert isinstance(ops[0], Return)  # handler's body is just `return p`

    def test_unknown_decorator_with_actor_is_actor(self):
        """Local function with @actor + unknown decorator is still an actor."""
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = handler(p)
                return p

            @actor
            @some_framework_decorator
            def handler(p: dict) -> dict:
                return p
        """)
        ops = FlowParser(source, "test.py").parse().operations
        assert isinstance(ops[0], ActorCall)

    def test_multiple_decorators_first_known_wins(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = handler(p)
                return p

            @actor
            @some_retry_decorator
            def handler(p: dict) -> dict:
                return p
        """)
        ops = FlowParser(source, "test.py").parse().operations
        assert isinstance(ops[0], ActorCall)

    def test_inline_comment_overrides_actor_decorator(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = handler(p)  # asya: inline
                return p

            @actor
            def handler(p: dict) -> dict:
                return p
        """)
        # Inline comment (highest priority) wins over @actor
        ops = FlowParser(source, "test.py").parse().operations
        assert isinstance(ops[0], Mutation)
