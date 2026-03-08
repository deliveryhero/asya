"""Unit tests for # asya: <action> inline comment directives."""

import textwrap

import pytest
from asya_cli.flow.errors import FlowCompileError
from asya_cli.flow.ir import ActorCall, AsyaDirective, Mutation
from asya_cli.flow.parser import FlowParser


class TestActorDirective:
    """# asya: actor — explicitly force dispatch to actor queue."""

    def test_actor_directive_produces_actor_call(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)  # asya: actor
                return p
        """)
        _, ops = FlowParser(source, "test.py").parse()
        assert len(ops) == 2
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "handler"
        assert ops[0].directive == AsyaDirective(action="actor")

    def test_actor_directive_on_await_call(self):
        source = textwrap.dedent("""
            async def flow(p: dict) -> dict:
                p = await handler(p)  # asya: actor
                return p
        """)
        _, ops = FlowParser(source, "test.py").parse()
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "handler"

    def test_actor_directive_on_module_qualified_call(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = validators.check(p)  # asya: actor
                return p
        """)
        _, ops = FlowParser(source, "test.py").parse()
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "validators.check"


class TestInlineDirective:
    """# asya: inline — embed call in router instead of dispatching to a queue."""

    def test_inline_directive_converts_actor_call_to_mutation(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)  # asya: inline
                return p
        """)
        _, ops = FlowParser(source, "test.py").parse()
        assert len(ops) == 2
        assert isinstance(ops[0], Mutation)
        assert "handler" in ops[0].code
        assert "p" in ops[0].code

    def test_inline_directive_on_await_call(self):
        source = textwrap.dedent("""
            async def flow(p: dict) -> dict:
                p = await handler(p)  # asya: inline
                return p
        """)
        _, ops = FlowParser(source, "test.py").parse()
        assert isinstance(ops[0], Mutation)
        assert "handler" in ops[0].code

    def test_inline_directive_on_existing_mutation_is_noop(self):
        """# asya: inline on a subscript assignment is already inline — no-op."""
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p['id'] = 'abc'  # asya: inline
                return p
        """)
        _, ops = FlowParser(source, "test.py").parse()
        assert isinstance(ops[0], Mutation)
        assert "p['id']" in ops[0].code

    def test_inline_interleaved_with_actor_calls(self):
        """Mixed inline + actor calls in sequence produce correct IR types."""
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = fast_util(p)  # asya: inline
                p = slow_actor(p)
                return p
        """)
        _, ops = FlowParser(source, "test.py").parse()
        assert len(ops) == 3
        assert isinstance(ops[0], Mutation)
        assert isinstance(ops[1], ActorCall)
        assert ops[1].name == "slow_actor"
        assert ops[1].directive is None


class TestUnknownDirective:
    """Unknown action words raise FlowCompileError at construction time."""

    def test_unknown_action_raises_error(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)  # asya: typo
                return p
        """)
        with pytest.raises(FlowCompileError, match="Unknown directive.*asya: typo"):
            FlowParser(source, "test.py")

    def test_error_message_lists_valid_actions(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)  # asya: invalid
                return p
        """)
        with pytest.raises(FlowCompileError, match="actor"):
            FlowParser(source, "test.py")

    def test_error_reports_correct_line_number(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p['x'] = 1
                p = handler(p)  # asya: bad
                return p
        """)
        with pytest.raises(FlowCompileError, match="test.py:4"):
            FlowParser(source, "test.py")


class TestUnsupportedDirectives:
    """flow, unfold, config are valid syntax but not yet implemented."""

    @pytest.mark.parametrize("action", ["flow", "unfold", "config"])
    def test_unsupported_action_raises_at_parse_time(self, action: str):
        source = textwrap.dedent(f"""
            def flow(p: dict) -> dict:
                p = handler(p)  # asya: {action}
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match=f"asya: {action}.*not yet supported"):
            parser.parse()


class TestDirectiveIgnored:
    """Non-asya comments and partial prefixes must not affect compilation."""

    def test_regular_comment_ignored(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)  # call the handler
                return p
        """)
        _, ops = FlowParser(source, "test.py").parse()
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "handler"
        assert ops[0].directive is None

    def test_partial_prefix_not_matched(self):
        """'asya' without colon should not trigger directive parsing."""
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)  # asya actor (missing colon)
                return p
        """)
        _, ops = FlowParser(source, "test.py").parse()
        assert isinstance(ops[0], ActorCall)
        assert ops[0].directive is None

    def test_directive_on_unrelated_line_ignored(self):
        """A directive comment on a line with no statement doesn't affect adjacent statements."""
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)
                return p
            # asya: actor
        """)
        _, ops = FlowParser(source, "test.py").parse()
        assert isinstance(ops[0], ActorCall)
        assert ops[0].directive is None


class TestDirectiveWithClassHandler:
    """Directives work on class method actor calls."""

    def test_inline_on_class_method(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                model = Model()
                p = model.predict(p)  # asya: inline
                return p
        """)
        _, ops = FlowParser(source, "test.py").parse()
        mutations = [op for op in ops if isinstance(op, Mutation)]
        assert any("predict" in m.code for m in mutations)

    def test_actor_directive_on_class_method(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                model = Model()
                p = model.predict(p)  # asya: actor
                return p
        """)
        _, ops = FlowParser(source, "test.py").parse()
        actor_calls = [op for op in ops if isinstance(op, ActorCall)]
        assert any("predict" in a.name for a in actor_calls)
        assert actor_calls[0].directive == AsyaDirective(action="actor")
