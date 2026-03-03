"""Integration tests for try-except flow compilation.

These tests exercise the full compilation pipeline (parse -> group -> codegen)
and validate that the generated router code correctly manipulates envelope routes,
headers, and status fields for try-except error handling patterns via ABI yields.
"""

import contextlib
import importlib
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest
from asya_cli.flow.compiler import FlowCompiler


# ---------------------------------------------------------------------------
# ABI driver helpers
# ---------------------------------------------------------------------------


def _resolve_path(data: dict, path: str) -> Any:
    """Resolve a dotted path on a nested dict. Leading dot is stripped."""
    parts = path.lstrip(".").split(".")
    cur: Any = data
    for p in parts:
        cur = cur[p]
    return cur


def _set_path(data: dict, path: str, value: Any) -> None:
    """Set a value at a dotted path on a nested dict. Leading dot is stripped."""
    parts = path.lstrip(".").split(".")
    cur = data
    last = parts[-1]
    for p in parts[:-1]:
        if p not in cur:
            cur[p] = {}
        cur = cur[p]
    m = re.match(r"^(\w+)\[(-?\d*):(-?\d*)\]$", last)
    if m:
        key = m.group(1)
        start = int(m.group(2)) if m.group(2) else None
        stop = int(m.group(3)) if m.group(3) else None
        cur[key][start:stop] = value
    else:
        cur[last] = value


def _del_path(data: dict, path: str) -> None:
    """Delete a value at a dotted path on a nested dict. Leading dot is stripped."""
    parts = path.lstrip(".").split(".")
    cur = data
    for p in parts[:-1]:
        cur = cur[p]
    del cur[parts[-1]]


def _drive_abi_single(gen, msg_ctx: dict) -> Any:
    """Drive an ABI generator that yields exactly one payload frame. Returns the payload."""
    value = gen.send(None)
    while True:
        if (
            isinstance(value, tuple)
            and len(value) >= 2
            and isinstance(value[0], str)
            and value[0] in ("GET", "SET", "DEL")
        ):
            op = value[0]
            if op == "GET":
                result = _resolve_path(msg_ctx, value[1])
                value = gen.send(result)
            elif op == "SET":
                _set_path(msg_ctx, value[1], value[2])
                value = gen.send(None)
            elif op == "DEL":
                _del_path(msg_ctx, value[1])
                value = gen.send(None)
        else:
            # Payload frame -- consume remaining
            payload = value
            with contextlib.suppress(StopIteration):
                gen.send(None)
            return payload


def _make_msg_ctx(
    prev: list[str] | None = None,
    next_actors: list[str] | None = None,
    headers: dict[str, str] | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    error_mro: list[str] | None = None,
) -> dict:
    """Create a message context dict for ABI-based tests."""
    ctx: dict[str, Any] = {
        "id": "test-msg",
        "route": {
            "prev": prev or [],
            "next": next_actors or [],
        },
        "headers": dict(headers) if headers else {},
    }
    if error_type is not None:
        ctx["status"] = {
            "error": {
                "type": error_type,
                "message": error_message or "",
                "mro": error_mro or [],
            }
        }
    return ctx


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
# Helpers
# ---------------------------------------------------------------------------


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

        msg_ctx = _make_msg_ctx(prev=["start_flow"], next_actors=[])
        _drive_abi_single(try_enter_fn({"data": "test"}), msg_ctx)

        # _on_error header should be set to the except_dispatch router
        assert "_on_error" in msg_ctx["headers"]
        assert msg_ctx["headers"]["_on_error"] == except_dispatch_name

        # Body actors (handler_a, handler_b) and try_exit should be prepended to next
        inserted = msg_ctx["route"]["next"]
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

        msg_ctx = _make_msg_ctx(
            prev=["start_flow", "try_enter", "handler_a"],
            next_actors=[],
            headers={"_on_error": "some-except-dispatch", "trace_id": "abc"},
        )
        _drive_abi_single(try_exit_fn({"data": "test"}), msg_ctx)

        # _on_error header should be removed
        assert "_on_error" not in msg_ctx["headers"]
        # trace_id should still exist
        assert msg_ctx["headers"].get("trace_id") == "abc"

        # Continuation actors (finalize) should be prepended to next
        inserted = msg_ctx["route"]["next"]
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

        msg_ctx = _make_msg_ctx(
            prev=[],
            next_actors=["placeholder"],
            error_type="ValueError",
            error_message="invalid value",
            error_mro=["Exception"],
        )
        _drive_abi_single(dispatch_fn({"data": "test"}), msg_ctx)

        # Should route to the ValueError handler
        inserted = msg_ctx["route"]["next"]
        assert "error_handler" in inserted

        # Error status should be cleared on match
        assert "error" not in msg_ctx.get("status", {})

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

        msg_ctx = _make_msg_ctx(
            prev=[],
            next_actors=["placeholder"],
            error_type="CustomError",
            error_message="custom error that inherits from ValueError",
            error_mro=["ValueError", "Exception"],
        )
        _drive_abi_single(dispatch_fn({"data": "test"}), msg_ctx)

        # Should match via MRO
        inserted = msg_ctx["route"]["next"]
        assert "value_error_handler" in inserted

        # Error status should be cleared
        assert "error" not in msg_ctx.get("status", {})

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

        msg_ctx = _make_msg_ctx(
            prev=[],
            next_actors=["placeholder"],
            error_type="SomeUnknownError",
            error_message="something broke",
            error_mro=["BaseException"],
        )
        _drive_abi_single(dispatch_fn({"data": "test"}), msg_ctx)

        # Should route to the catch-all handler
        inserted = msg_ctx["route"]["next"]
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

        msg_ctx = _make_msg_ctx(
            prev=[],
            next_actors=["placeholder"],
            error_type="KeyError",
            error_message="missing key",
            error_mro=["LookupError", "Exception"],
        )
        _drive_abi_single(dispatch_fn({"data": "test"}), msg_ctx)

        # Should route to reraise since no handler matches
        inserted = msg_ctx["route"]["next"]
        assert reraise_name in inserted

        # value_error_handler should NOT be in the route
        assert "value_error_handler" not in inserted

        # Error status should NOT be cleared (unmatched)
        assert "error" in msg_ctx.get("status", {})

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

        msg_ctx = _make_msg_ctx(
            prev=[],
            next_actors=[],
            error_type="KeyError",
            error_message="missing key 'x'",
            error_mro=["LookupError", "Exception"],
        )

        with pytest.raises(RuntimeError, match="Unhandled exception"):
            _drive_abi_single(reraise_fn({"data": "test"}), msg_ctx)

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

        msg_ctx = _make_msg_ctx(
            prev=["start_flow", "try_enter", "handler_a"],
            next_actors=[],
            headers={"_on_error": "some-dispatch"},
        )
        _drive_abi_single(try_exit_fn({"data": "test"}), msg_ctx)

        # _on_error should be cleared
        assert "_on_error" not in msg_ctx["headers"]

        # Both cleanup (finally) and finalize (continuation) should be prepended to next
        inserted = msg_ctx["route"]["next"]
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

        msg_ctx = _make_msg_ctx(
            prev=[],
            next_actors=["placeholder"],
            error_type="ValueError",
            error_message="invalid value",
            error_mro=["Exception"],
        )
        _drive_abi_single(dispatch_fn({"data": "test"}), msg_ctx)

        # error_handler, cleanup (finally), and finalize (continuation) should all be in next
        inserted = msg_ctx["route"]["next"]
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
        msg_ctx = _make_msg_ctx(
            prev=[],
            next_actors=["ph"],
            error_type="ValueError",
            error_message="bad",
            error_mro=["Exception"],
        )
        _drive_abi_single(dispatch_fn({"data": "test"}), msg_ctx)
        inserted = msg_ctx["route"]["next"]
        assert "value_handler" in inserted
        assert "type_handler" not in inserted
        assert "key_handler" not in inserted

        # Test TypeError match
        msg_ctx = _make_msg_ctx(
            prev=[],
            next_actors=["ph"],
            error_type="TypeError",
            error_message="bad",
            error_mro=["Exception"],
        )
        _drive_abi_single(dispatch_fn({"data": "test"}), msg_ctx)
        inserted = msg_ctx["route"]["next"]
        assert "type_handler" in inserted
        assert "value_handler" not in inserted

        # Test KeyError match
        msg_ctx = _make_msg_ctx(
            prev=[],
            next_actors=["ph"],
            error_type="KeyError",
            error_message="bad",
            error_mro=["LookupError", "Exception"],
        )
        _drive_abi_single(dispatch_fn({"data": "test"}), msg_ctx)
        inserted = msg_ctx["route"]["next"]
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
        msg_ctx = _make_msg_ctx(
            prev=[],
            next_actors=["ph"],
            error_type="ValueError",
            error_message="bad",
            error_mro=["Exception"],
        )
        _drive_abi_single(dispatch_fn({"data": "test"}), msg_ctx)
        inserted = msg_ctx["route"]["next"]
        assert "combined_handler" in inserted

        # TypeError should also match
        msg_ctx = _make_msg_ctx(
            prev=[],
            next_actors=["ph"],
            error_type="TypeError",
            error_message="bad",
            error_mro=["Exception"],
        )
        _drive_abi_single(dispatch_fn({"data": "test"}), msg_ctx)
        inserted = msg_ctx["route"]["next"]
        assert "combined_handler" in inserted

        # KeyError should NOT match, should go to reraise
        msg_ctx = _make_msg_ctx(
            prev=[],
            next_actors=["ph"],
            error_type="KeyError",
            error_message="bad",
            error_mro=["LookupError", "Exception"],
        )
        _drive_abi_single(dispatch_fn({"data": "test"}), msg_ctx)
        inserted = msg_ctx["route"]["next"]
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

        # Step 1: call start_flow
        msg_ctx = _make_msg_ctx(prev=[], next_actors=[])
        start_fn = mod.start_flow
        _drive_abi_single(start_fn({"data": "test"}), msg_ctx)

        # start_flow should prepend the try_enter router into next
        assert try_enter_name in msg_ctx["route"]["next"]

        # Step 2: simulate runtime shifting route to try_enter, then call try_enter
        msg_ctx["route"]["prev"] = ["start_flow"]
        msg_ctx["route"]["next"] = [a for a in msg_ctx["route"]["next"] if a != try_enter_name]
        _drive_abi_single(try_enter_fn({"data": "test"}), msg_ctx)

        # Should set _on_error header
        assert "_on_error" in msg_ctx["headers"]

        # Should insert handler_a and try_exit into next
        next_after_enter = msg_ctx["route"]["next"]
        assert "handler_a" in next_after_enter
        assert try_exit_name in next_after_enter

        # Step 3: simulate runtime advancing to try_exit (handler_a was handled by runtime)
        msg_ctx["route"]["prev"] = ["start_flow", try_enter_name, "handler_a"]
        msg_ctx["route"]["next"] = [a for a in next_after_enter if a not in ["handler_a", try_exit_name]]
        _drive_abi_single(try_exit_fn({"data": "test"}), msg_ctx)

        # _on_error should be cleared
        assert "_on_error" not in msg_ctx["headers"]

        # finalize should be in next
        assert "finalize" in msg_ctx["route"]["next"]

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

        msg_ctx = _make_msg_ctx(prev=["start_flow"], next_actors=[])
        result_payload = _drive_abi_single(try_enter_fn(dict(original_payload)), msg_ctx)

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
        msg_ctx = _make_msg_ctx(prev=["start"], next_actors=[])
        result = _drive_abi_single(try_enter_fn(dict(payload)), msg_ctx)
        assert result["id"] == "test-msg"

        # Check try_exit returns same payload object with id preserved
        msg_ctx = _make_msg_ctx(
            prev=["start"],
            next_actors=[],
            headers={"_on_error": "dispatch"},
        )
        result2 = _drive_abi_single(try_exit_fn(dict(payload)), msg_ctx)
        assert result2["id"] == "test-msg"

        # Check except_dispatch returns same payload object with id preserved
        msg_ctx = _make_msg_ctx(
            prev=[],
            next_actors=["ph"],
            error_type="ValueError",
            error_message="bad",
            error_mro=[],
        )
        result3 = _drive_abi_single(dispatch_fn(dict(payload)), msg_ctx)
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

        msg_ctx = _make_msg_ctx(
            prev=[],
            next_actors=[],
            error_type="KeyError",
            error_message="missing key 'important_field'",
            error_mro=["LookupError", "Exception"],
        )

        with pytest.raises(RuntimeError, match="KeyError") as exc_info:
            _drive_abi_single(reraise_fn({"data": "test"}), msg_ctx)

        assert "missing key" in str(exc_info.value)
