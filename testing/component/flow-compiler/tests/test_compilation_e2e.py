"""End-to-end compilation tests for flow compiler."""

import textwrap

import pytest

from asya_cli.flow import FlowCompiler
from asya_cli.flow.errors import FlowCompileError


class TestMinimalFlows:
    """Test compilation of minimal flow patterns."""

    def test_empty_flow(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        assert len(compiler.routers) == 2
        assert compiler.routers[0].name.startswith("start_")
        assert compiler.routers[-1].name.startswith("end_")

    def test_single_handler(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)
                return p

            def handler(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        start = compiler.routers[0]
        end = compiler.routers[-1]

        assert "handler" in start.true_branch_actors
        assert end.name in start.true_branch_actors

    def test_single_mutation(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["key"] = "value"
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        mutation_routers = [r for r in compiler.routers if len(r.mutations) > 0]
        assert len(mutation_routers) == 1
        assert "p['key']" in mutation_routers[0].mutations[0].code or 'p["key"]' in mutation_routers[0].mutations[0].code


class TestSequentialFlows:
    """Test compilation of sequential operations."""

    def test_multiple_handlers_sequential(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler_a(p)
                p = handler_b(p)
                p = handler_c(p)
                return p

            def handler_a(p: dict) -> dict:
                return p
            def handler_b(p: dict) -> dict:
                return p
            def handler_c(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        start = compiler.routers[0]
        assert "handler_a" in start.true_branch_actors
        assert "handler_b" in start.true_branch_actors
        assert "handler_c" in start.true_branch_actors

    def test_mutations_only(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["x"] = 1
                p["y"] = 2
                p["z"] = 3
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        mutation_routers = [r for r in compiler.routers if len(r.mutations) > 0]
        assert len(mutation_routers[0].mutations) == 3

    def test_mutations_with_handler(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["status"] = "init"
                p["timestamp"] = 123
                p = handler(p)
                return p

            def handler(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        mutation_routers = [r for r in compiler.routers if len(r.mutations) > 0]
        assert len(mutation_routers) == 1
        assert len(mutation_routers[0].mutations) == 2
        assert "handler" in mutation_routers[0].true_branch_actors


class TestSimpleConditionals:
    """Test compilation of simple if/else statements."""

    def test_if_else_simple(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["type"] == "A":
                    p = handler_a(p)
                else:
                    p = handler_b(p)
                return p

            def handler_a(p: dict) -> dict:
                return p
            def handler_b(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        cond_routers = [r for r in compiler.routers if r.condition is not None]
        assert len(cond_routers) == 1

        router = cond_routers[0]
        assert "p['type'] == 'A'" in router.condition.test or 'p["type"] == "A"' in router.condition.test
        assert "handler_a" in router.true_branch_actors
        assert "handler_b" in router.false_branch_actors

    def test_if_no_else(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["flag"]:
                    p = handler(p)
                return p

            def handler(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        cond_router = [r for r in compiler.routers if r.condition is not None][0]
        assert "handler" in cond_router.true_branch_actors
        assert "end_flow" in cond_router.false_branch_actors

    def test_if_elif_else(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["x"] == "A":
                    p = handler_a(p)
                elif p["x"] == "B":
                    p = handler_b(p)
                else:
                    p = handler_c(p)
                return p

            def handler_a(p: dict) -> dict:
                return p
            def handler_b(p: dict) -> dict:
                return p
            def handler_c(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        cond_routers = [r for r in compiler.routers if r.condition is not None]
        assert len(cond_routers) >= 1

    def test_empty_branches(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["skip"]:
                    pass
                else:
                    pass
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        cond_router = [r for r in compiler.routers if r.condition is not None][0]
        assert "end_flow" in cond_router.true_branch_actors
        assert "end_flow" in cond_router.false_branch_actors


class TestConditionalWithMutations:
    """Test conditionals combined with mutations."""

    def test_mutations_in_branches(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["type"] == "A":
                    p["label"] = "A"
                    p = handler_a(p)
                else:
                    p["label"] = "B"
                    p = handler_b(p)
                return p

            def handler_a(p: dict) -> dict:
                return p
            def handler_b(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        mutation_routers = [r for r in compiler.routers if len(r.mutations) > 0]
        assert len(mutation_routers) >= 2

    def test_mutations_before_conditional(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["initialized"] = True
                if p["condition"]:
                    p = handler_a(p)
                else:
                    p = handler_b(p)
                return p

            def handler_a(p: dict) -> dict:
                return p
            def handler_b(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        cond_router = [r for r in compiler.routers if r.condition is not None][0]
        assert len(cond_router.mutations) == 1

    def test_mutations_after_conditional(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["condition"]:
                    p = handler_a(p)
                else:
                    p = handler_b(p)
                p["finalized"] = True
                return p

            def handler_a(p: dict) -> dict:
                return p
            def handler_b(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        mutation_routers = [r for r in compiler.routers if len(r.mutations) > 0]
        assert any(len(r.mutations) > 0 for r in compiler.routers)


class TestNestedConditionals:
    """Test nested conditional structures."""

    def test_nested_if_in_true_branch(self):
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

            def handler_a(p: dict) -> dict:
                return p
            def handler_b(p: dict) -> dict:
                return p
            def handler_c(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        cond_routers = [r for r in compiler.routers if r.condition is not None]
        assert len(cond_routers) == 2

    def test_deeply_nested(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["l1"] == "A":
                    if p["l2"] == "X":
                        if p["l3"] == "1":
                            p = handler_deep(p)
                return p

            def handler_deep(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        cond_routers = [r for r in compiler.routers if r.condition is not None]
        assert len(cond_routers) == 3


class TestConvergence:
    """Test branch convergence behavior."""

    def test_branches_converge_to_handler(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["condition"]:
                    p = handler_a(p)
                else:
                    p = handler_b(p)
                p = final_handler(p)
                return p

            def handler_a(p: dict) -> dict:
                return p
            def handler_b(p: dict) -> dict:
                return p
            def final_handler(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        cond_router = [r for r in compiler.routers if r.condition is not None][0]
        assert "final_handler" in cond_router.true_branch_actors
        assert "final_handler" in cond_router.false_branch_actors

    def test_nested_branches_converge(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["outer"]:
                    if p["inner"]:
                        p = handler_a(p)
                    else:
                        p = handler_b(p)
                else:
                    p = handler_c(p)
                p = final(p)
                return p

            def handler_a(p: dict) -> dict:
                return p
            def handler_b(p: dict) -> dict:
                return p
            def handler_c(p: dict) -> dict:
                return p
            def final(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        all_branches = []
        for router in compiler.routers:
            all_branches.extend(router.true_branch_actors)
            all_branches.extend(router.false_branch_actors)

        assert "final" in all_branches


class TestEarlyReturn:
    """Test early return patterns."""

    def test_early_return_in_branch(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["early_exit"]:
                    return p
                p = handler(p)
                return p

            def handler(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        cond_router = [r for r in compiler.routers if r.condition is not None][0]
        assert "end_flow" in cond_router.true_branch_actors
        assert "handler" in cond_router.false_branch_actors


class TestComplexPatterns:
    """Test complex real-world patterns."""

    def test_preprocessing_conditional_postprocessing(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["status"] = "processing"
                p = preprocess(p)

                if p["type"] == "A":
                    p["route"] = "A"
                    p = handler_a(p)
                elif p["type"] == "B":
                    p["route"] = "B"
                    p = handler_b(p)
                else:
                    p["route"] = "default"
                    p = handler_default(p)

                p = postprocess(p)
                p["status"] = "complete"
                return p

            def preprocess(p: dict) -> dict:
                return p
            def handler_a(p: dict) -> dict:
                return p
            def handler_b(p: dict) -> dict:
                return p
            def handler_default(p: dict) -> dict:
                return p
            def postprocess(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        assert any("preprocess" in r.true_branch_actors for r in compiler.routers)
        assert any("postprocess" in r.true_branch_actors or "postprocess" in r.false_branch_actors for r in compiler.routers)
        assert any(r.condition is not None for r in compiler.routers)

    def test_multiple_sequential_conditionals(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["check1"]:
                    p = handler_1(p)

                if p["check2"]:
                    p = handler_2(p)

                if p["check3"]:
                    p = handler_3(p)

                return p

            def handler_1(p: dict) -> dict:
                return p
            def handler_2(p: dict) -> dict:
                return p
            def handler_3(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        cond_routers = [r for r in compiler.routers if r.condition is not None]
        assert len(cond_routers) == 3


class TestErrorCases:
    """Test compilation error handling."""

    def test_invalid_syntax(self):
        source = "def flow(p: dict) -> dict\n    return p"

        compiler = FlowCompiler()
        with pytest.raises(FlowCompileError, match="Syntax error"):
            compiler.compile(source, "test.py")

    def test_no_flow_function(self):
        source = textwrap.dedent("""
            def helper(x: int) -> int:
                return x
        """)

        compiler = FlowCompiler()
        with pytest.raises(FlowCompileError, match="No flow function found"):
            compiler.compile(source, "test.py")

    def test_invalid_handler_call(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler()
                return p
        """)

        compiler = FlowCompiler()
        with pytest.raises(FlowCompileError, match="must have exactly one argument"):
            compiler.compile(source, "test.py")


class TestCodeGeneration:
    """Test that compilation produces valid executable code."""

    def test_generated_code_is_valid_python(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)
                return p

            def handler(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        try:
            compile(code, "test.py", "exec")
        except SyntaxError as e:
            pytest.fail(f"Generated code has syntax errors: {e}")

    def test_generated_code_contains_all_functions(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler_a(p)
                p = handler_b(p)
                return p

            def handler_a(p: dict) -> dict:
                return p
            def handler_b(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        assert "def start_flow" in code
        assert "def end_flow" in code
        assert "def resolve" in code
