"""Tests for flow composition: @flow inlining, directives, call-site wrappers, and edge cases."""

import textwrap

import pytest
from asya_lab.compiler.rules import CompilerRule as EngineRule
from asya_lab.compiler.rules import RuleEngine, TreatAs, WhereNode
from asya_lab.flow.errors import FlowCompileError
from asya_lab.flow.parser import ActorCall, Conditional, FlowParser, Loop, Mutation


class TestFlowCompositionBasic:
    """Basic flow composition: outer @flow calls inner @flow, body is inlined."""

    def test_simple_flow_composition_inlines_body(self):
        source = textwrap.dedent("""
            @flow
            def inner(p: dict) -> dict:
                p = actor_a(p)
                p = actor_b(p)
                return p

            @flow
            def outer(p: dict) -> dict:
                p = inner(p)
                return p
        """)
        result = FlowParser(source, "test.py").parse()
        actor_names = [op.name for op in result.operations if isinstance(op, ActorCall)]
        assert actor_names == ["actor_a", "actor_b"]

    def test_flow_composition_records_group(self):
        source = textwrap.dedent("""
            @flow
            def inner(p: dict) -> dict:
                p = actor_a(p)
                p = actor_b(p)
                return p

            @flow
            def outer(p: dict) -> dict:
                p = inner(p)
                return p
        """)
        result = FlowParser(source, "test.py").parse()
        assert len(result.groups) == 1
        assert result.groups[0]["id"] == "inner"
        assert result.groups[0]["nodes"] == ["actor_a", "actor_b"]

    def test_flow_composition_with_conditional_inner(self):
        source = textwrap.dedent("""
            @flow
            def inner(p: dict) -> dict:
                if p["flag"]:
                    p = actor_a(p)
                else:
                    p = actor_b(p)
                return p

            @flow
            def outer(p: dict) -> dict:
                p = inner(p)
                return p
        """)
        result = FlowParser(source, "test.py").parse()
        # Inner's Return is stripped, so first op should be the Conditional
        assert len(result.operations) >= 1
        cond = result.operations[0]
        assert isinstance(cond, Conditional)
        assert len(cond.true_branch) == 1
        assert isinstance(cond.true_branch[0], ActorCall)
        assert cond.true_branch[0].name == "actor_a"
        assert len(cond.false_branch) == 1
        assert isinstance(cond.false_branch[0], ActorCall)
        assert cond.false_branch[0].name == "actor_b"

    def test_multiple_references_create_separate_groups(self):
        source = textwrap.dedent("""
            @flow
            def inner(p: dict) -> dict:
                p = actor_a(p)
                return p

            @flow
            def outer(p: dict) -> dict:
                p = inner(p)
                p = inner(p)
                return p
        """)
        result = FlowParser(source, "test.py").parse()
        assert len(result.groups) == 2
        assert result.groups[0]["id"] == "inner"
        assert result.groups[1]["id"] == "inner"

    def test_nested_flow_composition(self):
        source = textwrap.dedent("""
            @flow
            def level2(p: dict) -> dict:
                p = actor_c(p)
                return p

            @flow
            def level1(p: dict) -> dict:
                p = actor_b(p)
                p = level2(p)
                return p

            @flow
            def top(p: dict) -> dict:
                p = actor_a(p)
                p = level1(p)
                return p
        """)
        result = FlowParser(source, "test.py").parse()
        actor_names = [op.name for op in result.operations if isinstance(op, ActorCall)]
        assert actor_names == ["actor_a", "actor_b", "actor_c"]

    def test_flow_composition_uses_outer_flow_name(self):
        source = textwrap.dedent("""
            @flow
            def inner(p: dict) -> dict:
                p = actor_a(p)
                return p

            @flow
            def outer(p: dict) -> dict:
                p = inner(p)
                return p
        """)
        result = FlowParser(source, "test.py").parse()
        assert result.flow_name == "outer"

    def test_inner_flow_return_stripped(self):
        source = textwrap.dedent("""
            @flow
            def inner(p: dict) -> dict:
                p = actor_a(p)
                return p

            @flow
            def outer(p: dict) -> dict:
                p = inner(p)
                p = actor_b(p)
                return p
        """)
        result = FlowParser(source, "test.py").parse()
        # Inner's Return is stripped; outer's Return remains at the end
        op_types = [type(op).__name__ for op in result.operations]
        # actor_a from inner, actor_b from outer, Return from outer
        assert op_types == ["ActorCall", "ActorCall", "Return"]
        actor_names = [op.name for op in result.operations if isinstance(op, ActorCall)]
        assert actor_names == ["actor_a", "actor_b"]

    def test_inner_flow_with_mutations(self):
        source = textwrap.dedent("""
            @flow
            def inner(p: dict) -> dict:
                p["key"] = "value"
                p = actor_a(p)
                return p

            @flow
            def outer(p: dict) -> dict:
                p = inner(p)
                return p
        """)
        result = FlowParser(source, "test.py").parse()
        assert isinstance(result.operations[0], Mutation)
        assert isinstance(result.operations[1], ActorCall)
        assert result.operations[1].name == "actor_a"


class TestFlowCompositionDirectives:
    """Inline comment directives: # asya: flow and # asya: unfold."""

    def test_flow_directive_with_definition(self):
        source = textwrap.dedent("""
            @flow
            def sub(p: dict) -> dict:
                p = handler_a(p)
                return p

            @flow
            def my_flow(p: dict) -> dict:
                p = sub(p)  # asya: flow
                return p
        """)
        result = FlowParser(source, "test.py").parse()
        actor_names = [op.name for op in result.operations if isinstance(op, ActorCall)]
        assert "handler_a" in actor_names

    def test_unfold_directive_inlines_plain_function(self):
        source = textwrap.dedent("""
            def helper(p: dict) -> dict:
                p = handler_a(p)
                return p

            @flow
            def my_flow(p: dict) -> dict:
                p = helper(p)  # asya: unfold
                return p
        """)
        result = FlowParser(source, "test.py").parse()
        actor_names = [op.name for op in result.operations if isinstance(op, ActorCall)]
        assert "handler_a" in actor_names

    def test_flow_directive_without_definition_raises(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                p = missing_flow(p)  # asya: flow
                return p
        """)
        with pytest.raises(FlowCompileError, match="not found"):
            FlowParser(source, "test.py").parse()


class TestFlowCompositionCallSite:
    """Call-site wrappers: flow(inner)(p) and unfold(helper)(p)."""

    def test_flow_wrapper_inlines_body(self):
        source = textwrap.dedent("""
            @flow
            def inner(p: dict) -> dict:
                p = handler_x(p)
                return p

            @flow
            def my_flow(p: dict) -> dict:
                p = flow(inner)(p)
                return p
        """)
        result = FlowParser(source, "test.py").parse()
        actor_names = [op.name for op in result.operations if isinstance(op, ActorCall)]
        assert "handler_x" in actor_names

    def test_unfold_wrapper_inlines_body(self):
        source = textwrap.dedent("""
            def helper(p: dict) -> dict:
                p = handler_y(p)
                return p

            @flow
            def my_flow(p: dict) -> dict:
                p = unfold(helper)(p)
                return p
        """)
        result = FlowParser(source, "test.py").parse()
        actor_names = [op.name for op in result.operations if isinstance(op, ActorCall)]
        assert "handler_y" in actor_names


class TestFlowCompositionEdgeCases:
    """Edge cases: recursion, loops, parameter normalization."""

    def test_circular_reference_raises_error(self):
        source = textwrap.dedent("""
            @flow
            def flow_a(p: dict) -> dict:
                p = flow_b(p)
                return p

            @flow
            def flow_b(p: dict) -> dict:
                p = flow_a(p)
                return p
        """)
        with pytest.raises(FlowCompileError, match="depth exceeded"):
            FlowParser(source, "test.py").parse()

    def test_inner_flow_with_while_loop(self):
        source = textwrap.dedent("""
            @flow
            def inner(p: dict) -> dict:
                while p["continue"]:
                    p = actor_a(p)
                return p

            @flow
            def outer(p: dict) -> dict:
                p = inner(p)
                return p
        """)
        result = FlowParser(source, "test.py").parse()
        loop_op = result.operations[0]
        assert isinstance(loop_op, Loop)
        assert len(loop_op.body) == 1
        assert isinstance(loop_op.body[0], ActorCall)
        assert loop_op.body[0].name == "actor_a"

    def test_inner_flow_with_payload_param(self):
        source = textwrap.dedent("""
            @flow
            def inner(payload: dict) -> dict:
                payload = actor_a(payload)
                return payload

            @flow
            def outer(p: dict) -> dict:
                p = inner(p)
                return p
        """)
        result = FlowParser(source, "test.py").parse()
        actor_names = [op.name for op in result.operations if isinstance(op, ActorCall)]
        assert "actor_a" in actor_names

    def test_inner_flow_with_state_param(self):
        source = textwrap.dedent("""
            @flow
            def inner(state: dict) -> dict:
                state = actor_a(state)
                return state

            @flow
            def outer(p: dict) -> dict:
                p = inner(p)
                return p
        """)
        result = FlowParser(source, "test.py").parse()
        actor_names = [op.name for op in result.operations if isinstance(op, ActorCall)]
        assert "actor_a" in actor_names


class TestFlowCompositionE2E:
    """End-to-end: compile and verify groups in graph data."""

    def test_compiled_graph_has_groups(self):
        from asya_lab.flow.compiler import FlowCompiler

        source = textwrap.dedent("""
            @flow
            def inner(p: dict) -> dict:
                p = actor_a(p)
                p = actor_b(p)
                return p

            @flow
            def outer(p: dict) -> dict:
                p = inner(p)
                p = actor_c(p)
                return p
        """)
        compiler = FlowCompiler()
        code = compiler.compile(textwrap.dedent(source), "test.py")
        assert code  # compilation succeeded
        graph_data = compiler._graph_data
        assert graph_data is not None
        assert len(graph_data.groups) == 1
        assert graph_data.groups[0]["id"] == "inner"
        assert graph_data.groups[0]["nodes"] == ["actor_a", "actor_b"]


class TestUnfoldDecoratorReScoping:
    """Decorated unfold functions re-scope extracted config to expanded actors."""

    def _retry_engine(self) -> RuleEngine:
        rule = EngineRule(
            match="tenacity.retry",
            treat_as=TreatAs.CONFIG,
            where=[
                WhereNode(
                    param="stop",
                    where=[
                        WhereNode(
                            match="stop_after_attempt",
                            where=[
                                WhereNode(
                                    param="max_attempt_number",
                                    assign_to="spec.resiliency.policies.default.maxAttempts",
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )
        return RuleEngine([rule])

    def test_unfold_rescopes_decorator_config_to_expanded_actors(self):
        """@retry on an unfold function applies config to all actors inside."""
        source = textwrap.dedent("""
            from tenacity import retry, stop_after_attempt

            @flow
            def pipeline(p: dict) -> dict:
                p = resilient_work(p)
                return p

            @unfold
            @retry(stop=stop_after_attempt(3))
            def resilient_work(p: dict) -> dict:
                p = actor_a(p)
                p = actor_b(p)
                return p
        """)
        engine = self._retry_engine()
        result = FlowParser(source, "test.py", rule_engine=engine).parse()

        # The decorator config should be re-scoped to the expanded actors
        decorator_configs = [c for c in result.extracted_configs if c["scope_type"] == "decorator"]
        assert len(decorator_configs) == 1
        config = decorator_configs[0]
        assert config["scope_actors"] == ["actor_a", "actor_b"]
        assert config["spec_values"]["spec.resiliency.policies.default.maxAttempts"] == 3

    def test_unfold_rescopes_preserves_non_unfolded_decorator_configs(self):
        """Decorator config on a non-unfolded function stays scoped to itself."""
        source = textwrap.dedent("""
            from tenacity import retry, stop_after_attempt

            @flow
            def pipeline(p: dict) -> dict:
                p = actor_c(p)
                return p

            @actor
            @retry(stop=stop_after_attempt(5))
            def actor_c(p: dict) -> dict:
                return p
        """)
        engine = self._retry_engine()
        result = FlowParser(source, "test.py", rule_engine=engine).parse()

        decorator_configs = [c for c in result.extracted_configs if c["scope_type"] == "decorator"]
        assert len(decorator_configs) == 1
        config = decorator_configs[0]
        # Not unfolded, so scope stays on the function name
        assert config["scope_actors"] == ["actor_c"]
        assert config["spec_values"]["spec.resiliency.policies.default.maxAttempts"] == 5

    def test_flow_decorated_function_rescopes_decorator_config(self):
        """@retry on a @flow function also re-scopes (same mechanism as unfold)."""
        source = textwrap.dedent("""
            from tenacity import retry, stop_after_attempt

            @flow
            @retry(stop=stop_after_attempt(7))
            def inner_flow(p: dict) -> dict:
                p = handler_x(p)
                p = handler_y(p)
                return p

            @flow
            def pipeline(p: dict) -> dict:
                p = inner_flow(p)
                return p
        """)
        engine = self._retry_engine()
        result = FlowParser(source, "test.py", rule_engine=engine).parse()

        decorator_configs = [c for c in result.extracted_configs if c["scope_type"] == "decorator"]
        assert len(decorator_configs) == 1
        config = decorator_configs[0]
        assert config["scope_actors"] == ["handler_x", "handler_y"]
        assert config["spec_values"]["spec.resiliency.policies.default.maxAttempts"] == 7
