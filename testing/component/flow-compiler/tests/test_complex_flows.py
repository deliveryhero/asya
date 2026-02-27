"""Test complex real-world flow patterns."""

import textwrap
from pathlib import Path
import pytest

from asya_cli.flow import FlowCompiler


class TestExampleFlows:
    """Test compilation of example flows from examples/flows/."""

    @pytest.mark.parametrize("flow_file,expected_min_routers", [
        ("minimal.py", 2),
        ("sequential.py", 2),
        ("mutations_only.py", 2),
        ("mutations_with_handler.py", 3),
        ("if_no_else.py", 3),
        ("if_else_simple.py", 3),
        ("if_elif_else.py", 3),
        ("nested_if.py", 3),
        ("early_return.py", 3),
    ])
    def test_example_flow_compiles(self, project_root: Path, flow_file, expected_min_routers):
        flow_path = project_root / "examples/flows" / flow_file

        if not flow_path.exists():
            pytest.skip(f"Example file not found: {flow_path}")

        compiler = FlowCompiler()
        source = flow_path.read_text()
        compiler.compile(source, str(flow_path))

        assert len(compiler.routers) >= expected_min_routers
        assert any(r.name.startswith("start_") for r in compiler.routers)
        assert any(r.name.startswith("end_") for r in compiler.routers)

    def test_01_minimal_structure(self, project_root: Path):
        flow_path = project_root / "examples/flows/01_minimal.py"
        if not flow_path.exists():
            pytest.skip("Example file not found")

        compiler = FlowCompiler()
        source = flow_path.read_text()
        compiler.compile(source, str(flow_path))

        start = compiler.routers[0]
        end = compiler.routers[-1]

        assert "handler_a" in start.true_branch_actors
        assert end.name in start.true_branch_actors

    def test_06_if_else_simple_structure(self, project_root: Path):
        flow_path = project_root / "examples/flows/06_if_else_simple.py"
        if not flow_path.exists():
            pytest.skip("Example file not found")

        compiler = FlowCompiler()
        source = flow_path.read_text()
        compiler.compile(source, str(flow_path))

        cond_routers = [r for r in compiler.routers if r.condition is not None]
        assert len(cond_routers) >= 1

        router = cond_routers[0]
        assert "handler_type_a" in str(router.true_branch_actors)
        assert "handler_type_b" in str(router.false_branch_actors)
        assert "handler_finalize" in str(router.true_branch_actors)
        assert "handler_finalize" in str(router.false_branch_actors)

    def test_10_nested_if_structure(self, project_root: Path):
        flow_path = project_root / "examples/flows/10_nested_if.py"
        if not flow_path.exists():
            pytest.skip("Example file not found")

        compiler = FlowCompiler()
        source = flow_path.read_text()
        compiler.compile(source, str(flow_path))

        cond_routers = [r for r in compiler.routers if r.condition is not None]
        assert len(cond_routers) >= 2

        all_branches = []
        for r in cond_routers:
            all_branches.extend(r.true_branch_actors)
            all_branches.extend(r.false_branch_actors)

        assert "handler_finalize" in all_branches or any("finalize" in str(b) for b in all_branches)


class TestMultiLayerNesting:
    """Test deep nesting scenarios."""

    def test_three_level_nesting(self):
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

            def handler_a_x_1(p: dict) -> dict:
                return p
            def handler_a_x_2(p: dict) -> dict:
                return p
            def handler_a_y(p: dict) -> dict:
                return p
            def handler_b(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        cond_routers = [r for r in compiler.routers if r.condition is not None]
        assert len(cond_routers) == 3

    def test_nested_with_mutations_at_each_level(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["level"] = 0
                if p["l1"]:
                    p["level"] = 1
                    if p["l2"]:
                        p["level"] = 2
                        if p["l3"]:
                            p["level"] = 3
                            p = handler_deep(p)
                return p

            def handler_deep(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        mutation_routers = [r for r in compiler.routers if len(r.mutations) > 0]
        assert len(mutation_routers) >= 3


class TestComplexConvergence:
    """Test complex convergence scenarios."""

    def test_diamond_pattern(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = start_handler(p)
                if p["condition"]:
                    p = left_handler(p)
                else:
                    p = right_handler(p)
                p = end_handler(p)
                return p

            def start_handler(p: dict) -> dict:
                return p
            def left_handler(p: dict) -> dict:
                return p
            def right_handler(p: dict) -> dict:
                return p
            def end_handler(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        start = compiler.routers[0]
        assert "start_handler" in start.true_branch_actors

        cond_router = [r for r in compiler.routers if r.condition is not None][0]
        assert "end_handler" in cond_router.true_branch_actors
        assert "end_handler" in cond_router.false_branch_actors

    def test_multiple_convergence_points(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["first"]:
                    p = handler_1a(p)
                else:
                    p = handler_1b(p)
                p = middle_handler(p)

                if p["second"]:
                    p = handler_2a(p)
                else:
                    p = handler_2b(p)
                p = final_handler(p)
                return p

            def handler_1a(p: dict) -> dict:
                return p
            def handler_1b(p: dict) -> dict:
                return p
            def middle_handler(p: dict) -> dict:
                return p
            def handler_2a(p: dict) -> dict:
                return p
            def handler_2b(p: dict) -> dict:
                return p
            def final_handler(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        cond_routers = [r for r in compiler.routers if r.condition is not None]
        assert len(cond_routers) == 2

        all_branches = []
        for r in compiler.routers:
            all_branches.extend(r.true_branch_actors)
            all_branches.extend(r.false_branch_actors)

        assert "middle_handler" in all_branches
        assert "final_handler" in all_branches


class TestComplexMutations:
    """Test complex mutation patterns."""

    def test_mutations_with_expressions(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["sum"] = p["a"] + p["b"]
                p["product"] = p["a"] * p["b"]
                p["result"] = p["sum"] if p["flag"] else p["product"]
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        mutation_router = [r for r in compiler.routers if len(r.mutations) > 0][0]
        assert len(mutation_router.mutations) == 3

    def test_augmented_assignments(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["counter"] += 1
                p["total"] *= 2
                p["value"] -= 5
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        mutation_router = [r for r in compiler.routers if len(r.mutations) > 0][0]
        assert len(mutation_router.mutations) == 3

    def test_nested_subscripts(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["data"]["nested"]["value"] = 42
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        mutation_router = [r for r in compiler.routers if len(r.mutations) > 0][0]
        assert "p['data']['nested']['value']" in mutation_router.mutations[0].code or 'p["data"]["nested"]["value"]' in mutation_router.mutations[0].code


class TestComplexConditionals:
    """Test complex conditional logic."""

    def test_multiple_elif_chains(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["type"] == "A":
                    p = handler_a(p)
                elif p["type"] == "B":
                    p = handler_b(p)
                elif p["type"] == "C":
                    p = handler_c(p)
                elif p["type"] == "D":
                    p = handler_d(p)
                else:
                    p = handler_default(p)
                return p

            def handler_a(p: dict) -> dict:
                return p
            def handler_b(p: dict) -> dict:
                return p
            def handler_c(p: dict) -> dict:
                return p
            def handler_d(p: dict) -> dict:
                return p
            def handler_default(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        cond_routers = [r for r in compiler.routers if r.condition is not None]
        assert len(cond_routers) >= 4

    def test_complex_boolean_expressions(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if (p["x"] > 10 and p["y"] < 20) or (p["z"] == "special" and p["flag"]):
                    p = handler_match(p)
                else:
                    p = handler_no_match(p)
                return p

            def handler_match(p: dict) -> dict:
                return p
            def handler_no_match(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        cond_router = [r for r in compiler.routers if r.condition is not None][0]
        assert "and" in cond_router.condition.test
        assert "or" in cond_router.condition.test


class TestMixedPatterns:
    """Test combinations of all features."""

    def test_preprocessing_pipeline(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["status"] = "init"
                p = validate(p)
                p["validated"] = True

                if p["valid"]:
                    p["route"] = "processing"
                    p = preprocess(p)

                    if p["type"] == "A":
                        p["handler"] = "A"
                        p = handler_a(p)
                    else:
                        p["handler"] = "B"
                        p = handler_b(p)

                    p = postprocess(p)
                    p["processed"] = True
                else:
                    p["route"] = "rejected"
                    p = reject_handler(p)

                p["status"] = "complete"
                return p

            def validate(p: dict) -> dict:
                return p
            def preprocess(p: dict) -> dict:
                return p
            def handler_a(p: dict) -> dict:
                return p
            def handler_b(p: dict) -> dict:
                return p
            def postprocess(p: dict) -> dict:
                return p
            def reject_handler(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        assert len(compiler.routers) >= 3
        assert any(r.condition is not None for r in compiler.routers)
        assert any(len(r.mutations) > 0 for r in compiler.routers)

        all_handlers = set()
        for r in compiler.routers:
            all_handlers.update(r.true_branch_actors)
            all_handlers.update(r.false_branch_actors)

        assert "validate" in all_handlers
        assert "preprocess" in all_handlers or any("preprocess" in h for h in all_handlers)
        assert "postprocess" in all_handlers or any("postprocess" in h for h in all_handlers)

    def test_error_handling_pattern(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = validate_input(p)

                if not p.get("valid", False):
                    p["error"] = "Invalid input"
                    return p

                p = process(p)

                if p.get("error"):
                    p = error_handler(p)
                    return p

                p = finalize(p)
                return p

            def validate_input(p: dict) -> dict:
                return p
            def process(p: dict) -> dict:
                return p
            def error_handler(p: dict) -> dict:
                return p
            def finalize(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        cond_routers = [r for r in compiler.routers if r.condition is not None]
        assert len(cond_routers) == 2


class TestEdgeCasesComplex:
    """Test edge cases in complex scenarios."""

    def test_all_empty_branches_nested(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["outer"]:
                    if p["inner"]:
                        pass
                    else:
                        pass
                else:
                    pass
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        cond_routers = [r for r in compiler.routers if r.condition is not None]
        assert len(cond_routers) == 2

    def test_single_statement_branches(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["x"]:
                    p["a"] = 1
                else:
                    p["b"] = 2

                if p["y"]:
                    p = handler(p)

                return p

            def handler(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        cond_routers = [r for r in compiler.routers if r.condition is not None]
        assert len(cond_routers) == 2

    def test_very_long_sequential_chain(self):
        calls = "\n".join([f"    p = handler_{i}(p)" for i in range(20)])
        handlers = "\n".join([f"def handler_{i}(p: dict) -> dict:\n    return p" for i in range(20)])

        source = f"""
def flow(p: dict) -> dict:
{calls}
    return p

{handlers}
"""

        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        all_handlers = set()
        for router in compiler.routers:
            all_handlers.update(router.true_branch_actors)
            all_handlers.update(router.false_branch_actors)

        handler_count = sum(1 for h in all_handlers if h.startswith("handler"))
        assert handler_count == 20


class TestCodeQuality:
    """Test that generated code meets quality standards."""

    def test_no_syntax_errors_in_complex_flow(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["init"] = True
                p = setup(p)

                if p["type"] == "A":
                    p["branch"] = "A"
                    if p["subtype"] == "1":
                        p = handler_a1(p)
                    else:
                        p = handler_a2(p)
                elif p["type"] == "B":
                    p["branch"] = "B"
                    p = handler_b(p)
                else:
                    p["branch"] = "default"

                p = finalize(p)
                p["complete"] = True
                return p

            def setup(p: dict) -> dict:
                return p
            def handler_a1(p: dict) -> dict:
                return p
            def handler_a2(p: dict) -> dict:
                return p
            def handler_b(p: dict) -> dict:
                return p
            def finalize(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        try:
            compile(code, "test.py", "exec")
        except SyntaxError as e:
            pytest.fail(f"Generated code has syntax errors: {e}")

    def test_all_routers_are_functions(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["x"]:
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
        code = compiler.compile(source, "test.py")

        namespace = {}
        exec(code, namespace)

        for router in compiler.routers:
            assert router.name in namespace
            assert callable(namespace[router.name])
