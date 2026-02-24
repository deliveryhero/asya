"""Integration tests for while loop compilation.

These tests exercise the full compilation pipeline (parse -> group -> codegen)
and validate that the generated router code correctly manipulates message routes
for various while loop patterns.
"""

import ast
import os
import sys
import tempfile
from pathlib import Path

import pytest
from asya_cli.flow.compiler import FlowCompiler


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


def make_message(
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
def flow(p: dict) -> dict:
    while p["i"] < 3:
        p["i"] += 1
        p = handler(p)
    return p
"""
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        tree = ast.parse(code)
        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]

        assert "start_flow" in func_names
        assert "end_flow" in func_names
        assert any("while" in n for n in func_names)
        assert any("loop_back" in n for n in func_names)

    def test_compile_while_true(self):
        source = """
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
        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]

        # while True should NOT produce a condition router
        assert not any("_while_" in n for n in func_names)
        assert any("loop_back" in n for n in func_names)


class TestWhileWithBreak:
    """Test while loop with break produces correct routing."""

    def test_while_with_break_structure(self):
        source = """
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

        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        assert any("while" in n for n in func_names)
        assert any("loop_back" in n for n in func_names)

        # Should reference handler_finalize in the generated code (break exits to it)
        assert "handler_finalize" in code


class TestWhileWithContinue:
    """Test while loop with continue produces correct routing."""

    def test_while_with_continue_structure(self):
        source = """
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

        # continue should reference a loop_back router
        assert "loop_back" in code


class TestWhileWithIfInBody:
    """Test while with conditional branching inside body."""

    def test_if_inside_while(self):
        source = """
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
        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]

        assert any("_if" in n for n in func_names)
        assert any("while" in n or "loop_back" in n for n in func_names)
        assert "handler_even" in code
        assert "handler_odd" in code


class TestNestedWhileLoops:
    """Test nested while loop compilation."""

    def test_two_level_nesting(self):
        source = """
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
        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]

        loop_backs = [n for n in func_names if "loop_back" in n]
        whiles = [n for n in func_names if "_while_" in n]

        assert len(loop_backs) == 2
        assert len(whiles) == 2


class TestWhileMutationsInBody:
    """Test while loop with mutations in the body."""

    def test_mutations_inside_loop(self):
        source = """
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
        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]

        assert any("while" in n for n in func_names)
        assert any("loop_back" in n for n in func_names)
        assert "handler_check" in code
        assert "handler_process" in code
        assert "handler_finalize" in code


class TestWhileInsideIf:
    """Test while loop inside a conditional branch."""

    def test_while_in_true_branch(self):
        source = """
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
        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]

        assert any("_if" in n for n in func_names)
        assert any("while" in n or "loop_back" in n for n in func_names)


class TestComplexFlow:
    """Test complex flow combining all features."""

    def test_complex_flow_compiles(self):
        source = """
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

        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        assert "start_complex_flow" in func_names
        assert "end_complex_flow" in func_names
        assert any("while" in n or "loop_back" in n for n in func_names)

    def test_react_loop_pattern(self):
        """Test the ReAct (Reasoning + Acting) loop pattern from the RFC."""
        source = """
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
        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]

        assert "start_agent" in func_names
        assert any("loop_back" in n for n in func_names)
        assert "llm_call" in code
        assert "execute_tool" in code


class TestSequentialWhileLoops:
    """Test multiple while loops in sequence."""

    def test_two_sequential_whiles(self):
        source = """
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
        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]

        loop_backs = [n for n in func_names if "loop_back" in n]
        whiles = [n for n in func_names if "_while_" in n]

        assert len(loop_backs) == 2
        assert len(whiles) == 2


class TestWhileReturnInBody:
    """Test while loop with return inside the body."""

    def test_return_in_while_true(self):
        source = """
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

        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        assert any("loop_back" in n for n in func_names)

    def test_return_in_conditional_while(self):
        source = """
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

        func_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        assert any("while" in n for n in func_names)
        assert "handler_finalize" in code


class TestWhileOnlyMutationsInBody:
    """Test while loop with only mutations (no actor calls) in body."""

    def test_mutations_only_body(self):
        source = """
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
    """Compile all example flows from later/ directory and verify valid Python output."""

    EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "examples" / "flows"

    @pytest.fixture(autouse=True)
    def skip_if_no_examples(self):
        if not self.EXAMPLES_DIR.exists():
            pytest.skip(f"Examples directory not found: {self.EXAMPLES_DIR}")

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


class TestMaxIterationsGuardIntegration:
    """Test max_iterations guard through the full compilation pipeline."""

    def test_while_true_generates_guard_code(self):
        source = """
def flow(p: dict) -> dict:
    while True:
        p = handler(p)
        if p["done"]:
            break
    return p
"""
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        assert "_ASYA_MAX_LOOP_ITERATIONS" in code
        assert "route/prev" in code
        assert "_prev.count(_self) >= _ASYA_MAX_LOOP_ITERATIONS" in code
        assert "RuntimeError" in code
        # No payload pollution
        assert "__loop_" not in code

        tree = ast.parse(code)
        assert tree is not None

    def test_while_condition_no_guard_code(self):
        source = """
def flow(p: dict) -> dict:
    while p["i"] < 10:
        p["i"] += 1
        p = handler(p)
    return p
"""
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        assert "_ASYA_MAX_LOOP_ITERATIONS" not in code

    def test_custom_max_iterations_via_compiler(self):
        source = """
def flow(p: dict) -> dict:
    while True:
        p = handler(p)
        if p["done"]:
            break
    return p
"""
        compiler = FlowCompiler(max_iterations=10)
        code = compiler.compile(source, "test.py")

        assert '"10"' in code

    def test_react_loop_gets_guard(self):
        source = """
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

        assert "_ASYA_MAX_LOOP_ITERATIONS" in code
        assert "RuntimeError" in code

        tree = ast.parse(code)
        assert tree is not None

    def _setup_vfs(self, tmpdir: str, prev: list[str], next_actors: list[str]) -> str:
        """Set up a VFS directory structure for a message."""
        vfs_root = os.path.join(tmpdir, "vfs")
        route_dir = os.path.join(vfs_root, "route")
        os.makedirs(route_dir, exist_ok=True)
        with open(os.path.join(route_dir, "prev"), "w") as f:
            f.write("\n".join(prev))
        with open(os.path.join(route_dir, "next"), "w") as f:
            f.write("\n".join(next_actors))
        return vfs_root

    def _read_vfs_next(self, vfs_root: str) -> list[str]:
        next_path = os.path.join(vfs_root, "route", "next")
        with open(next_path) as f:
            content = f.read()
        return [x for x in content.splitlines() if x]

    def _write_vfs_prev(self, vfs_root: str, prev: list[str]) -> None:
        with open(os.path.join(vfs_root, "route", "prev"), "w") as f:
            f.write("\n".join(prev))

    def _write_vfs_next(self, vfs_root: str, next_actors: list[str]) -> None:
        with open(os.path.join(vfs_root, "route", "next"), "w") as f:
            f.write("\n".join(next_actors))

    def test_guard_execution_raises_at_limit(self, compile_and_import, monkeypatch):
        source = """
def flow(p: dict) -> dict:
    while True:
        p = handler(p)
        if p.get("done"):
            break
    return p
"""
        monkeypatch.setenv("ASYA_HANDLER_HANDLER", "handler")
        monkeypatch.setenv("ASYA_MAX_LOOP_ITERATIONS", "3")

        mod = compile_and_import(source)
        # resolve() returns name as-is so route history can be counted
        monkeypatch.setattr(mod, "resolve", lambda name: name)

        loop_back_name = None
        loop_back_fn = None
        for name in dir(mod):
            if "loop_back" in name:
                loop_back_name = name
                loop_back_fn = getattr(mod, name)
                break
        assert loop_back_name is not None
        assert loop_back_fn is not None

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = self._setup_vfs(tmpdir, prev=["start_flow"], next_actors=[])
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)

            payload = {"value": 1}

            # 3 iterations should succeed (prev accumulates loop_back visits)
            prev_list = ["start_flow"]
            for _ in range(3):
                self._write_vfs_prev(vfs_root, prev_list)
                self._write_vfs_next(vfs_root, [])
                loop_back_fn(payload)
                # Simulate runtime shifting route: move curr to prev
                prev_list = [*prev_list, loop_back_name]

            # 4th iteration should raise (3 past visits in prev)
            self._write_vfs_prev(vfs_root, prev_list)
            self._write_vfs_next(vfs_root, [])
            with pytest.raises(RuntimeError, match="Max loop iterations"):
                loop_back_fn(payload)

    def test_guard_execution_succeeds_under_limit(self, compile_and_import, monkeypatch):
        source = """
def flow(p: dict) -> dict:
    while True:
        p = handler(p)
        if p.get("done"):
            break
    return p
"""
        monkeypatch.setenv("ASYA_HANDLER_HANDLER", "handler")
        monkeypatch.setenv("ASYA_MAX_LOOP_ITERATIONS", "5")

        mod = compile_and_import(source)
        # resolve() returns name as-is so route history can be counted
        monkeypatch.setattr(mod, "resolve", lambda name: name)

        loop_back_name = None
        loop_back_fn = None
        for name in dir(mod):
            if "loop_back" in name:
                loop_back_name = name
                loop_back_fn = getattr(mod, name)
                break
        assert loop_back_name is not None
        assert loop_back_fn is not None

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = self._setup_vfs(tmpdir, prev=["start_flow"], next_actors=[])
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)

            payload = {"value": 1}
            prev_list = ["start_flow"]

            for _ in range(5):
                self._write_vfs_prev(vfs_root, prev_list)
                self._write_vfs_next(vfs_root, [])
                result = loop_back_fn(payload)
                # Simulate runtime shifting route: move curr to prev
                prev_list = [*prev_list, loop_back_name]

            # Payload stays clean (no __loop_ keys injected)
            assert not any(k.startswith("__loop_") for k in result)
