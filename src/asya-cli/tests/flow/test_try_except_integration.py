"""Integration tests for try-except flow compilation.

These tests exercise the full compilation pipeline (parse -> group -> codegen)
and validate that the generated router code correctly manipulates message routes,
headers, and status fields for try-except error handling patterns via VFS.
"""

import importlib
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
    modules_to_cleanup: list[str] = []

    def _compile(source_code: str):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_file = Path(tmpdir) / "flow.py"
            source_file.write_text(source_code)

            output_dir = Path(tmpdir) / "output"
            compiler = FlowCompiler()
            compiler.compile_file(str(source_file), str(output_dir))

            sys.path.insert(0, str(output_dir))

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


# ---------------------------------------------------------------------------
# VFS helpers
# ---------------------------------------------------------------------------


def setup_vfs(
    tmpdir: str,
    prev: list[str] | None = None,
    next_actors: list[str] | None = None,
    headers: dict[str, str] | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    error_mro: list[str] | None = None,
) -> str:
    """Set up a VFS directory structure for a message and return the VFS root path."""
    vfs_root = os.path.join(tmpdir, "vfs")
    route_dir = os.path.join(vfs_root, "route")
    os.makedirs(route_dir, exist_ok=True)
    with open(os.path.join(route_dir, "prev"), "w") as f:
        f.write("\n".join(prev or []))
    with open(os.path.join(route_dir, "next"), "w") as f:
        f.write("\n".join(next_actors or []))

    if headers:
        headers_dir = os.path.join(vfs_root, "headers")
        os.makedirs(headers_dir, exist_ok=True)
        for key, value in headers.items():
            with open(os.path.join(headers_dir, key), "w") as f:
                f.write(value)

    if error_type is not None:
        status_error_dir = os.path.join(vfs_root, "status", "error")
        os.makedirs(status_error_dir, exist_ok=True)
        with open(os.path.join(status_error_dir, "type"), "w") as f:
            f.write(error_type)
        with open(os.path.join(status_error_dir, "message"), "w") as f:
            f.write(error_message or "")
        with open(os.path.join(status_error_dir, "mro"), "w") as f:
            f.write("\n".join(error_mro or []))

    return vfs_root


def read_vfs_next(vfs_root: str) -> list[str]:
    next_path = os.path.join(vfs_root, "route", "next")
    with open(next_path) as f:
        content = f.read()
    return [x for x in content.splitlines() if x]


def read_vfs_header(vfs_root: str, key: str) -> str | None:
    header_path = os.path.join(vfs_root, "headers", key)
    if not os.path.exists(header_path):
        return None
    with open(header_path) as f:
        return f.read()


def vfs_header_exists(vfs_root: str, key: str) -> bool:
    return os.path.exists(os.path.join(vfs_root, "headers", key))


def vfs_error_exists(vfs_root: str) -> bool:
    return os.path.exists(os.path.join(vfs_root, "status", "error"))


def write_vfs_next(vfs_root: str, next_actors: list[str]) -> None:
    with open(os.path.join(vfs_root, "route", "next"), "w") as f:
        f.write("\n".join(next_actors))


def write_vfs_prev(vfs_root: str, prev: list[str]) -> None:
    with open(os.path.join(vfs_root, "route", "prev"), "w") as f:
        f.write("\n".join(prev))


def _find_function(mod, substring: str):
    """Find a function in the module whose name contains the given substring."""
    for name in dir(mod):
        if substring in name:
            fn = getattr(mod, name)
            if callable(fn):
                return name, fn
    return None, None


def _find_all_functions(mod, substring: str) -> list[tuple[str, object]]:
    """Find all functions in the module whose names contain the given substring."""
    results = []
    for name in dir(mod):
        if substring in name:
            fn = getattr(mod, name)
            if callable(fn):
                results.append((name, fn))
    return results


# ---------------------------------------------------------------------------
# Tests: full compile + execute
# ---------------------------------------------------------------------------


class TestTryExceptRouterExecution:
    """Full compile + execute tests for try-except flow patterns."""

    # -- Test: try_enter sets _on_error and inserts body actors --------

    def test_try_enter_sets_on_error_and_inserts_body(self, compile_and_import, monkeypatch):
        source = """\
def flow(p: dict) -> dict:
    try:
        p = handler_a(p)
        p = handler_b(p)
    except ValueError:
        p = error_handler(p)
    p = finalize(p)
    return p
"""
        monkeypatch.setenv("ASYA_HANDLER_HANDLER_A", "handler_a")
        monkeypatch.setenv("ASYA_HANDLER_HANDLER_B", "handler_b")
        monkeypatch.setenv("ASYA_HANDLER_ERROR_HANDLER", "error_handler")
        monkeypatch.setenv("ASYA_HANDLER_FINALIZE", "finalize")

        mod = compile_and_import(source)
        monkeypatch.setattr(mod, "resolve", lambda name: name)

        try_enter_name, try_enter_fn = _find_function(mod, "try_enter")
        assert try_enter_name is not None, "try_enter router not found"

        except_dispatch_name, _ = _find_function(mod, "except_dispatch")
        assert except_dispatch_name is not None, "except_dispatch router not found"

        try_exit_name, _ = _find_function(mod, "try_exit")
        assert try_exit_name is not None, "try_exit router not found"

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = setup_vfs(tmpdir, prev=["start_flow"], next_actors=[])
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)

            try_enter_fn({"data": "test"})

            # _on_error header should be set to the except_dispatch router
            assert vfs_header_exists(vfs_root, "_on_error")
            assert read_vfs_header(vfs_root, "_on_error") == except_dispatch_name

            # Body actors (handler_a, handler_b) and try_exit should be prepended to next
            inserted = read_vfs_next(vfs_root)
            assert "handler_a" in inserted
            assert "handler_b" in inserted
            assert try_exit_name in inserted

    # -- Test: try_exit clears _on_error -----------------------------------

    def test_try_exit_clears_on_error(self, compile_and_import, monkeypatch):
        source = """\
def flow(p: dict) -> dict:
    try:
        p = handler_a(p)
    except ValueError:
        p = error_handler(p)
    p = finalize(p)
    return p
"""
        monkeypatch.setenv("ASYA_HANDLER_HANDLER_A", "handler_a")
        monkeypatch.setenv("ASYA_HANDLER_ERROR_HANDLER", "error_handler")
        monkeypatch.setenv("ASYA_HANDLER_FINALIZE", "finalize")

        mod = compile_and_import(source)
        monkeypatch.setattr(mod, "resolve", lambda name: name)

        try_exit_name, try_exit_fn = _find_function(mod, "try_exit")
        assert try_exit_name is not None, "try_exit router not found"

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = setup_vfs(
                tmpdir,
                prev=["start_flow", "try_enter", "handler_a"],
                next_actors=[],
                headers={"_on_error": "some-except-dispatch", "trace_id": "abc"},
            )
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)

            try_exit_fn({"data": "test"})

            # _on_error header should be removed
            assert not vfs_header_exists(vfs_root, "_on_error")
            # trace_id should still exist (only _on_error was removed)
            assert vfs_header_exists(vfs_root, "trace_id")

            # Continuation actors (finalize) should be prepended to next
            inserted = read_vfs_next(vfs_root)
            assert "finalize" in inserted

    # -- Test: except_dispatch matches error type --------------------------

    def test_except_dispatch_matches_error_type(self, compile_and_import, monkeypatch):
        source = """\
def flow(p: dict) -> dict:
    try:
        p = handler_a(p)
    except ValueError:
        p = error_handler(p)
    p = finalize(p)
    return p
"""
        monkeypatch.setenv("ASYA_HANDLER_HANDLER_A", "handler_a")
        monkeypatch.setenv("ASYA_HANDLER_ERROR_HANDLER", "error_handler")
        monkeypatch.setenv("ASYA_HANDLER_FINALIZE", "finalize")

        mod = compile_and_import(source)
        monkeypatch.setattr(mod, "resolve", lambda name: name)

        dispatch_name, dispatch_fn = _find_function(mod, "except_dispatch")
        assert dispatch_name is not None, "except_dispatch router not found"

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = setup_vfs(
                tmpdir,
                prev=[],
                next_actors=["placeholder"],
                error_type="ValueError",
                error_message="invalid value",
                error_mro=["Exception"],
            )
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)

            dispatch_fn({"data": "test"})

            # Should route to the ValueError handler
            inserted = read_vfs_next(vfs_root)
            assert "error_handler" in inserted

            # Error status should be cleared on match
            assert not vfs_error_exists(vfs_root)

            # Continuation actors (finalize) should be prepended to next
            assert "finalize" in inserted

    # -- Test: except_dispatch matches via MRO -----------------------------

    def test_except_dispatch_matches_via_mro(self, compile_and_import, monkeypatch):
        source = """\
def flow(p: dict) -> dict:
    try:
        p = handler_a(p)
    except ValueError:
        p = value_error_handler(p)
    p = finalize(p)
    return p
"""
        monkeypatch.setenv("ASYA_HANDLER_HANDLER_A", "handler_a")
        monkeypatch.setenv("ASYA_HANDLER_VALUE_ERROR_HANDLER", "value_error_handler")
        monkeypatch.setenv("ASYA_HANDLER_FINALIZE", "finalize")

        mod = compile_and_import(source)
        monkeypatch.setattr(mod, "resolve", lambda name: name)

        dispatch_name, dispatch_fn = _find_function(mod, "except_dispatch")
        assert dispatch_name is not None, "except_dispatch router not found"

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = setup_vfs(
                tmpdir,
                prev=[],
                next_actors=["placeholder"],
                error_type="CustomError",
                error_message="custom error that inherits from ValueError",
                error_mro=["ValueError", "Exception"],
            )
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)

            dispatch_fn({"data": "test"})

            # Should match via MRO
            inserted = read_vfs_next(vfs_root)
            assert "value_error_handler" in inserted

            # Error status should be cleared
            assert not vfs_error_exists(vfs_root)

    # -- Test: bare except catches all errors ------------------------------

    def test_except_dispatch_bare_except_catches_all(self, compile_and_import, monkeypatch):
        source = """\
def flow(p: dict) -> dict:
    try:
        p = handler_a(p)
    except:
        p = catch_all_handler(p)
    p = finalize(p)
    return p
"""
        monkeypatch.setenv("ASYA_HANDLER_HANDLER_A", "handler_a")
        monkeypatch.setenv("ASYA_HANDLER_CATCH_ALL_HANDLER", "catch_all_handler")
        monkeypatch.setenv("ASYA_HANDLER_FINALIZE", "finalize")

        mod = compile_and_import(source)
        monkeypatch.setattr(mod, "resolve", lambda name: name)

        dispatch_name, dispatch_fn = _find_function(mod, "except_dispatch")
        assert dispatch_name is not None, "except_dispatch router not found"

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = setup_vfs(
                tmpdir,
                prev=[],
                next_actors=["placeholder"],
                error_type="SomeUnknownError",
                error_message="something broke",
                error_mro=["BaseException"],
            )
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)

            dispatch_fn({"data": "test"})

            # Should route to the catch-all handler
            inserted = read_vfs_next(vfs_root)
            assert "catch_all_handler" in inserted

            # No reraise router should exist for bare except flows
            reraise_name, _ = _find_function(mod, "reraise")
            assert reraise_name is None, "reraise router should not exist with bare except"

    # -- Test: unmatched error routes to reraise ---------------------------

    def test_except_dispatch_unmatched_routes_to_reraise(self, compile_and_import, monkeypatch):
        source = """\
def flow(p: dict) -> dict:
    try:
        p = handler_a(p)
    except ValueError:
        p = value_error_handler(p)
    p = finalize(p)
    return p
"""
        monkeypatch.setenv("ASYA_HANDLER_HANDLER_A", "handler_a")
        monkeypatch.setenv("ASYA_HANDLER_VALUE_ERROR_HANDLER", "value_error_handler")
        monkeypatch.setenv("ASYA_HANDLER_FINALIZE", "finalize")

        mod = compile_and_import(source)
        monkeypatch.setattr(mod, "resolve", lambda name: name)

        dispatch_name, dispatch_fn = _find_function(mod, "except_dispatch")
        assert dispatch_name is not None, "except_dispatch router not found"

        reraise_name, _ = _find_function(mod, "reraise")
        assert reraise_name is not None, "reraise router should exist when no bare except"

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = setup_vfs(
                tmpdir,
                prev=[],
                next_actors=["placeholder"],
                error_type="KeyError",
                error_message="missing key",
                error_mro=["LookupError", "Exception"],
            )
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)

            dispatch_fn({"data": "test"})

            # Should route to reraise since no handler matches
            inserted = read_vfs_next(vfs_root)
            assert reraise_name in inserted

            # value_error_handler should NOT be in the route
            assert "value_error_handler" not in inserted

            # Error status should NOT be cleared (unmatched)
            assert vfs_error_exists(vfs_root)

    # -- Test: reraise raises RuntimeError ---------------------------------

    def test_reraise_raises_runtime_error(self, compile_and_import, monkeypatch):
        source = """\
def flow(p: dict) -> dict:
    try:
        p = handler_a(p)
    except ValueError:
        p = error_handler(p)
    return p
"""
        monkeypatch.setenv("ASYA_HANDLER_HANDLER_A", "handler_a")
        monkeypatch.setenv("ASYA_HANDLER_ERROR_HANDLER", "error_handler")

        mod = compile_and_import(source)
        monkeypatch.setattr(mod, "resolve", lambda name: name)

        reraise_name, reraise_fn = _find_function(mod, "reraise")
        assert reraise_name is not None, "reraise router should exist"

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = setup_vfs(
                tmpdir,
                prev=[],
                next_actors=[],
                error_type="KeyError",
                error_message="missing key 'x'",
                error_mro=["LookupError", "Exception"],
            )
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)

            with pytest.raises(RuntimeError, match="Unhandled exception"):
                reraise_fn({"data": "test"})

    # -- Test: try-except with finally clause ------------------------------

    def test_try_exit_inserts_finally_and_continuation(self, compile_and_import, monkeypatch):
        source = """\
def flow(p: dict) -> dict:
    try:
        p = handler_a(p)
    except ValueError:
        p = error_handler(p)
    finally:
        p = cleanup(p)
    p = finalize(p)
    return p
"""
        monkeypatch.setenv("ASYA_HANDLER_HANDLER_A", "handler_a")
        monkeypatch.setenv("ASYA_HANDLER_ERROR_HANDLER", "error_handler")
        monkeypatch.setenv("ASYA_HANDLER_CLEANUP", "cleanup")
        monkeypatch.setenv("ASYA_HANDLER_FINALIZE", "finalize")

        mod = compile_and_import(source)
        monkeypatch.setattr(mod, "resolve", lambda name: name)

        try_exit_name, try_exit_fn = _find_function(mod, "try_exit")
        assert try_exit_name is not None, "try_exit router not found"

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = setup_vfs(
                tmpdir,
                prev=["start_flow", "try_enter", "handler_a"],
                next_actors=[],
                headers={"_on_error": "some-dispatch"},
            )
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)

            try_exit_fn({"data": "test"})

            # _on_error should be cleared
            assert not vfs_header_exists(vfs_root, "_on_error")

            # Both cleanup (finally) and finalize (continuation) should be prepended to next
            inserted = read_vfs_next(vfs_root)
            assert "cleanup" in inserted
            assert "finalize" in inserted

            # cleanup (finally) should come before finalize (continuation)
            cleanup_idx = inserted.index("cleanup")
            finalize_idx = inserted.index("finalize")
            assert cleanup_idx < finalize_idx

    def test_except_dispatch_with_finally_inserts_finally_actors(self, compile_and_import, monkeypatch):
        source = """\
def flow(p: dict) -> dict:
    try:
        p = handler_a(p)
    except ValueError:
        p = error_handler(p)
    finally:
        p = cleanup(p)
    p = finalize(p)
    return p
"""
        monkeypatch.setenv("ASYA_HANDLER_HANDLER_A", "handler_a")
        monkeypatch.setenv("ASYA_HANDLER_ERROR_HANDLER", "error_handler")
        monkeypatch.setenv("ASYA_HANDLER_CLEANUP", "cleanup")
        monkeypatch.setenv("ASYA_HANDLER_FINALIZE", "finalize")

        mod = compile_and_import(source)
        monkeypatch.setattr(mod, "resolve", lambda name: name)

        dispatch_name, dispatch_fn = _find_function(mod, "except_dispatch")
        assert dispatch_name is not None, "except_dispatch router not found"

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = setup_vfs(
                tmpdir,
                prev=[],
                next_actors=["placeholder"],
                error_type="ValueError",
                error_message="invalid value",
                error_mro=["Exception"],
            )
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)

            dispatch_fn({"data": "test"})

            # error_handler, cleanup (finally), and finalize (continuation) should all be in next
            inserted = read_vfs_next(vfs_root)
            assert "error_handler" in inserted
            assert "cleanup" in inserted
            assert "finalize" in inserted

            # Order: error_handler < cleanup < finalize
            eh_idx = inserted.index("error_handler")
            cleanup_idx = inserted.index("cleanup")
            finalize_idx = inserted.index("finalize")
            assert eh_idx < cleanup_idx < finalize_idx

    # -- Test: multiple except handlers ------------------------------------

    def test_except_dispatch_multiple_handlers(self, compile_and_import, monkeypatch):
        source = """\
def flow(p: dict) -> dict:
    try:
        p = handler_a(p)
    except ValueError:
        p = value_handler(p)
    except TypeError:
        p = type_handler(p)
    except KeyError:
        p = key_handler(p)
    p = finalize(p)
    return p
"""
        monkeypatch.setenv("ASYA_HANDLER_HANDLER_A", "handler_a")
        monkeypatch.setenv("ASYA_HANDLER_VALUE_HANDLER", "value_handler")
        monkeypatch.setenv("ASYA_HANDLER_TYPE_HANDLER", "type_handler")
        monkeypatch.setenv("ASYA_HANDLER_KEY_HANDLER", "key_handler")
        monkeypatch.setenv("ASYA_HANDLER_FINALIZE", "finalize")

        mod = compile_and_import(source)
        monkeypatch.setattr(mod, "resolve", lambda name: name)

        dispatch_name, dispatch_fn = _find_function(mod, "except_dispatch")
        assert dispatch_name is not None

        # Test ValueError match
        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = setup_vfs(
                tmpdir,
                prev=[],
                next_actors=["ph"],
                error_type="ValueError",
                error_message="bad",
                error_mro=["Exception"],
            )
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)
            dispatch_fn({"data": "test"})
            inserted = read_vfs_next(vfs_root)
            assert "value_handler" in inserted
            assert "type_handler" not in inserted
            assert "key_handler" not in inserted

        # Test TypeError match
        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = setup_vfs(
                tmpdir,
                prev=[],
                next_actors=["ph"],
                error_type="TypeError",
                error_message="bad",
                error_mro=["Exception"],
            )
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)
            dispatch_fn({"data": "test"})
            inserted = read_vfs_next(vfs_root)
            assert "type_handler" in inserted
            assert "value_handler" not in inserted

        # Test KeyError match
        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = setup_vfs(
                tmpdir,
                prev=[],
                next_actors=["ph"],
                error_type="KeyError",
                error_message="bad",
                error_mro=["LookupError", "Exception"],
            )
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)
            dispatch_fn({"data": "test"})
            inserted = read_vfs_next(vfs_root)
            assert "key_handler" in inserted
            assert "value_handler" not in inserted

    # -- Test: tuple except (multiple types in one handler) ----------------

    def test_except_dispatch_tuple_types(self, compile_and_import, monkeypatch):
        source = """\
def flow(p: dict) -> dict:
    try:
        p = handler_a(p)
    except (ValueError, TypeError):
        p = combined_handler(p)
    p = finalize(p)
    return p
"""
        monkeypatch.setenv("ASYA_HANDLER_HANDLER_A", "handler_a")
        monkeypatch.setenv("ASYA_HANDLER_COMBINED_HANDLER", "combined_handler")
        monkeypatch.setenv("ASYA_HANDLER_FINALIZE", "finalize")

        mod = compile_and_import(source)
        monkeypatch.setattr(mod, "resolve", lambda name: name)

        dispatch_name, dispatch_fn = _find_function(mod, "except_dispatch")
        assert dispatch_name is not None

        reraise_name, _ = _find_function(mod, "reraise")
        assert reraise_name is not None

        # ValueError should match
        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = setup_vfs(
                tmpdir,
                prev=[],
                next_actors=["ph"],
                error_type="ValueError",
                error_message="bad",
                error_mro=["Exception"],
            )
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)
            dispatch_fn({"data": "test"})
            inserted = read_vfs_next(vfs_root)
            assert "combined_handler" in inserted

        # TypeError should also match
        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = setup_vfs(
                tmpdir,
                prev=[],
                next_actors=["ph"],
                error_type="TypeError",
                error_message="bad",
                error_mro=["Exception"],
            )
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)
            dispatch_fn({"data": "test"})
            inserted = read_vfs_next(vfs_root)
            assert "combined_handler" in inserted

        # KeyError should NOT match, should go to reraise
        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = setup_vfs(
                tmpdir,
                prev=[],
                next_actors=["ph"],
                error_type="KeyError",
                error_message="bad",
                error_mro=["LookupError", "Exception"],
            )
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)
            dispatch_fn({"data": "test"})
            inserted = read_vfs_next(vfs_root)
            assert reraise_name in inserted
            assert "combined_handler" not in inserted

    # -- Test: end-to-end success path (start -> try_enter -> try_exit) ----

    def test_full_success_path(self, compile_and_import, monkeypatch):
        source = """\
def flow(p: dict) -> dict:
    try:
        p = handler_a(p)
    except ValueError:
        p = error_handler(p)
    p = finalize(p)
    return p
"""
        monkeypatch.setenv("ASYA_HANDLER_HANDLER_A", "handler_a")
        monkeypatch.setenv("ASYA_HANDLER_ERROR_HANDLER", "error_handler")
        monkeypatch.setenv("ASYA_HANDLER_FINALIZE", "finalize")

        mod = compile_and_import(source)
        monkeypatch.setattr(mod, "resolve", lambda name: name)

        try_enter_name, try_enter_fn = _find_function(mod, "try_enter")
        try_exit_name, try_exit_fn = _find_function(mod, "try_exit")

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = setup_vfs(tmpdir, prev=[], next_actors=[])
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)

            # Step 1: call start_flow
            start_fn = mod.start_flow
            start_fn({"data": "test"})

            # start_flow should prepend the try_enter router into next
            assert try_enter_name in read_vfs_next(vfs_root)

            # Step 2: simulate runtime shifting route to try_enter, then call try_enter
            write_vfs_prev(vfs_root, ["start_flow"])
            write_vfs_next(vfs_root, [a for a in read_vfs_next(vfs_root) if a != try_enter_name])
            try_enter_fn({"data": "test"})

            # Should set _on_error header
            assert vfs_header_exists(vfs_root, "_on_error")

            # Should insert handler_a and try_exit into next
            next_after_enter = read_vfs_next(vfs_root)
            assert "handler_a" in next_after_enter
            assert try_exit_name in next_after_enter

            # Step 3: simulate runtime advancing to try_exit (handler_a was handled by runtime)
            write_vfs_prev(vfs_root, ["start_flow", try_enter_name, "handler_a"])
            write_vfs_next(vfs_root, [a for a in next_after_enter if a not in ["handler_a", try_exit_name]])
            try_exit_fn({"data": "test"})

            # _on_error should be cleared
            assert not vfs_header_exists(vfs_root, "_on_error")

            # finalize should be in next
            assert "finalize" in read_vfs_next(vfs_root)

    # -- Test: payload is preserved through routers ------------------------

    def test_payload_preserved_through_try_enter(self, compile_and_import, monkeypatch):
        source = """\
def flow(p: dict) -> dict:
    try:
        p = handler_a(p)
    except ValueError:
        p = error_handler(p)
    return p
"""
        monkeypatch.setenv("ASYA_HANDLER_HANDLER_A", "handler_a")
        monkeypatch.setenv("ASYA_HANDLER_ERROR_HANDLER", "error_handler")

        mod = compile_and_import(source)
        monkeypatch.setattr(mod, "resolve", lambda name: name)

        try_enter_name, try_enter_fn = _find_function(mod, "try_enter")
        assert try_enter_name is not None

        original_payload = {"key1": "value1", "key2": [1, 2, 3], "nested": {"a": "b"}}

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = setup_vfs(tmpdir, prev=["start_flow"], next_actors=[])
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)

            result_payload = try_enter_fn(dict(original_payload))

            # Payload should be untouched by try_enter router
            assert result_payload == original_payload

    # -- Test: message id is preserved through all routers -----------------

    def test_message_id_preserved(self, compile_and_import, monkeypatch):
        source = """\
def flow(p: dict) -> dict:
    try:
        p = handler_a(p)
    except ValueError:
        p = error_handler(p)
    return p
"""
        monkeypatch.setenv("ASYA_HANDLER_HANDLER_A", "handler_a")
        monkeypatch.setenv("ASYA_HANDLER_ERROR_HANDLER", "error_handler")

        mod = compile_and_import(source)
        monkeypatch.setattr(mod, "resolve", lambda name: name)

        try_enter_name, try_enter_fn = _find_function(mod, "try_enter")
        try_exit_name, try_exit_fn = _find_function(mod, "try_exit")
        dispatch_name, dispatch_fn = _find_function(mod, "except_dispatch")

        payload = {"id": "test-msg", "data": "test"}

        # Check try_enter returns same payload object with id preserved
        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = setup_vfs(tmpdir, prev=["start"], next_actors=[])
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)
            result = try_enter_fn(dict(payload))
            assert result["id"] == "test-msg"

        # Check try_exit returns same payload object with id preserved
        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = setup_vfs(
                tmpdir,
                prev=["start"],
                next_actors=[],
                headers={"_on_error": "dispatch"},
            )
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)
            result2 = try_exit_fn(dict(payload))
            assert result2["id"] == "test-msg"

        # Check except_dispatch returns same payload object with id preserved
        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = setup_vfs(
                tmpdir,
                prev=[],
                next_actors=["ph"],
                error_type="ValueError",
                error_message="bad",
                error_mro=[],
            )
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)
            result3 = dispatch_fn(dict(payload))
            assert result3["id"] == "test-msg"

    # -- Test: reraise error message content -------------------------------

    def test_reraise_error_message_includes_details(self, compile_and_import, monkeypatch):
        source = """\
def flow(p: dict) -> dict:
    try:
        p = handler_a(p)
    except ValueError:
        p = error_handler(p)
    return p
"""
        monkeypatch.setenv("ASYA_HANDLER_HANDLER_A", "handler_a")
        monkeypatch.setenv("ASYA_HANDLER_ERROR_HANDLER", "error_handler")

        mod = compile_and_import(source)
        monkeypatch.setattr(mod, "resolve", lambda name: name)

        reraise_name, reraise_fn = _find_function(mod, "reraise")
        assert reraise_name is not None

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = setup_vfs(
                tmpdir,
                prev=[],
                next_actors=[],
                error_type="KeyError",
                error_message="missing key 'important_field'",
                error_mro=["LookupError", "Exception"],
            )
            monkeypatch.setattr(mod, "_MSG_ROOT", vfs_root)

            with pytest.raises(RuntimeError, match="KeyError") as exc_info:
                reraise_fn({"data": "test"})

            assert "missing key" in str(exc_info.value)
