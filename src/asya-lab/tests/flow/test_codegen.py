"""Unit tests for code generation via the full compile pipeline."""

import ast
import textwrap

from asya_lab.flow.compiler import FlowCompiler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compile(source: str) -> str:
    """Compile flow source and return generated code."""
    compiler = FlowCompiler()
    return compiler.compile(textwrap.dedent(source), "test.py")


def _func_names(code: str) -> list[str]:
    """Extract all function names from generated code."""
    tree = ast.parse(code)
    return [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)]


def _get_func_source(code: str, func_name: str) -> str:
    """Extract source of a specific function from generated code."""
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == func_name:
            return ast.unparse(node)
    raise ValueError(f"Function {func_name} not found")


class TestCodeValidity:
    """Generated code must be valid Python."""

    def test_sequential_flow_is_valid_python(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p = handler_a(p)
                p = handler_b(p)
                return p
        """)
        ast.parse(code)

    def test_conditional_flow_is_valid_python(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                if p["condition"]:
                    p = handler_a(p)
                else:
                    p = handler_b(p)
                return p
        """)
        ast.parse(code)

    def test_loop_flow_is_valid_python(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                while p["running"]:
                    p = handler(p)
                return p
        """)
        ast.parse(code)

    def test_complex_flow_is_valid_python(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p["init"] = True
                p = preprocessor(p)
                if p["mode"] == "fast":
                    p = fast_handler(p)
                else:
                    while p["remaining"] > 0:
                        p = slow_handler(p)
                        if p["abort"]:
                            break
                p = finalizer(p)
                return p
        """)
        ast.parse(code)


class TestStartRouter:
    """Start router prepends the entry chain."""

    def test_start_router_exists(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p = handler_a(p)
                p = handler_b(p)
                return p
        """)
        assert "start_my_flow" in _func_names(code)

    def test_start_router_prepends_actors(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p = handler_a(p)
                p = handler_b(p)
                return p
        """)
        start = _get_func_source(code, "start_my_flow")
        assert "handler_a" in start
        assert "handler_b" in start
        assert ".route.next[:0]" in start


class TestSequentialRouters:
    """Mutations create sequence routers."""

    def test_mutations_before_actors_create_seq_router(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p["status"] = "started"
                p = handler_a(p)
                return p
        """)
        funcs = _func_names(code)
        seq_routers = [f for f in funcs if "seq" in f]
        assert len(seq_routers) >= 1

    def test_mutations_only_flow_creates_router(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p["a"] = 1
                p["b"] = 2
                return p
        """)
        ast.parse(code)
        funcs = _func_names(code)
        assert any("seq" in f for f in funcs)


class TestConditionalRouters:
    """Conditional flows produce if/else routers."""

    def test_conditional_creates_if_router(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                if p["flag"]:
                    p = handler_a(p)
                else:
                    p = handler_b(p)
                return p
        """)
        funcs = _func_names(code)
        assert any("if" in f for f in funcs)

    def test_conditional_router_has_both_branches(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                if p["flag"]:
                    p = handler_a(p)
                else:
                    p = handler_b(p)
                return p
        """)
        if_routers = [f for f in _func_names(code) if "if" in f]
        assert len(if_routers) >= 1
        if_source = _get_func_source(code, if_routers[0])
        assert "handler_a" in if_source
        assert "handler_b" in if_source

    def test_convergence_after_conditional(self):
        """Both branches should include continuation actors."""
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                if p["flag"]:
                    p = handler_a(p)
                else:
                    p = handler_b(p)
                p = handler_c(p)
                return p
        """)
        if_routers = [f for f in _func_names(code) if "if" in f]
        assert len(if_routers) >= 1
        if_source = _get_func_source(code, if_routers[0])
        # handler_c should appear in both branches (convergence)
        assert if_source.count("handler_c") >= 2

    def test_nested_conditionals(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                if p["outer"]:
                    if p["inner"]:
                        p = handler_a(p)
                    else:
                        p = handler_b(p)
                else:
                    p = handler_c(p)
                p = handler_d(p)
                return p
        """)
        funcs = _func_names(code)
        if_routers = [f for f in funcs if "if" in f]
        assert len(if_routers) >= 2


class TestLoopRouters:
    """While loops produce loop-back routers."""

    def test_while_creates_loop_router(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                while p["running"]:
                    p = handler(p)
                return p
        """)
        funcs = _func_names(code)
        assert any("while" in f for f in funcs)

    def test_while_true_creates_unconditional_loop(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                while True:
                    p = handler(p)
                    if p["done"]:
                        break
                return p
        """)
        ast.parse(code)
        funcs = _func_names(code)
        assert any("while" in f for f in funcs)

    def test_loop_router_prepends_body_and_self(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                while p["running"]:
                    p = handler(p)
                return p
        """)
        while_routers = [f for f in _func_names(code) if "while" in f]
        assert len(while_routers) >= 1
        loop_source = _get_func_source(code, while_routers[0])
        # Loop router should reference itself for loop-back
        assert while_routers[0] in loop_source

    def test_break_uses_set_routing(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                while p["running"]:
                    p = handler(p)
                    if p["abort"]:
                        break
                p = finalizer(p)
                return p
        """)
        ast.parse(code)
        if_routers = [f for f in _func_names(code) if "if" in f]
        assert len(if_routers) >= 1
        # Break branch should use SET (not prepend)
        if_source = _get_func_source(code, if_routers[0])
        assert ".route.next" in if_source

    def test_continue_loops_back(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                while p["running"]:
                    if p["skip"]:
                        continue
                    p = handler(p)
                return p
        """)
        ast.parse(code)

    def test_mutations_before_loop_run_once(self):
        """Mutations before loop should be in a separate seq router, not duplicated."""
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p["i"] = 0
                while p["i"] < 10:
                    p = handler(p)
                return p
        """)
        # The mutation p['i'] = 0 should appear exactly once (may use single or double quotes)
        count = code.count("p['i'] = 0") + code.count('p["i"] = 0')
        assert count == 1, f"Expected mutation once, found {count} times"


class TestSingleActorFlow:
    """Single actor flows produce metadata instead of routers."""

    def test_single_actor_flow_no_routers(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p = handler(p)
                return p
        """)
        # Should contain FLOW_METADATA instead of start/end routers
        assert "FLOW_METADATA" in code
        assert "single-actor" in code

    def test_single_actor_flow_no_resolve(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p = handler(p)
                return p
        """)
        assert "def resolve" not in code


class TestEarlyReturn:
    """Early return terminates the branch."""

    def test_early_return_in_conditional(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                if p["done"]:
                    return p
                p = handler(p)
                return p
        """)
        ast.parse(code)

    def test_early_return_uses_set_empty(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                if p["done"]:
                    return p
                p = handler(p)
                return p
        """)
        if_routers = [f for f in _func_names(code) if "if" in f]
        assert len(if_routers) >= 1
        if_source = _get_func_source(code, if_routers[0])
        # Early return sets route.next to []
        assert "[]" in if_source


class TestResolveFunction:
    """The resolve function is generated for multi-actor flows."""

    def test_resolve_function_exists(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p = handler_a(p)
                p = handler_b(p)
                return p
        """)
        assert "def resolve" in code

    def test_resolve_function_reads_env_vars(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p = handler_a(p)
                p = handler_b(p)
                return p
        """)
        assert "ASYA_HANDLER_" in code


class TestHeaderGeneration:
    """Header comments and metadata."""

    def test_header_contains_source_file(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p = handler(p)
                p = handler_b(p)
                return p
        """)
        assert "test.py" in code

    def test_header_contains_noqa(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p = handler(p)
                p = handler_b(p)
                return p
        """)
        assert "ruff: noqa" in code


class TestAsyncFlows:
    """Async flows produce async routers."""

    def test_async_flow_compiles(self):
        code = _compile("""
            @flow
            async def my_flow(p: dict) -> dict:
                p = await handler_a(p)
                p = await handler_b(p)
                return p
        """)
        ast.parse(code)

    def test_async_flow_has_start(self):
        code = _compile("""
            @flow
            async def my_flow(p: dict) -> dict:
                p = await handler_a(p)
                p = await handler_b(p)
                return p
        """)
        funcs = _func_names(code)
        assert "start_my_flow" in funcs
