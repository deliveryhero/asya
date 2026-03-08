"""Unit tests for # asya: treat-as-* inline comment directives."""

import textwrap

import pytest
from asya_cli.flow.errors import FlowCompileError
from asya_cli.flow.ir import ActorCall, AsyaDirective, Mutation
from asya_cli.flow.parser import FlowParser


class TestTreatAsActor:
    """# asya: treat-as-actor — force treat as actor dispatch."""

    def test_treat_as_actor_default_name(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)  # asya: treat-as-actor
                return p
        """)
        _, ops = FlowParser(source, "test.py").parse()
        assert len(ops) == 2
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "handler"
        assert ops[0].directive is not None
        assert ops[0].directive.treat_as == "actor"
        assert ops[0].directive.name is None

    def test_treat_as_actor_with_name_override(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)  # asya: treat-as-actor name=order-validator
                return p
        """)
        _, ops = FlowParser(source, "test.py").parse()
        assert len(ops) == 2
        actor = ops[0]
        assert isinstance(actor, ActorCall)
        assert actor.name == "order-validator"
        assert actor.directive is not None
        assert actor.directive.treat_as == "actor"
        assert actor.directive.name == "order-validator"

    def test_treat_as_actor_with_dotted_name_override(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = validate(p)  # asya: treat-as-actor name=validators.strict_validate
                return p
        """)
        _, ops = FlowParser(source, "test.py").parse()
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "validators.strict_validate"


class TestTreatAsInline:
    """# asya: treat-as-inline — embed call in router instead of dispatching."""

    def test_treat_as_inline_converts_actor_call_to_mutation(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)  # asya: treat-as-inline
                return p
        """)
        _, ops = FlowParser(source, "test.py").parse()
        assert len(ops) == 2
        assert isinstance(ops[0], Mutation)
        assert "handler" in ops[0].code
        assert "p" in ops[0].code

    def test_treat_as_inline_on_await_call(self):
        source = textwrap.dedent("""
            async def flow(p: dict) -> dict:
                p = await handler(p)  # asya: treat-as-inline
                return p
        """)
        _, ops = FlowParser(source, "test.py").parse()
        assert isinstance(ops[0], Mutation)
        assert "handler" in ops[0].code

    def test_treat_as_inline_on_mutation_is_noop(self):
        """# asya: treat-as-inline on an already-inline statement is a no-op."""
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["id"] = "abc"  # asya: treat-as-inline
                return p
        """)
        _, ops = FlowParser(source, "test.py").parse()
        assert isinstance(ops[0], Mutation)
        assert "p['id']" in ops[0].code

    def test_treat_as_inline_interleaved_with_actor_calls(self):
        """Mixed inline + actor calls in sequence."""
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = fast_util(p)  # asya: treat-as-inline
                p = slow_actor(p)
                return p
        """)
        _, ops = FlowParser(source, "test.py").parse()
        assert len(ops) == 3
        assert isinstance(ops[0], Mutation)
        assert isinstance(ops[1], ActorCall)
        assert ops[1].name == "slow_actor"


class TestUnknownDirective:
    """Unknown treat-as actions should raise FlowCompileError at parse time."""

    def test_unknown_action_raises_error(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)  # asya: treat-as-typo
                return p
        """)
        with pytest.raises(FlowCompileError, match="Unknown directive.*treat-as-typo"):
            FlowParser(source, "test.py")

    def test_error_includes_valid_actions(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)  # asya: treat-as-invalid
                return p
        """)
        with pytest.raises(FlowCompileError, match="actor"):
            FlowParser(source, "test.py")

    def test_error_reports_correct_line_number(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["x"] = 1
                p = handler(p)  # asya: treat-as-bad
                return p
        """)
        with pytest.raises(FlowCompileError, match="test.py:4"):
            FlowParser(source, "test.py")


class TestUnsupportedDirectives:
    """flow, decompose, config are valid syntax but not yet implemented."""

    @pytest.mark.parametrize("action", ["flow", "decompose", "config"])
    def test_unsupported_action_raises_at_parse_time(self, action: str):
        source = textwrap.dedent(f"""
            def flow(p: dict) -> dict:
                p = handler(p)  # asya: treat-as-{action}
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match=f"treat-as-{action}.*not yet supported"):
            parser.parse()


class TestDirectiveIgnored:
    """Non-asya comments must not affect compilation."""

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

    def test_partial_prefix_ignored(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)  # asya treat-as-actor (missing colon)
                return p
        """)
        _, ops = FlowParser(source, "test.py").parse()
        assert isinstance(ops[0], ActorCall)
        assert ops[0].directive is None

    def test_comment_on_unrelated_line_ignored(self):
        """A directive on a non-statement line (e.g. class def) doesn't affect parsing."""
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)
                return p
            # asya: treat-as-actor
        """)
        _, ops = FlowParser(source, "test.py").parse()
        assert isinstance(ops[0], ActorCall)
        assert ops[0].directive is None


class TestDirectiveWithClassHandler:
    """Directives work on class method actor calls too."""

    def test_treat_as_inline_on_class_method(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                model = Model()
                p = model.predict(p)  # asya: treat-as-inline
                return p
        """)
        _, ops = FlowParser(source, "test.py").parse()
        mutations = [op for op in ops if isinstance(op, Mutation)]
        assert any("predict" in m.code for m in mutations)

    def test_treat_as_actor_name_override_on_class_method(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                model = Model()
                p = model.predict(p)  # asya: treat-as-actor name=ml-predictor
                return p
        """)
        _, ops = FlowParser(source, "test.py").parse()
        actor_calls = [op for op in ops if isinstance(op, ActorCall)]
        assert any(a.name == "ml-predictor" for a in actor_calls)
