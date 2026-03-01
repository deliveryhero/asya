"""Unit tests for flow parser."""

import textwrap

import pytest
from asya_cli.flow.errors import FlowCompileError
from asya_cli.flow.ir import ActorCall, Break, Condition, Continue, Mutation, Return, WhileLoop
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

    def test_accepts_flow_with_arbitrary_parameter_name(self):
        source = textwrap.dedent("""
            def my_flow(data: dict) -> dict:
                return data
        """)
        parser = FlowParser(source, "test.py")
        flow_name, _ = parser.parse()
        assert flow_name == "my_flow"

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

    def test_rejects_for_loop(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                for item in items:
                    p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="'for' loops are not supported"):
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


class TestWhileLoopParsing:
    """Test parsing of while loop statements."""

    def test_simple_while_with_condition(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                while p["i"] < 10:
                    p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 2
        assert isinstance(ops[0], WhileLoop)
        loop = ops[0]
        assert loop.test is not None
        assert contains_with_either_quotes(loop.test, 'p["i"] < 10')
        assert len(loop.body) == 1
        assert isinstance(loop.body[0], ActorCall)
        assert isinstance(ops[1], Return)

    def test_while_true(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                while True:
                    p = handler(p)
                    if p["done"]:
                        break
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], WhileLoop)
        loop = ops[0]
        assert loop.test is None
        assert len(loop.body) == 2
        assert isinstance(loop.body[0], ActorCall)
        assert isinstance(loop.body[1], Condition)
        assert isinstance(loop.body[1].true_branch[0], Break)

    def test_while_with_break(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                while p["i"] < 10:
                    p = handler(p)
                    if p["stop"]:
                        break
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], WhileLoop)
        loop = ops[0]
        cond = loop.body[1]
        assert isinstance(cond, Condition)
        assert isinstance(cond.true_branch[0], Break)

    def test_while_with_continue(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                while p["i"] < 10:
                    p["i"] += 1
                    if p["skip"]:
                        continue
                    p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], WhileLoop)
        loop = ops[0]
        assert isinstance(loop.body[0], Mutation)
        assert isinstance(loop.body[1], Condition)
        assert isinstance(loop.body[1].true_branch[0], Continue)
        assert isinstance(loop.body[2], ActorCall)

    def test_while_with_both_break_and_continue(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                while p["i"] < 10:
                    p["i"] += 1
                    if p["skip"]:
                        continue
                    p = handler(p)
                    if p["stop"]:
                        break
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        loop = ops[0]
        assert isinstance(loop, WhileLoop)
        assert len(loop.body) == 4
        assert isinstance(loop.body[0], Mutation)
        assert isinstance(loop.body[1], Condition)
        assert isinstance(loop.body[1].true_branch[0], Continue)
        assert isinstance(loop.body[2], ActorCall)
        assert isinstance(loop.body[3], Condition)
        assert isinstance(loop.body[3].true_branch[0], Break)

    def test_while_with_mutations_in_body(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                while p["i"] < 10:
                    p["i"] += 1
                    p["sum"] += p["i"]
                    p = handler(p)
                    p["processed"] = True
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        loop = ops[0]
        assert isinstance(loop, WhileLoop)
        assert isinstance(loop.body[0], Mutation)
        assert isinstance(loop.body[1], Mutation)
        assert isinstance(loop.body[2], ActorCall)
        assert isinstance(loop.body[3], Mutation)

    def test_while_with_if_in_body(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                while p["i"] < 10:
                    if p["type"] == "A":
                        p = handler_a(p)
                    else:
                        p = handler_b(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        loop = ops[0]
        assert isinstance(loop, WhileLoop)
        assert len(loop.body) == 1
        assert isinstance(loop.body[0], Condition)
        assert isinstance(loop.body[0].true_branch[0], ActorCall)
        assert isinstance(loop.body[0].false_branch[0], ActorCall)

    def test_nested_while_loops(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                while p["i"] < 10:
                    while p["j"] < 5:
                        p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        outer = ops[0]
        assert isinstance(outer, WhileLoop)
        inner = outer.body[0]
        assert isinstance(inner, WhileLoop)
        assert isinstance(inner.body[0], ActorCall)

    def test_while_with_code_before_and_after(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler_init(p)
                p["i"] = 0
                while p["i"] < 10:
                    p["i"] += 1
                    p = handler_process(p)
                p = handler_finalize(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "handler_init"
        assert isinstance(ops[1], Mutation)
        assert isinstance(ops[2], WhileLoop)
        assert isinstance(ops[3], ActorCall)
        assert ops[3].name == "handler_finalize"
        assert isinstance(ops[4], Return)

    def test_while_preserves_lineno(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                while p["i"] < 10:
                    p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], WhileLoop)
        assert ops[0].lineno == 3

    def test_break_preserves_lineno(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                while True:
                    if p["stop"]:
                        break
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], WhileLoop)
        loop = ops[0]
        assert isinstance(loop.body[0], Condition)
        brk = loop.body[0].true_branch[0]
        assert isinstance(brk, Break)
        assert brk.lineno == 5

    def test_continue_preserves_lineno(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                while True:
                    if p["skip"]:
                        continue
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], WhileLoop)
        loop = ops[0]
        assert isinstance(loop.body[0], Condition)
        cont = loop.body[0].true_branch[0]
        assert isinstance(cont, Continue)
        assert cont.lineno == 5

    def test_while_empty_body(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                while p["i"] < 10:
                    pass
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        loop = ops[0]
        assert isinstance(loop, WhileLoop)
        assert len(loop.body) == 0

    def test_while_with_complex_condition(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                while p["i"] < 10 and p["status"] != "done":
                    p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        loop = ops[0]
        assert isinstance(loop, WhileLoop)
        assert loop.test is not None
        assert "and" in loop.test
        assert "10" in loop.test

    def test_while_with_not_condition(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                while not p.get("done", False):
                    p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        loop = ops[0]
        assert isinstance(loop, WhileLoop)
        assert loop.test is not None
        assert "not" in loop.test

    def test_while_with_method_call_condition(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                while p.get("continue_flag", True):
                    p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        loop = ops[0]
        assert isinstance(loop, WhileLoop)
        assert loop.test is not None
        assert "get" in loop.test

    def test_while_with_return_in_body(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                while True:
                    p = handler(p)
                    if p["final"]:
                        return p
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        loop = ops[0]
        assert isinstance(loop, WhileLoop)
        cond = loop.body[1]
        assert isinstance(cond, Condition)
        assert isinstance(cond.true_branch[0], Return)


class TestWhileLoopErrors:
    """Test error handling for while loop parsing."""

    def test_break_outside_loop_rejected(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                break
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="'break' outside loop"):
            parser.parse()

    def test_continue_outside_loop_rejected(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                continue
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="'continue' outside loop"):
            parser.parse()

    def test_break_in_if_outside_loop_rejected(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["x"]:
                    break
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="'break' outside loop"):
            parser.parse()

    def test_continue_in_if_outside_loop_rejected(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["x"]:
                    continue
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="'continue' outside loop"):
            parser.parse()

    def test_while_else_rejected(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                while p["i"] < 10:
                    p = handler(p)
                else:
                    p = fallback(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="'else' clause on 'while' loops is not supported"):
            parser.parse()

    def test_for_loop_rejected_with_helpful_message(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                for i in range(10):
                    p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="'for' loops are not supported"):
            parser.parse()

    def test_break_ok_inside_nested_loop(self):
        """break inside a while loop nested inside an if is valid."""
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                while True:
                    if p["x"]:
                        break
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()
        assert isinstance(ops[0], WhileLoop)
        loop = ops[0]
        assert isinstance(loop.body[0], Condition)
        cond = loop.body[0]
        assert isinstance(cond.true_branch[0], Break)

    def test_continue_ok_inside_nested_if_in_loop(self):
        """continue inside an if inside a while is valid."""
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                while p["i"] < 10:
                    if p["skip"]:
                        continue
                    p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()
        assert isinstance(ops[0], WhileLoop)
        loop = ops[0]
        assert isinstance(loop.body[0], Condition)
        assert isinstance(loop.body[0].true_branch[0], Continue)

    def test_while_only_mutations_in_body(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                while p["i"] < 10:
                    p["i"] += 1
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        loop = ops[0]
        assert isinstance(loop, WhileLoop)
        assert len(loop.body) == 1
        assert isinstance(loop.body[0], Mutation)

    def test_while_with_class_method_in_body(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                processor = Processor()
                while p["i"] < 10:
                    p = processor.run(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], WhileLoop)
        loop = ops[0]
        assert isinstance(loop.body[0], ActorCall)
        assert "Processor.run" in loop.body[0].name


class TestAsyncFlowDetection:
    """Test detection of async flow functions."""

    def test_detects_async_flow_function(self):
        source = textwrap.dedent("""
            async def my_flow(p: dict) -> dict:
                return p
        """)
        parser = FlowParser(source, "test.py")
        flow_name, _ = parser.parse()
        assert flow_name == "my_flow"

    def test_detects_async_flow_with_payload_parameter(self):
        source = textwrap.dedent("""
            async def my_flow(payload: dict) -> dict:
                return payload
        """)
        parser = FlowParser(source, "test.py")
        flow_name, _ = parser.parse()
        assert flow_name == "my_flow"

    def test_detects_async_flow_with_state_parameter(self):
        source = textwrap.dedent("""
            async def my_flow(state: dict) -> dict:
                return state
        """)
        parser = FlowParser(source, "test.py")
        flow_name, _ = parser.parse()
        assert flow_name == "my_flow"

    def test_async_flow_skips_non_matching_functions(self):
        source = textwrap.dedent("""
            async def helper(x: int) -> int:
                return x

            async def my_flow(p: dict) -> dict:
                return p
        """)
        parser = FlowParser(source, "test.py")
        flow_name, _ = parser.parse()
        assert flow_name == "my_flow"

    def test_prefers_first_valid_function_sync_or_async(self):
        source = textwrap.dedent("""
            def sync_flow(p: dict) -> dict:
                return p

            async def async_flow(p: dict) -> dict:
                return p
        """)
        parser = FlowParser(source, "test.py")
        flow_name, _ = parser.parse()
        assert flow_name == "sync_flow"


class TestAwaitActorCallParsing:
    """Test parsing of await expressions as actor calls."""

    def test_parse_single_await_call(self):
        source = textwrap.dedent("""
            async def flow(p: dict) -> dict:
                p = await handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 2
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "handler"
        assert isinstance(ops[1], Return)

    def test_parse_sequential_await_calls(self):
        source = textwrap.dedent("""
            async def flow(p: dict) -> dict:
                p = await handler_a(p)
                p = await handler_b(p)
                p = await handler_c(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 4
        assert isinstance(ops[0], ActorCall) and ops[0].name == "handler_a"
        assert isinstance(ops[1], ActorCall) and ops[1].name == "handler_b"
        assert isinstance(ops[2], ActorCall) and ops[2].name == "handler_c"
        assert isinstance(ops[3], Return)

    def test_parse_await_with_conditionals(self):
        source = textwrap.dedent("""
            async def flow(p: dict) -> dict:
                p = await classifier(p)
                if p["type"] == "text":
                    p = await text_handler(p)
                else:
                    p = await fallback(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "classifier"
        assert isinstance(ops[1], Condition)
        assert isinstance(ops[1].true_branch[0], ActorCall)
        assert ops[1].true_branch[0].name == "text_handler"
        assert isinstance(ops[1].false_branch[0], ActorCall)
        assert ops[1].false_branch[0].name == "fallback"

    def test_parse_mixed_sync_and_await_calls(self):
        source = textwrap.dedent("""
            async def flow(p: dict) -> dict:
                p = sync_handler(p)
                p = await async_handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 3
        assert isinstance(ops[0], ActorCall) and ops[0].name == "sync_handler"
        assert isinstance(ops[1], ActorCall) and ops[1].name == "async_handler"

    def test_rejects_await_without_argument(self):
        source = textwrap.dedent("""
            async def flow(p: dict) -> dict:
                p = await handler()
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="must have exactly one argument"):
            parser.parse()


class TestParameterNamePreservation:
    """Test that arbitrary parameter names are preserved in generated code."""

    def test_ctx_parameter_preserved(self):
        source = textwrap.dedent("""
            def flow(ctx: dict) -> dict:
                ctx["key"] = "value"
                return ctx
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], Mutation)
        assert contains_with_either_quotes(ops[0].code, 'ctx["key"]')

    def test_data_parameter_preserved(self):
        source = textwrap.dedent("""
            def flow(data: dict) -> dict:
                data["status"] = "processing"
                return data
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], Mutation)
        assert contains_with_either_quotes(ops[0].code, 'data["status"]')

    def test_arbitrary_name_preserved(self):
        source = textwrap.dedent("""
            def flow(x: dict) -> dict:
                x["count"] = 42
                return x
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], Mutation)
        assert contains_with_either_quotes(ops[0].code, 'x["count"]')

    def test_state_mutations_preserved(self):
        source = textwrap.dedent("""
            def flow(state: dict) -> dict:
                state["key"] = "value"
                return state
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], Mutation)
        assert contains_with_either_quotes(ops[0].code, 'state["key"]')

    def test_state_conditions_preserved(self):
        source = textwrap.dedent("""
            def flow(state: dict) -> dict:
                if state["type"] == "A":
                    state = handler_a(state)
                else:
                    state = handler_b(state)
                return state
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], Condition)
        assert contains_with_either_quotes(ops[0].test, 'state["type"]')

    def test_state_augmented_assignment_preserved(self):
        source = textwrap.dedent("""
            def flow(state: dict) -> dict:
                state["counter"] += 1
                return state
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], Mutation)
        assert contains_with_either_quotes(ops[0].code, 'state["counter"]')

    def test_async_state_flow_fully_preserved(self):
        source = textwrap.dedent("""
            async def my_flow(state: dict) -> dict:
                state = await classifier(state)
                if state["content_type"] == "text":
                    state = await text_processor(state)
                else:
                    state = await generic_processor(state)
                return state
        """)
        parser = FlowParser(source, "test.py")
        flow_name, ops = parser.parse()

        assert flow_name == "my_flow"
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "classifier"
        assert isinstance(ops[1], Condition)
        assert contains_with_either_quotes(ops[1].test, 'state["content_type"]')
        assert isinstance(ops[1].true_branch[0], ActorCall)
        assert ops[1].true_branch[0].name == "text_processor"
        assert isinstance(ops[1].false_branch[0], ActorCall)
        assert ops[1].false_branch[0].name == "generic_processor"

    def test_payload_parameter_preserved(self):
        source = textwrap.dedent("""
            def flow(payload: dict) -> dict:
                payload["key"] = "value"
                return payload
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], Mutation)
        assert contains_with_either_quotes(ops[0].code, 'payload["key"]')


class TestIsAsyncFlag:
    """Test that parser tracks whether the flow is async."""

    def test_sync_flow_not_async(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                return p
        """)
        parser = FlowParser(source, "test.py")
        parser.parse()
        assert parser.is_async is False

    def test_async_flow_is_async(self):
        source = textwrap.dedent("""
            async def flow(p: dict) -> dict:
                return p
        """)
        parser = FlowParser(source, "test.py")
        parser.parse()
        assert parser.is_async is True


class TestExprStatementErrors:
    """Test descriptive errors for unsupported expression statements."""

    def test_yield_gives_descriptive_error(self):
        source = textwrap.dedent("""
            async def flow(p: dict) -> dict:
                while True:
                    yield p
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="'yield' is not supported in flow definitions.*ABI"):
            parser.parse()

    def test_async_for_gives_descriptive_error(self):
        source = textwrap.dedent("""
            async def flow(p: dict) -> dict:
                async for event in handler(p):
                    pass
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="'async for' is not supported in flow definitions.*transport-level"):
            parser.parse()

    def test_standalone_await_gives_descriptive_error(self):
        source = textwrap.dedent("""
            async def flow(p: dict) -> dict:
                await handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="standalone 'await' is not supported"):
            parser.parse()

    def test_standalone_call_gives_descriptive_error(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                print(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="standalone function call is not supported"):
            parser.parse()


class TestAssertStatement:
    """Test assert statement support."""

    def test_assert_compiles_to_mutation(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                assert p["valid"]
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()
        assert isinstance(ops[0], Mutation)
        assert "assert" in ops[0].code
        assert 'p["valid"]' in ops[0].code or "p['valid']" in ops[0].code

    def test_assert_with_message(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                assert p["count"] > 0, "count must be positive"
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()
        assert isinstance(ops[0], Mutation)
        assert "assert" in ops[0].code
        assert "count must be positive" in ops[0].code

    def test_assert_with_state_parameter_preserved(self):
        source = textwrap.dedent("""
            def flow(state: dict) -> dict:
                assert state["valid"], "validation failed"
                return state
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()
        assert isinstance(ops[0], Mutation)
        # state should be preserved
        assert 'state["valid"]' in ops[0].code or "state['valid']" in ops[0].code


class TestImportHandling:
    """Test import statement handling."""

    def test_module_level_import_allowed(self):
        source = textwrap.dedent("""
            import my_handlers

            def flow(p: dict) -> dict:
                p = my_handlers.process(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()
        assert len(ops) == 2  # ActorCall + Return

    def test_module_level_from_import_allowed(self):
        source = textwrap.dedent("""
            from my_handlers import validate, process

            def flow(p: dict) -> dict:
                p = validate(p)
                p = process(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()
        assert len(ops) == 3  # 2 ActorCalls + Return

    def test_import_inside_flow_body_rejected(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                import my_handlers
                p = my_handlers.process(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="imports are not allowed inside flow functions"):
            parser.parse()

    def test_from_import_inside_flow_body_rejected(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                from my_handlers import process
                p = process(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="imports are not allowed inside flow functions"):
            parser.parse()
