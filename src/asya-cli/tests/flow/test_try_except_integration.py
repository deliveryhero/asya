"""Integration tests for try-except flow compilation.

These tests exercise the full compilation pipeline (parse -> group -> codegen)
and validate that the generated router code correctly manipulates message routes,
headers, and status fields for try-except error handling patterns.
"""

import copy
import importlib
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


def make_message(
    payload: dict,
    prev: list[str] | None = None,
    curr: str = "",
    next_actors: list[str] | None = None,
    headers: dict | None = None,
    status: dict | None = None,
) -> dict:
    """Create a test message with route structure."""
    msg: dict = {
        "id": "test-msg",
        "route": {
            "prev": prev or [],
            "curr": curr,
            "next": next_actors or [],
        },
        "payload": payload,
    }
    if headers is not None:
        msg["headers"] = headers
    if status is not None:
        msg["status"] = status
    return msg


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
        # Override resolve to return the handler name as the actor name
        monkeypatch.setattr(mod, "resolve", lambda name: name)

        # Find the try_enter function
        try_enter_name, try_enter_fn = _find_function(mod, "try_enter")
        assert try_enter_name is not None, "try_enter router not found"

        # Find the except_dispatch name for verification
        except_dispatch_name, _ = _find_function(mod, "except_dispatch")
        assert except_dispatch_name is not None, "except_dispatch router not found"

        # Find the try_exit name for verification
        try_exit_name, _ = _find_function(mod, "try_exit")
        assert try_exit_name is not None, "try_exit router not found"

        msg = make_message(
            {"data": "test"},
            prev=["start_flow"],
            curr=try_enter_name,
            next_actors=[],
        )

        result = try_enter_fn(msg)

        # _on_error header should be set to the except_dispatch router
        assert "headers" in result
        assert "_on_error" in result["headers"]
        assert result["headers"]["_on_error"] == except_dispatch_name

        # Body actors (handler_a, handler_b) and try_exit should be prepended to next
        inserted = result["route"]["next"]
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

        # Simulate a message arriving at try_exit (success path)
        msg = make_message(
            {"data": "test"},
            prev=["start_flow", "try_enter", "handler_a"],
            curr=try_exit_name,
            next_actors=[],
            headers={"_on_error": "some-except-dispatch", "trace_id": "abc"},
        )

        result = try_exit_fn(msg)

        # _on_error header should be removed
        assert "_on_error" not in result.get("headers", {})
        # Other headers should be preserved
        assert result["headers"]["trace_id"] == "abc"

        # Continuation actors (finalize) should be prepended to next
        inserted = result["route"]["next"]
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

        msg = make_message(
            {"data": "test"},
            prev=[],
            curr=dispatch_name,
            next_actors=["placeholder"],
            status={
                "error": {
                    "type": "ValueError",
                    "message": "invalid value",
                    "mro": ["Exception"],
                }
            },
        )

        result = dispatch_fn(msg)

        # Should route to the ValueError handler
        inserted = result["route"]["next"]
        assert "error_handler" in inserted

        # Error status should be cleared on match
        error_status = result.get("status", {}).get("error")
        assert error_status is None

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

        # Error type is "CustomError" but mro contains "ValueError"
        msg = make_message(
            {"data": "test"},
            prev=[],
            curr=dispatch_name,
            next_actors=["placeholder"],
            status={
                "error": {
                    "type": "CustomError",
                    "message": "custom error that inherits from ValueError",
                    "mro": ["ValueError", "Exception"],
                }
            },
        )

        result = dispatch_fn(msg)

        # Should match via MRO
        inserted = result["route"]["next"]
        assert "value_error_handler" in inserted

        # Error status should be cleared
        error_status = result.get("status", {}).get("error")
        assert error_status is None

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

        # Any error type should match bare except
        msg = make_message(
            {"data": "test"},
            prev=[],
            curr=dispatch_name,
            next_actors=["placeholder"],
            status={
                "error": {
                    "type": "SomeUnknownError",
                    "message": "something broke",
                    "mro": ["BaseException"],
                }
            },
        )

        result = dispatch_fn(msg)

        # Should route to the catch-all handler
        inserted = result["route"]["next"]
        assert "catch_all_handler" in inserted

        # Error status should be cleared
        error_status = result.get("status", {}).get("error")
        assert error_status is None

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

        # Error type is "KeyError" but only "except ValueError:" handler exists
        msg = make_message(
            {"data": "test"},
            prev=[],
            curr=dispatch_name,
            next_actors=["placeholder"],
            status={
                "error": {
                    "type": "KeyError",
                    "message": "missing key",
                    "mro": ["LookupError", "Exception"],
                }
            },
        )

        result = dispatch_fn(msg)

        # Should route to reraise since no handler matches
        inserted = result["route"]["next"]
        assert reraise_name in inserted

        # value_error_handler should NOT be in the route
        assert "value_error_handler" not in inserted

        # Error status should NOT be cleared (unmatched)
        error_status = result.get("status", {}).get("error")
        assert error_status is not None
        assert error_status["type"] == "KeyError"

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

        msg = make_message(
            {"data": "test"},
            prev=[],
            curr=reraise_name,
            next_actors=[],
            status={
                "error": {
                    "type": "KeyError",
                    "message": "missing key 'x'",
                    "mro": ["LookupError", "Exception"],
                }
            },
        )

        with pytest.raises(RuntimeError, match="Unhandled exception"):
            reraise_fn(msg)

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

        msg = make_message(
            {"data": "test"},
            prev=["start_flow", "try_enter", "handler_a"],
            curr=try_exit_name,
            next_actors=[],
            headers={"_on_error": "some-dispatch"},
        )

        result = try_exit_fn(msg)

        # _on_error should be cleared
        assert "_on_error" not in result.get("headers", {})

        # Both cleanup (finally) and finalize (continuation) should be prepended to next
        inserted = result["route"]["next"]
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

        msg = make_message(
            {"data": "test"},
            prev=[],
            curr=dispatch_name,
            next_actors=["placeholder"],
            status={
                "error": {
                    "type": "ValueError",
                    "message": "invalid value",
                    "mro": ["Exception"],
                }
            },
        )

        result = dispatch_fn(msg)

        # error_handler, cleanup (finally), and finalize (continuation) should all be in next
        inserted = result["route"]["next"]
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
        msg_value = make_message(
            {"data": "test"},
            prev=[],
            curr=dispatch_name,
            next_actors=["ph"],
            status={"error": {"type": "ValueError", "message": "bad", "mro": ["Exception"]}},
        )
        result = dispatch_fn(copy.deepcopy(msg_value))
        inserted = result["route"]["next"]
        assert "value_handler" in inserted
        assert "type_handler" not in inserted
        assert "key_handler" not in inserted

        # Test TypeError match
        msg_type = make_message(
            {"data": "test"},
            prev=[],
            curr=dispatch_name,
            next_actors=["ph"],
            status={"error": {"type": "TypeError", "message": "bad", "mro": ["Exception"]}},
        )
        result = dispatch_fn(copy.deepcopy(msg_type))
        inserted = result["route"]["next"]
        assert "type_handler" in inserted
        assert "value_handler" not in inserted

        # Test KeyError match
        msg_key = make_message(
            {"data": "test"},
            prev=[],
            curr=dispatch_name,
            next_actors=["ph"],
            status={"error": {"type": "KeyError", "message": "bad", "mro": ["LookupError", "Exception"]}},
        )
        result = dispatch_fn(copy.deepcopy(msg_key))
        inserted = result["route"]["next"]
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

        # ValueError should match
        msg_val = make_message(
            {"data": "test"},
            prev=[],
            curr=dispatch_name,
            next_actors=["ph"],
            status={"error": {"type": "ValueError", "message": "bad", "mro": ["Exception"]}},
        )
        result = dispatch_fn(copy.deepcopy(msg_val))
        inserted = result["route"]["next"]
        assert "combined_handler" in inserted

        # TypeError should also match
        msg_type = make_message(
            {"data": "test"},
            prev=[],
            curr=dispatch_name,
            next_actors=["ph"],
            status={"error": {"type": "TypeError", "message": "bad", "mro": ["Exception"]}},
        )
        result = dispatch_fn(copy.deepcopy(msg_type))
        inserted = result["route"]["next"]
        assert "combined_handler" in inserted

        # KeyError should NOT match, should go to reraise
        reraise_name, _ = _find_function(mod, "reraise")
        assert reraise_name is not None

        msg_key = make_message(
            {"data": "test"},
            prev=[],
            curr=dispatch_name,
            next_actors=["ph"],
            status={"error": {"type": "KeyError", "message": "bad", "mro": ["LookupError", "Exception"]}},
        )
        result = dispatch_fn(copy.deepcopy(msg_key))
        inserted = result["route"]["next"]
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

        # Step 1: call start_flow
        start_fn = mod.start_flow
        msg = make_message({"data": "test"}, prev=[], curr="start_flow", next_actors=[])
        msg = start_fn(msg)

        # start_flow should prepend the try_enter router into next
        try_enter_name, try_enter_fn = _find_function(mod, "try_enter")
        assert try_enter_name in msg["route"]["next"]

        # Step 2: simulate runtime shifting route to try_enter, then call try_enter
        msg["route"]["prev"] = ["start_flow"]
        msg["route"]["curr"] = try_enter_name
        msg["route"]["next"] = [a for a in msg["route"]["next"] if a != try_enter_name]
        msg = try_enter_fn(msg)

        # Should set _on_error header
        assert "_on_error" in msg.get("headers", {})

        # Should insert handler_a and try_exit into next
        try_exit_name, try_exit_fn = _find_function(mod, "try_exit")
        assert "handler_a" in msg["route"]["next"]
        assert try_exit_name in msg["route"]["next"]

        # Step 3: simulate runtime shifting route to handler_a
        msg["route"]["prev"] = ["start_flow", try_enter_name]
        msg["route"]["curr"] = "handler_a"
        msg["route"]["next"] = [a for a in msg["route"]["next"] if a != "handler_a"]

        # Step 4: simulate runtime shifting route to try_exit, then call try_exit
        msg["route"]["prev"] = ["start_flow", try_enter_name, "handler_a"]
        msg["route"]["curr"] = try_exit_name
        msg["route"]["next"] = [a for a in msg["route"]["next"] if a != try_exit_name]
        msg = try_exit_fn(msg)

        # _on_error should be cleared
        assert "_on_error" not in msg.get("headers", {})

        # finalize should be in next
        assert "finalize" in msg["route"]["next"]

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
        msg = make_message(
            original_payload,
            prev=["start_flow"],
            curr=try_enter_name,
            next_actors=[],
        )

        result = try_enter_fn(msg)

        # Payload should be untouched by try_enter router
        assert result["payload"] == original_payload

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

        # Check try_enter preserves id
        msg = make_message({"data": "test"}, prev=["start"], curr=try_enter_name, next_actors=[])
        result = try_enter_fn(msg)
        assert result["id"] == "test-msg"

        # Check try_exit preserves id
        msg2 = make_message(
            {"data": "test"},
            prev=["start"],
            curr=try_exit_name,
            next_actors=[],
            headers={"_on_error": "dispatch"},
        )
        result2 = try_exit_fn(msg2)
        assert result2["id"] == "test-msg"

        # Check except_dispatch preserves id
        msg3 = make_message(
            {"data": "test"},
            prev=[],
            curr=dispatch_name,
            next_actors=["ph"],
            status={"error": {"type": "ValueError", "message": "bad", "mro": []}},
        )
        result3 = dispatch_fn(msg3)
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

        msg = make_message(
            {"data": "test"},
            prev=[],
            curr=reraise_name,
            next_actors=[],
            status={
                "error": {
                    "type": "KeyError",
                    "message": "missing key 'important_field'",
                    "mro": ["LookupError", "Exception"],
                }
            },
        )

        with pytest.raises(RuntimeError, match="KeyError") as exc_info:
            reraise_fn(msg)

        assert "missing key" in str(exc_info.value)
