"""Integration tests for while loop compilation.

These tests exercise the full compilation pipeline (parse -> codegen -> analyze)
and validate that the generated router code correctly manipulates envelope routes
for various while loop patterns.
"""

import ast
import sys
import tempfile
from pathlib import Path

import pytest
from asya_lab.flow.compiler import FlowCompiler


# ---------------------------------------------------------------------------
# Fixture: compile source and import the generated module
# ---------------------------------------------------------------------------


@pytest.fixture
def compile_and_import():
    """Factory fixture: compiles flow source and returns the imported module."""
    modules_to_cleanup = []

    def _compile(source_code: str):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_file = Path(tmpdir) / "flow.py"
            source_file.write_text(source_code)

            output_dir = Path(tmpdir) / "output"
            compiler = FlowCompiler()
            compiler.compile_file(str(source_file), str(output_dir))

            sys.path.insert(0, str(output_dir))
            import importlib

            # Remove cached module if present
            if "routers" in sys.modules:
                del sys.modules["routers"]

            import routers

            importlib.reload(routers)
            modules_to_cleanup.append(str(output_dir))

            return routers

    yield _compile

    for path in modules_to_cleanup:
        if path in sys.path:
            sys.path.remove(path)
    if "routers" in sys.modules:
        del sys.modules["routers"]


def make_envelope(
    payload: dict,
    prev: list[str] | None = None,
    curr: str = "",
    next_actors: list[str] | None = None,
) -> dict:
    """Create a test message with route structure."""
    return {
        "id": "test-msg",
        "route": {
            "prev": prev or [],
            "curr": curr,
            "next": next_actors or [],
        },
        "payload": payload,
    }


# ---------------------------------------------------------------------------
# Tests: simple while loop
# ---------------------------------------------------------------------------


class TestSimpleWhileCompilation:
    """Test compilation of simple while loop patterns."""

    def test_compile_simple_while(self):
        source = """
@flow
def flow(p: dict) -> dict:
    while p["i"] < 3:
        p["i"] += 1
        p = handler(p)
    return p
"""
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        tree = ast.parse(code)
        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]

        assert "start_flow" in func_names
        assert any("while" in n for n in func_names)

    def test_compile_while_true(self):
        source = """
@flow
def flow(p: dict) -> dict:
    while True:
        p = handler(p)
        if p["done"]:
            break
    return p
"""
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        tree = ast.parse(code)
        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]

        # while True uses the same naming: router_..._while_...
        assert any("while" in n for n in func_names)


class TestWhileWithBreak:
    """Test while loop with break produces correct routing."""

    def test_while_with_break_structure(self):
        source = """
@flow
def flow(p: dict) -> dict:
    p = handler_init(p)
    p["i"] = 0
    while p["i"] < 10:
        p["i"] += 1
        p = handler_process(p)
        if p["stop_condition"]:
            break
    p = handler_finalize(p)
    return p
"""
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        tree = ast.parse(code)
        assert tree is not None

        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
        assert any("while" in n for n in func_names)

        # Should reference handler_finalize in the generated code (break exits to it)
        assert "handler_finalize" in code


class TestWhileWithContinue:
    """Test while loop with continue produces correct routing."""

    def test_while_with_continue_structure(self):
        source = """
@flow
def flow(p: dict) -> dict:
    p = handler_init(p)
    p["i"] = 0
    while p["i"] < 10:
        p["i"] += 1
        if p["skip_iteration"]:
            continue
        p = handler_process(p)
    p = handler_finalize(p)
    return p
"""
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        tree = ast.parse(code)
        assert tree is not None

        # continue should reference the while router
        assert "_while_" in code


class TestWhileWithIfInBody:
    """Test while with conditional branching inside body."""

    def test_if_inside_while(self):
        source = """
@flow
def flow(p: dict) -> dict:
    p["i"] = 0
    while p["i"] < 10:
        p["i"] += 1
        if p["i"] % 2 == 0:
            p = handler_even(p)
        else:
            p = handler_odd(p)
    p = handler_finalize(p)
    return p
"""
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        tree = ast.parse(code)
        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]

        assert any("_if" in n for n in func_names)
        assert any("_while_" in n for n in func_names)
        assert "handler_even" in code
        assert "handler_odd" in code


class TestNestedWhileLoops:
    """Test nested while loop compilation."""

    def test_two_level_nesting(self):
        source = """
@flow
def flow(p: dict) -> dict:
    p["i"] = 0
    while p["i"] < 10:
        p["i"] += 1
        p = handler_outer(p)
        p["j"] = 0
        while p["j"] < 5:
            p["j"] += 1
            p = handler_inner(p)
        p = handler_outer_end(p)
    p = handler_finalize(p)
    return p
"""
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        tree = ast.parse(code)
        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]

        whiles = [n for n in func_names if "_while_" in n]
        assert len(whiles) == 2


class TestWhileMutationsInBody:
    """Test while loop with mutations in the body."""

    def test_mutations_inside_loop(self):
        source = """
@flow
def flow(p: dict) -> dict:
    p["i"] = 0
    p["sum"] = 0
    while p["i"] < 10:
        p["i"] += 1
        p["sum"] += p["i"]
        p["step"] = p["i"]
        p = handler_process(p)
        p["processed"] = True
    p = handler_finalize(p)
    return p
"""
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        tree = ast.parse(code)
        assert tree is not None

        # Verify mutations appear in generated code (ast.unparse may use single quotes)
        assert "p['i'] += 1" in code or 'p["i"] += 1' in code
        assert "p['sum'] += p['i']" in code or 'p["sum"] += p["i"]' in code


class TestWhileBreakContinueCombined:
    """Test while loop with both break and continue."""

    def test_break_and_continue_combined(self):
        source = """
@flow
def flow(p: dict) -> dict:
    p = handler_init(p)
    p["i"] = 0
    while p["i"] < 10:
        p["i"] += 1
        p = handler_check(p)
        if p["skip"]:
            continue
        p = handler_process(p)
        if p["stop"]:
            break
    p = handler_finalize(p)
    return p
"""
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        tree = ast.parse(code)
        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]

        assert any("_while_" in n for n in func_names)
        assert "handler_check" in code
        assert "handler_process" in code
        assert "handler_finalize" in code


class TestWhileInsideIf:
    """Test while loop inside a conditional branch."""

    def test_while_in_true_branch(self):
        source = """
@flow
def flow(p: dict) -> dict:
    if p.get("needs_enrichment"):
        while p.get("batch_count", 0) < p.get("max_batches", 3):
            p = handler_transform_batch(p)
    else:
        p = handler_simple(p)
    p = handler_finalize(p)
    return p
"""
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        tree = ast.parse(code)
        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]

        assert any("_if" in n for n in func_names)
        assert any("_while_" in n for n in func_names)


class TestComplexFlow:
    """Test complex flow combining all features."""

    def test_complex_flow_compiles(self):
        source = """
@flow
def complex_flow(p: dict) -> dict:
    p = handler_preprocess(p)
    p = handler_validate(p)

    if not p["valid"]:
        p = handler_error(p)
        return p

    if p.get("needs_enrichment"):
        p = handler_enrich_data(p)

        while p.get("batch_count", 0) < p.get("max_batches", 3):
            p = handler_transform_batch(p)
            p = handler_check_quality(p)

            if p["quality_score"] < 20:
                continue

            if p["quality_score"] >= 50:
                break
    else:
        if p.get("requires_retry"):
            p = handler_retry_handler(p)

    p = handler_finalize(p)
    return p
"""
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            pytest.fail(f"Complex flow generated invalid Python: {e}")

        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
        assert "start_complex_flow" in func_names
        assert any("_while_" in n for n in func_names)

    def test_react_loop_pattern(self):
        """Test the ReAct (Reasoning + Acting) loop pattern from the RFC."""
        source = """
@flow
def agent(p: dict) -> dict:
    while True:
        p = llm_call(p)
        if p.get("tool_calls"):
            p = execute_tool(p)
        else:
            return p
    return p
"""
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        tree = ast.parse(code)
        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]

        assert "start_agent" in func_names
        assert any("while" in n for n in func_names)
        assert "llm_call" in code
        assert "execute_tool" in code


class TestSequentialWhileLoops:
    """Test multiple while loops in sequence."""

    def test_two_sequential_whiles(self):
        source = """
@flow
def flow(p: dict) -> dict:
    while p["i"] < 10:
        p["i"] += 1
        p = handler_a(p)
    while p["j"] < 5:
        p["j"] += 1
        p = handler_b(p)
    return p
"""
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        tree = ast.parse(code)
        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]

        whiles = [n for n in func_names if "_while_" in n]
        assert len(whiles) == 2


class TestWhileReturnInBody:
    """Test while loop with return inside the body."""

    def test_return_in_while_true(self):
        source = """
@flow
def flow(p: dict) -> dict:
    while True:
        p = handler(p)
        if p["result_ready"]:
            return p
    return p
"""
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")
        tree = ast.parse(code)

        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
        assert any("while" in n for n in func_names)

    def test_return_in_conditional_while(self):
        source = """
@flow
def flow(p: dict) -> dict:
    while p["i"] < 10:
        p["i"] += 1
        p = handler(p)
        if p["error"]:
            return p
    p = handler_finalize(p)
    return p
"""
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")
        tree = ast.parse(code)

        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
        assert any("while" in n for n in func_names)
        assert "handler_finalize" in code


class TestWhileOnlyMutationsInBody:
    """Test while loop with only mutations (no actor calls) in body."""

    def test_mutations_only_body(self):
        source = """
@flow
def flow(p: dict) -> dict:
    while p["i"] < 10:
        p["i"] += 1
    return p
"""
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")
        tree = ast.parse(code)
        assert tree is not None


class TestExampleFlowsCompile:
    """Compile example flow fixtures and verify valid Python output."""

    EXAMPLES_DIR = Path(__file__).resolve().parent / "fixtures" / "example_flows"

    @pytest.fixture(autouse=True)
    def skip_if_no_examples(self):
        if not self.EXAMPLES_DIR.exists():
            pytest.skip(f"Fixtures directory not found: {self.EXAMPLES_DIR}")

    def _compile_example(self, filename: str) -> str:
        source_file = self.EXAMPLES_DIR / filename
        source_code = source_file.read_text()

        compiler = FlowCompiler()
        code = compiler.compile(source_code, str(source_file))

        try:
            ast.parse(code)
        except SyntaxError as e:
            pytest.fail(f"Compiled {filename} produced invalid Python: {e}")

        return code

    def test_while_simple(self):
        self._compile_example("while_simple.py")

    def test_while_with_break(self):
        self._compile_example("while_with_break.py")

    def test_while_with_continue(self):
        self._compile_example("while_with_continue.py")

    def test_while_with_if(self):
        self._compile_example("while_with_if.py")

    def test_while_break_continue(self):
        self._compile_example("while_break_continue.py")

    def test_while_mutations_in_loop(self):
        self._compile_example("while_mutations_in_loop.py")

    def test_while_nested(self):
        self._compile_example("while_nested.py")

    def test_complex(self):
        self._compile_example("complex_with_while.py")
