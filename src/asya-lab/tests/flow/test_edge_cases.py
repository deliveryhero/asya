"""Edge case validation tests for the flow compiler."""

import ast
import textwrap

from asya_lab.flow.compiler import FlowCompiler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compile(source: str) -> str:
    compiler = FlowCompiler()
    return compiler.compile(textwrap.dedent(source), "test.py")


def _compile_with_graph(source: str) -> FlowCompiler:
    compiler = FlowCompiler()
    compiler.compile(textwrap.dedent(source), "test.py")
    return compiler


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestSingleActorFlow:
    """A flow with exactly one actor call and no other operations (besides Return)
    should emit metadata-only output, not a full router."""

    def test_single_actor_generates_metadata_only(self):
        code = _compile("""
            @flow
            def single_step(p: dict) -> dict:
                p = my_actor(p)
                return p
        """)
        assert "FLOW_METADATA" in code
        assert "single-actor" in code

    def test_single_actor_has_start_role(self):
        compiler = _compile_with_graph("""
            @flow
            def single_step(p: dict) -> dict:
                p = my_actor(p)
                return p
        """)
        assert compiler.single_actor_name == "my_actor"


class TestMultipleExitpoints:
    """Branching flows with early returns should mark both terminal actors
    with role=end in the graph."""

    def test_branching_flow_has_multiple_end_nodes(self):
        compiler = _compile_with_graph("""
            @flow
            def branching(p: dict) -> dict:
                if p["flag"]:
                    p = actor_a(p)
                    return p
                else:
                    p = actor_b(p)
                    return p
        """)
        graph = compiler._graph_data
        assert graph is not None
        end_nodes = [n["id"] for n in graph.nodes if n.get("role") == "end"]
        assert "actor_a" in end_nodes
        assert "actor_b" in end_nodes


class TestNestedControlFlow:
    """P13 invariant: nested control flow generates one router per level."""

    def test_nested_if_generates_chain_of_routers(self):
        code = _compile("""
            @flow
            def nested(p: dict) -> dict:
                if p["outer"]:
                    if p["inner"]:
                        p = actor_a(p)
                    else:
                        p = actor_b(p)
                else:
                    p = actor_c(p)
                return p
        """)
        tree = ast.parse(code)
        router_funcs = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and "_if_" in node.name
        ]
        assert len(router_funcs) == 2, f"Expected 2 if-routers, got {len(router_funcs)}: {router_funcs}"

    def test_while_with_if_generates_separate_routers(self):
        code = _compile("""
            @flow
            def loop_branch(p: dict) -> dict:
                while p["go"]:
                    if p["check"]:
                        p = actor_x(p)
                    else:
                        p = actor_y(p)
                return p
        """)
        tree = ast.parse(code)
        func_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)]
        while_routers = [n for n in func_names if "_while_" in n]
        if_routers = [n for n in func_names if "_if_" in n]
        assert len(while_routers) >= 1, f"Expected at least 1 while-router, got {while_routers}"
        assert len(if_routers) >= 1, f"Expected at least 1 if-router, got {if_routers}"


class TestMutationsOnly:
    """A flow with only payload mutations (no actor calls) should generate
    a start router containing those mutations."""

    def test_mutations_only_flow(self):
        code = _compile("""
            @flow
            def mutate_only(p: dict) -> dict:
                p["x"] = 1
                p["y"] = 2
                return p
        """)
        assert "start_mutate_only" in code
        assert "p['x'] = 1" in code or 'p["x"] = 1' in code


class TestAbortRouting:
    """An early return in an if-branch should produce an empty route
    (abort to x-sink) for that branch."""

    def test_early_return_in_branch(self):
        code = _compile("""
            @flow
            def abort_flow(p: dict) -> dict:
                if p["done"]:
                    return p
                p = actor_z(p)
                return p
        """)
        # The true branch returns early, which means it uses SET with an
        # empty route list (yield p / return). The false branch continues
        # to actor_z.
        tree = ast.parse(code)
        if_funcs = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and "_if_" in node.name
        ]
        assert len(if_funcs) >= 1
        # The if-router source must contain "yield p" (early return path)
        if_source = ast.unparse(if_funcs[0])
        assert "yield p" in if_source


class TestNoOpFlow:
    """A flow with only mutations and return (no actor calls) should
    generate a start router with the mutation code."""

    def test_no_handler_flow(self):
        code = _compile("""
            @flow
            def noop(p: dict) -> dict:
                p["tag"] = "processed"
                return p
        """)
        assert "start_noop" in code
        assert "processed" in code
