"""Unit tests for code generator."""

import ast
from typing import TYPE_CHECKING

import pytest
from asya_cli.flow.codegen import CodeGenerator
from asya_cli.flow.grouper import Router
from asya_cli.flow.ir import Condition, Mutation


if TYPE_CHECKING:
    pass


class TestCodeStructure:
    """Test overall generated code structure using AST analysis."""

    def test_generated_code_is_valid_python(self):
        routers = [
            Router(name="start_flow", lineno=0, true_branch_actors=["end_flow"]),
            Router(name="end_flow", lineno=999),
        ]
        code = CodeGenerator("flow", routers, "test.py").generate()

        try:
            ast.parse(code)
        except SyntaxError as e:
            pytest.fail(f"Generated code is not valid Python: {e}")

    def test_contains_all_router_functions(self):
        routers = [
            Router(name="start_flow", lineno=0, true_branch_actors=["handler_a", "end_flow"]),
            Router(name="end_flow", lineno=999),
        ]
        code = CodeGenerator("flow", routers, "test.py").generate()
        tree = ast.parse(code)

        func_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]

        assert "start_flow" in func_names
        assert "end_flow" in func_names
        assert "resolve" in func_names

    def test_functions_have_correct_signature(self):
        routers = [
            Router(name="start_flow", lineno=0, true_branch_actors=["end_flow"]),
            Router(name="end_flow", lineno=999),
        ]
        code = CodeGenerator("flow", routers, "test.py").generate()
        tree = ast.parse(code)

        funcs = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        router_funcs = [f for f in funcs if f.name in ["start_flow", "end_flow"]]

        for func in router_funcs:
            assert len(func.args.args) == 1
            assert func.args.args[0].arg == "message"

    def test_resolve_function_exists(self):
        routers = [Router(name="start_flow", lineno=0), Router(name="end_flow", lineno=999)]
        code = CodeGenerator("flow", routers, "test.py").generate()
        tree = ast.parse(code)

        resolve_funcs = [
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "resolve"
        ]

        assert len(resolve_funcs) == 1
        assert len(resolve_funcs[0].args.args) == 1


class TestStartRouter:
    """Test start router generation."""

    def test_start_router_has_correct_docstring(self):
        routers = [Router(name="start_my_flow", lineno=0), Router(name="end_my_flow", lineno=999)]
        code = CodeGenerator("my_flow", routers, "test.py")._generate_start_router(routers[0])

        assert "Entrypoint" in code
        assert "my_flow" in code

    def test_start_router_calls_resolve_for_actors(self):
        routers = [
            Router(name="start_flow", lineno=0, true_branch_actors=["handler_a", "handler_b", "end_flow"]),
        ]
        code = CodeGenerator("flow", routers, "test.py")._generate_start_router(routers[0])

        assert 'resolve("handler_a")' in code
        assert 'resolve("handler_b")' in code
        assert 'resolve("end_flow")' not in code

    def test_start_router_inserts_into_route(self):
        routers = [Router(name="start_flow", lineno=0, true_branch_actors=["handler", "end_flow"])]
        code = CodeGenerator("flow", routers, "test.py")._generate_start_router(routers[0])

        assert "r['actors'][c+1:c+1]" in code

    def test_start_router_handles_empty_actors(self):
        routers = [Router(name="start_flow", lineno=0, true_branch_actors=[])]
        code = CodeGenerator("flow", routers, "test.py")._generate_start_router(routers[0])

        tree = ast.parse(code)
        assert tree is not None


class TestEndRouter:
    """Test end router generation."""

    def test_end_router_has_correct_docstring(self):
        routers = [Router(name="end_my_flow", lineno=999)]
        code = CodeGenerator("my_flow", routers, "test.py")._generate_end_router(routers[0])

        assert "Exitpoint" in code
        assert "my_flow" in code

    def test_end_router_returns_message_unchanged(self):
        routers = [Router(name="end_flow", lineno=999)]
        code = CodeGenerator("flow", routers, "test.py")._generate_end_router(routers[0])

        assert "return message" in code
        assert "resolve(" not in code


class TestSequentialRouter:
    """Test sequential router generation (mutations + handlers)."""

    def test_sequential_router_has_mutations(self):
        routers = [
            Router(
                name="router_flow_line_1_seq",
                lineno=1,
                mutations=[Mutation(lineno=1, code='p["x"] = 1'), Mutation(lineno=2, code='p["y"] = 2')],
                true_branch_actors=["handler", "end_flow"],
            )
        ]
        code = CodeGenerator("flow", routers, "test.py")._generate_router(routers[0])

        assert 'p["x"] = 1' in code
        assert 'p["y"] = 2' in code

    def test_sequential_router_appends_actors_to_next(self):
        routers = [
            Router(
                name="router_flow_line_1_seq",
                lineno=1,
                mutations=[],
                true_branch_actors=["handler_a", "handler_b"],
            )
        ]
        code = CodeGenerator("flow", routers, "test.py")._generate_router(routers[0])

        assert '_next.append(resolve("handler_a"))' in code
        assert '_next.append(resolve("handler_b"))' in code

    def test_sequential_router_inserts_into_route(self):
        routers = [Router(name="router_flow_line_1_seq", lineno=1, true_branch_actors=["handler"])]
        code = CodeGenerator("flow", routers, "test.py")._generate_router(routers[0])

        assert "r['actors'][c+1:c+1] = _next" in code


class TestConditionalRouter:
    """Test conditional router generation."""

    def test_conditional_router_has_if_statement(self):
        routers = [
            Router(
                name="router_flow_line_1_if",
                lineno=1,
                condition=Condition(lineno=1, test='p["x"]', true_branch=[], false_branch=[]),
                true_branch_actors=["handler_a"],
                false_branch_actors=["handler_b"],
            )
        ]
        code = CodeGenerator("flow", routers, "test.py")._generate_router(routers[0])
        tree = ast.parse(code)

        if_stmts = [node for node in ast.walk(tree) if isinstance(node, ast.If)]
        assert len(if_stmts) > 0

    def test_conditional_router_uses_condition_test(self):
        routers = [
            Router(
                name="router_flow_line_1_if",
                lineno=1,
                condition=Condition(lineno=1, test='p["type"] == "A"', true_branch=[], false_branch=[]),
                true_branch_actors=["handler_a"],
                false_branch_actors=["handler_b"],
            )
        ]
        code = CodeGenerator("flow", routers, "test.py")._generate_router(routers[0])

        assert 'if p["type"] == "A":' in code

    def test_conditional_router_populates_true_branch(self):
        routers = [
            Router(
                name="router_flow_line_1_if",
                lineno=1,
                condition=Condition(lineno=1, test='p["x"]', true_branch=[], false_branch=[]),
                true_branch_actors=["handler_a", "handler_b"],
                false_branch_actors=[],
            )
        ]
        code = CodeGenerator("flow", routers, "test.py")._generate_router(routers[0])

        assert '_next.append(resolve("handler_a"))' in code
        assert '_next.append(resolve("handler_b"))' in code

    def test_conditional_router_populates_false_branch(self):
        routers = [
            Router(
                name="router_flow_line_1_if",
                lineno=1,
                condition=Condition(lineno=1, test='p["x"]', true_branch=[], false_branch=[]),
                true_branch_actors=[],
                false_branch_actors=["handler_c", "handler_d"],
            )
        ]
        code = CodeGenerator("flow", routers, "test.py")._generate_router(routers[0])

        assert '_next.append(resolve("handler_c"))' in code
        assert '_next.append(resolve("handler_d"))' in code

    def test_conditional_router_with_empty_true_branch_uses_pass(self):
        routers = [
            Router(
                name="router_flow_line_1_if",
                lineno=1,
                condition=Condition(lineno=1, test='p["x"]', true_branch=[], false_branch=[]),
                true_branch_actors=[],
                false_branch_actors=["handler"],
            )
        ]
        code = CodeGenerator("flow", routers, "test.py")._generate_router(routers[0])

        lines = code.split("\n")
        if_block = False
        for line in lines:
            if 'if p["x"]:' in line:
                if_block = True
            elif if_block and "else:" in line:
                break
            elif if_block and "pass" in line:
                assert True
                return

        pytest.fail("Expected pass statement in empty true branch")

    def test_conditional_router_with_empty_false_branch_uses_pass(self):
        routers = [
            Router(
                name="router_flow_line_1_if",
                lineno=1,
                condition=Condition(lineno=1, test='p["x"]', true_branch=[], false_branch=[]),
                true_branch_actors=["handler"],
                false_branch_actors=[],
            )
        ]
        code = CodeGenerator("flow", routers, "test.py")._generate_router(routers[0])

        lines = code.split("\n")
        else_block = False
        for line in lines:
            if "else:" in line:
                else_block = True
            elif else_block and "pass" in line:
                assert True
                return

        pytest.fail("Expected pass statement in empty false branch")

    def test_conditional_router_with_mutations(self):
        routers = [
            Router(
                name="router_flow_line_1_if",
                lineno=1,
                mutations=[Mutation(lineno=1, code='p["status"] = "init"')],
                condition=Condition(lineno=2, test='p["x"]', true_branch=[], false_branch=[]),
                true_branch_actors=["handler_a"],
                false_branch_actors=["handler_b"],
            )
        ]
        code = CodeGenerator("flow", routers, "test.py")._generate_router(routers[0])

        lines = code.split("\n")
        mutation_line = None
        if_line = None

        for i, line in enumerate(lines):
            if 'p["status"] = "init"' in line:
                mutation_line = i
            if 'if p["x"]:' in line:
                if_line = i

        assert mutation_line is not None
        assert if_line is not None
        assert mutation_line < if_line


class TestHandlerCollection:
    """Test handler collection from routers."""

    def test_collects_handlers_from_true_branch(self):
        routers = [Router(name="start_flow", lineno=0, true_branch_actors=["handler_a", "handler_b"])]
        generator = CodeGenerator("flow", routers, "test.py")
        generator._collect_handlers()

        assert "handler_a" in generator.all_handlers
        assert "handler_b" in generator.all_handlers

    def test_collects_handlers_from_false_branch(self):
        routers = [Router(name="router_if", lineno=1, false_branch_actors=["handler_c", "handler_d"])]
        generator = CodeGenerator("flow", routers, "test.py")
        generator._collect_handlers()

        assert "handler_c" in generator.all_handlers
        assert "handler_d" in generator.all_handlers

    def test_collects_router_names_as_handlers(self):
        routers = [
            Router(name="start_flow", lineno=0),
            Router(name="router_flow_line_1_if", lineno=1),
            Router(name="end_flow", lineno=999),
        ]
        generator = CodeGenerator("flow", routers, "test.py")
        generator._collect_handlers()

        assert "start_flow" in generator.all_handlers
        assert "router_flow_line_1_if" in generator.all_handlers
        assert "end_flow" in generator.all_handlers

    def test_deduplicates_handlers(self):
        routers = [
            Router(name="start_flow", lineno=0, true_branch_actors=["handler", "handler", "handler"]),
        ]
        generator = CodeGenerator("flow", routers, "test.py")
        generator._collect_handlers()

        handler_count = sum(1 for h in generator.all_handlers if h == "handler")
        assert handler_count == 1


class TestHeaderGeneration:
    """Test header generation."""

    def test_header_includes_source_file(self):
        routers = [Router(name="start_flow", lineno=0), Router(name="end_flow", lineno=999)]
        code = CodeGenerator("flow", routers, "/path/to/my_flow.py")._generate_header()

        assert "my_flow.py" in code

    def test_header_includes_warning(self):
        routers = [Router(name="start_flow", lineno=0), Router(name="end_flow", lineno=999)]
        code = CodeGenerator("flow", routers, "test.py")._generate_header()

        assert "DO NOT EDIT" in code


class TestComplexRouters:
    """Test complex router combinations."""

    def test_multiple_routers_in_sequence(self):
        routers = [
            Router(name="start_flow", lineno=0, true_branch_actors=["router_1", "end_flow"]),
            Router(name="router_1", lineno=1, true_branch_actors=["handler_a"]),
            Router(name="end_flow", lineno=999),
        ]
        code = CodeGenerator("flow", routers, "test.py").generate()
        tree = ast.parse(code)

        func_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]

        assert "start_flow" in func_names
        assert "router_1" in func_names
        assert "end_flow" in func_names

    def test_nested_conditional_routers(self):
        routers = [
            Router(
                name="router_outer",
                lineno=1,
                condition=Condition(lineno=1, test='p["outer"]', true_branch=[], false_branch=[]),
                true_branch_actors=["router_inner"],
                false_branch_actors=["handler_b"],
            ),
            Router(
                name="router_inner",
                lineno=2,
                condition=Condition(lineno=2, test='p["inner"]', true_branch=[], false_branch=[]),
                true_branch_actors=["handler_a"],
                false_branch_actors=["handler_c"],
            ),
        ]
        code = CodeGenerator("flow", routers, "test.py").generate()

        assert 'if p["outer"]:' in code
        assert 'if p["inner"]:' in code
        assert 'resolve("router_inner")' in code

    def test_router_with_multiple_mutations_and_condition(self):
        routers = [
            Router(
                name="router_complex",
                lineno=1,
                mutations=[
                    Mutation(lineno=1, code='p["status"] = "processing"'),
                    Mutation(lineno=2, code='p["timestamp"] = 123'),
                    Mutation(lineno=3, code='p["counter"] += 1'),
                ],
                condition=Condition(lineno=4, test='p["type"] == "A"', true_branch=[], false_branch=[]),
                true_branch_actors=["handler_a", "handler_b"],
                false_branch_actors=["handler_c"],
            )
        ]
        code = CodeGenerator("flow", routers, "test.py")._generate_router(routers[0])

        assert 'p["status"] = "processing"' in code
        assert 'p["timestamp"] = 123' in code
        assert 'p["counter"] += 1' in code
        assert 'if p["type"] == "A":' in code


class TestEdgeCases:
    """Test edge cases."""

    def test_empty_routers_list(self):
        routers: list[Router] = []
        code = CodeGenerator("flow", routers, "test.py").generate()

        tree = ast.parse(code)
        assert tree is not None

    def test_router_with_special_characters_in_name(self):
        routers = [Router(name="router_flow_line_10_if", lineno=10)]
        code = CodeGenerator("flow", routers, "test.py")._generate_router(routers[0])

        assert "def router_flow_line_10_if(message: dict) -> dict:" in code

    def test_very_long_actor_list(self):
        actors = [f"handler_{i}" for i in range(50)]
        routers = [Router(name="start_flow", lineno=0, true_branch_actors=actors)]
        code = CodeGenerator("flow", routers, "test.py")._generate_start_router(routers[0])

        for actor in actors:
            assert f'resolve("{actor}")' in code

    def test_mutation_with_complex_expression(self):
        routers = [
            Router(
                name="router_mutation",
                lineno=1,
                mutations=[Mutation(lineno=1, code='p["result"] = p["x"] + p["y"] * 2 if p["flag"] else p["z"]')],
            )
        ]
        code = CodeGenerator("flow", routers, "test.py")._generate_router(routers[0])

        assert 'p["result"] = p["x"] + p["y"] * 2 if p["flag"] else p["z"]' in code

    def test_condition_with_complex_boolean_expression(self):
        routers = [
            Router(
                name="router_complex_cond",
                lineno=1,
                condition=Condition(
                    lineno=1,
                    test='p["x"] > 10 and p["y"] < 20 or p["z"] == "special"',
                    true_branch=[],
                    false_branch=[],
                ),
                true_branch_actors=["handler"],
                false_branch_actors=[],
            )
        ]
        code = CodeGenerator("flow", routers, "test.py")._generate_router(routers[0])

        assert 'if p["x"] > 10 and p["y"] < 20 or p["z"] == "special":' in code
