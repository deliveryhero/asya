"""Unit tests for flow parser."""

import textwrap

import pytest
from asya_cli.flow.errors import FlowCompileError
from asya_cli.flow.ir import ActorCall, Condition, Mutation, Return
from asya_cli.flow.parser import FlowParser

from .test_helpers import contains_with_either_quotes


class TestFlowFunctionDetection:
    """Test detection of valid flow functions."""

    def test_detects_flow_with_p_parameter(self):
        source = textwrap.dedent("""
            def my_flow(p: dict) -> dict:
                return p
        """)
        parser = FlowParser(source, "test.py")
        flow_name, _ = parser.parse()
        assert flow_name == "my_flow"

    def test_detects_flow_with_payload_parameter(self):
        source = textwrap.dedent("""
            def my_flow(payload: dict) -> dict:
                return payload
        """)
        parser = FlowParser(source, "test.py")
        flow_name, _ = parser.parse()
        assert flow_name == "my_flow"

    def test_rejects_function_without_return_annotation(self):
        source = textwrap.dedent("""
            def my_flow(p: dict):
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="No flow function found"):
            parser.parse()

    def test_rejects_function_with_wrong_parameter_name(self):
        source = textwrap.dedent("""
            def my_flow(data: dict) -> dict:
                return data
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="No flow function found"):
            parser.parse()

    def test_rejects_function_with_multiple_parameters(self):
        source = textwrap.dedent("""
            def my_flow(p: dict, config: dict) -> dict:
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="No flow function found"):
            parser.parse()

    def test_rejects_function_with_no_parameters(self):
        source = textwrap.dedent("""
            def my_flow() -> dict:
                return {}
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="No flow function found"):
            parser.parse()

    def test_finds_first_valid_flow_function(self):
        source = textwrap.dedent("""
            def helper(x: int) -> int:
                return x

            def my_flow(p: dict) -> dict:
                return p

            def another_flow(p: dict) -> dict:
                return p
        """)
        parser = FlowParser(source, "test.py")
        flow_name, _ = parser.parse()
        assert flow_name == "my_flow"


class TestActorCallParsing:
    """Test parsing of actor/handler calls."""

    def test_parse_single_handler_call(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 2
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "handler"
        assert isinstance(ops[1], Return)

    def test_parse_multiple_sequential_handlers(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler_a(p)
                p = handler_b(p)
                p = handler_c(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 4
        assert all(isinstance(op, ActorCall | Return) for op in ops)
        assert isinstance(ops[0], ActorCall) and ops[0].name == "handler_a"
        assert isinstance(ops[1], ActorCall) and ops[1].name == "handler_b"
        assert isinstance(ops[2], ActorCall) and ops[2].name == "handler_c"

    def test_parse_method_call_as_actor(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = MyClass.process(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 2
        assert isinstance(ops[0], ActorCall)
        assert "MyClass.process" in ops[0].name

    def test_rejects_actor_call_without_argument(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler()
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="must have exactly one argument"):
            parser.parse()

    def test_rejects_actor_call_with_multiple_arguments(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p, config)
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="must have exactly one argument"):
            parser.parse()

    def test_rejects_assignment_to_p_with_non_call(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = {"new": "dict"}
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="Invalid assignment to 'p'"):
            parser.parse()


class TestMutationParsing:
    """Test parsing of payload mutations."""

    def test_parse_simple_subscript_assignment(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["key"] = "value"
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 2
        assert isinstance(ops[0], Mutation)
        assert contains_with_either_quotes(ops[0].code, 'p["key"]')
        assert contains_with_either_quotes(ops[0].code, '"value"')

    def test_parse_multiple_mutations(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["x"] = 1
                p["y"] = 2
                p["z"] = 3
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        mutations = [op for op in ops if isinstance(op, Mutation)]
        assert len(mutations) == 3
        assert contains_with_either_quotes(mutations[0].code, 'p["x"]')
        assert contains_with_either_quotes(mutations[1].code, 'p["y"]')
        assert contains_with_either_quotes(mutations[2].code, 'p["z"]')

    def test_parse_nested_subscript_assignment(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["nested"]["key"] = "value"
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], Mutation)
        assert contains_with_either_quotes(ops[0].code, 'p["nested"]["key"]')

    def test_parse_augmented_assignment(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["counter"] += 1
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], Mutation)
        assert contains_with_either_quotes(ops[0].code, 'p["counter"]')
        assert "+=" in ops[0].code

    def test_parse_various_augmented_assignments(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["a"] += 1
                p["b"] -= 2
                p["c"] *= 3
                p["d"] //= 4
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        mutations = [op for op in ops if isinstance(op, Mutation)]
        assert len(mutations) == 4
        assert all(isinstance(m, Mutation) for m in mutations)

    def test_parse_mutation_with_expression(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["result"] = p["x"] + p["y"] * 2
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], Mutation)
        assert contains_with_either_quotes(ops[0].code, 'p["result"]')


class TestConditionalParsing:
    """Test parsing of if/elif/else statements."""

    def test_parse_simple_if_else(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["condition"]:
                    p = handler_a(p)
                else:
                    p = handler_b(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 2
        assert isinstance(ops[0], Condition)
        assert contains_with_either_quotes(ops[0].test, 'p["condition"]')
        assert len(ops[0].true_branch) == 1
        assert len(ops[0].false_branch) == 1
        assert isinstance(ops[0].true_branch[0], ActorCall)
        assert isinstance(ops[0].false_branch[0], ActorCall)

    def test_parse_if_without_else(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["flag"]:
                    p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], Condition)
        assert len(ops[0].true_branch) == 1
        assert len(ops[0].false_branch) == 0

    def test_parse_if_elif_else(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["x"] == "A":
                    p = handler_a(p)
                elif p["x"] == "B":
                    p = handler_b(p)
                else:
                    p = handler_c(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], Condition)
        assert contains_with_either_quotes(ops[0].test, 'p["x"] == "A"')
        assert len(ops[0].true_branch) == 1
        assert len(ops[0].false_branch) == 1
        assert isinstance(ops[0].false_branch[0], Condition)

    def test_parse_nested_if(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["outer"]:
                    if p["inner"]:
                        p = handler_a(p)
                    else:
                        p = handler_b(p)
                else:
                    p = handler_c(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], Condition)
        assert contains_with_either_quotes(ops[0].test, 'p["outer"]')
        assert len(ops[0].true_branch) == 1
        assert isinstance(ops[0].true_branch[0], Condition)
        assert contains_with_either_quotes(ops[0].true_branch[0].test, 'p["inner"]')

    def test_parse_if_with_mutations_in_branches(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["type"] == "A":
                    p["label"] = "A"
                    p = handler_a(p)
                else:
                    p["label"] = "B"
                    p = handler_b(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        cond = ops[0]
        assert isinstance(cond, Condition)
        assert len(cond.true_branch) == 2
        assert isinstance(cond.true_branch[0], Mutation)
        assert isinstance(cond.true_branch[1], ActorCall)
        assert len(cond.false_branch) == 2
        assert isinstance(cond.false_branch[0], Mutation)
        assert isinstance(cond.false_branch[1], ActorCall)

    def test_parse_empty_if_branches(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["skip"]:
                    pass
                else:
                    p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], Condition)
        cond = ops[0]
        assert len(cond.true_branch) == 0
        assert len(cond.false_branch) == 1

    def test_parse_complex_condition_expression(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["x"] > 10 and p["y"] < 20:
                    p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], Condition)
        cond = ops[0]
        assert ">" in cond.test and "<" in cond.test and "and" in cond.test


class TestMixedOperations:
    """Test combinations of operations."""

    def test_parse_mutations_before_handler(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["status"] = "processing"
                p["timestamp"] = 123
                p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 4
        assert isinstance(ops[0], Mutation)
        assert isinstance(ops[1], Mutation)
        assert isinstance(ops[2], ActorCall)
        assert isinstance(ops[3], Return)

    def test_parse_mutations_after_handler(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)
                p["status"] = "complete"
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], ActorCall)
        assert isinstance(ops[1], Mutation)

    def test_parse_handlers_and_mutations_interleaved(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["step"] = 1
                p = handler_a(p)
                p["step"] = 2
                p = handler_b(p)
                p["step"] = 3
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], Mutation)
        assert isinstance(ops[1], ActorCall)
        assert isinstance(ops[2], Mutation)
        assert isinstance(ops[3], ActorCall)
        assert isinstance(ops[4], Mutation)

    def test_parse_conditional_with_mutations_before(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["initialized"] = True
                if p["condition"]:
                    p = handler_a(p)
                else:
                    p = handler_b(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], Mutation)
        assert isinstance(ops[1], Condition)


class TestClassInstantiation:
    """Test class instantiation and method calls."""

    def test_class_instantiation_with_default_args(self):
        source = textwrap.dedent(
            """
            def flow(p: dict) -> dict:
                processor = MyProcessor()
                p = processor.process(p)
                return p
            """
        )
        parser = FlowParser(source, "test.py")
        flow_name, operations = parser.parse()

        assert flow_name == "flow"
        assert len(operations) == 2
        assert isinstance(operations[0], ActorCall)
        assert operations[0].name == "MyProcessor.process"
        assert isinstance(operations[1], Return)

    def test_class_instantiation_with_multiple_instances(self):
        source = textwrap.dedent(
            """
            def flow(p: dict) -> dict:
                preprocessor = Preprocessor()
                model = Model()
                p = preprocessor.clean(p)
                p = model.predict(p)
                return p
            """
        )
        parser = FlowParser(source, "test.py")
        flow_name, operations = parser.parse()

        assert len(operations) == 3
        assert isinstance(operations[0], ActorCall)
        assert operations[0].name == "Preprocessor.clean"
        assert isinstance(operations[1], ActorCall)
        assert operations[1].name == "Model.predict"
        assert isinstance(operations[2], Return)

    def test_class_instantiation_rejects_positional_args(self):
        source = textwrap.dedent(
            """
            def flow(p: dict) -> dict:
                processor = MyProcessor("arg1")
                p = processor.process(p)
                return p
            """
        )
        parser = FlowParser(source, "test.py")

        with pytest.raises(FlowCompileError) as exc:
            parser.parse()
        assert "only default arguments" in str(exc.value)
        assert "1 positional arguments" in str(exc.value)

    def test_class_instantiation_rejects_keyword_args(self):
        source = textwrap.dedent(
            """
            def flow(p: dict) -> dict:
                processor = MyProcessor(config="custom")
                p = processor.process(p)
                return p
            """
        )
        parser = FlowParser(source, "test.py")

        with pytest.raises(FlowCompileError) as exc:
            parser.parse()
        assert "only default arguments" in str(exc.value)
        assert "keyword arguments" in str(exc.value)

    def test_class_instantiation_with_function_calls_mixed(self):
        source = textwrap.dedent(
            """
            def flow(p: dict) -> dict:
                processor = Preprocessor()
                p = validator(p)
                p = processor.clean(p)
                p = normalizer(p)
                return p
            """
        )
        parser = FlowParser(source, "test.py")
        flow_name, operations = parser.parse()

        assert len(operations) == 4
        assert isinstance(operations[0], ActorCall)
        assert operations[0].name == "validator"
        assert isinstance(operations[1], ActorCall)
        assert operations[1].name == "Preprocessor.clean"
        assert isinstance(operations[2], ActorCall)
        assert operations[2].name == "normalizer"
        assert isinstance(operations[3], Return)

    def test_class_instantiation_multiple_args_rejects(self):
        source = textwrap.dedent(
            """
            def flow(p: dict) -> dict:
                processor = MyProcessor("arg1", "arg2", key="value")
                p = processor.process(p)
                return p
            """
        )
        parser = FlowParser(source, "test.py")

        with pytest.raises(FlowCompileError) as exc:
            parser.parse()
        assert "only default arguments" in str(exc.value)


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_parse_empty_flow(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 1
        assert isinstance(ops[0], Return)

    def test_rejects_multiple_assignment_targets(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p, q = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="Unsupported assignment target"):
            parser.parse()

    def test_rejects_unsupported_assignment_target(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                x = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="Unsupported assignment target"):
            parser.parse()

    def test_rejects_unsupported_statement(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                for item in items:
                    p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="Unsupported statement type"):
            parser.parse()

    def test_handles_syntax_error_gracefully(self):
        source = "def flow(p: dict) -> dict\n    return p"
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="Syntax error"):
            parser.parse()

    def test_parse_pass_statement(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                pass
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 1
        assert isinstance(ops[0], Return)

    def test_lineno_preserved_in_operations(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler_a(p)
                p["key"] = "value"
                if p["x"]:
                    p = handler_b(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert all(hasattr(op, "lineno") for op in ops)
        assert all(op.lineno > 0 for op in ops)


class TestComplexFlows:
    """Test complex real-world flow patterns."""

    def test_parse_deeply_nested_conditionals(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["l1"] == "A":
                    if p["l2"] == "X":
                        if p["l3"] == "1":
                            p = handler_a_x_1(p)
                        else:
                            p = handler_a_x_2(p)
                    else:
                        p = handler_a_y(p)
                else:
                    p = handler_b(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], Condition)
        assert isinstance(ops[0].true_branch[0], Condition)
        assert isinstance(ops[0].true_branch[0].true_branch[0], Condition)

    def test_parse_multiple_conditionals_sequential(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["check1"]:
                    p = handler_1(p)

                if p["check2"]:
                    p = handler_2(p)

                if p["check3"]:
                    p = handler_3(p)

                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        conditions = [op for op in ops if isinstance(op, Condition)]
        assert len(conditions) == 3

    def test_parse_early_return_pattern(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["early_exit"]:
                    return p
                p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], Condition)
        assert isinstance(ops[0].true_branch[0], Return)
        assert isinstance(ops[1], ActorCall)
        assert isinstance(ops[2], Return)

    def test_parse_all_empty_branches(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["noop"]:
                    pass
                else:
                    pass
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], Condition)
        cond = ops[0]
        assert len(cond.true_branch) == 0
        assert len(cond.false_branch) == 0
