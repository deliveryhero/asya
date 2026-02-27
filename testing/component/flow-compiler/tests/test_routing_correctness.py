"""Test routing correctness by executing compiled routers."""

import os
import tempfile
import textwrap
from pathlib import Path

import pytest

from asya_cli.flow import FlowCompiler


def _setup_vfs(tmpdir, prev, next_actors):
    """Create mock VFS directory structure for testing routers."""
    vfs_root = Path(tmpdir) / "vfs"
    route_dir = vfs_root / "route"
    route_dir.mkdir(parents=True, exist_ok=True)
    (route_dir / "prev").write_text("\n".join(prev))
    (route_dir / "next").write_text("\n".join(next_actors))
    return str(vfs_root)


def _read_vfs_next(vfs_root):
    """Read the route/next VFS file and return list of actors."""
    content = (Path(vfs_root) / "route" / "next").read_text()
    return [x for x in content.splitlines() if x]


def _compile_and_exec(source, env_vars=None):
    """Compile source, set env vars, exec code, and return namespace.

    env_vars must be set BEFORE exec() so the handler-to-actor
    mapping (_HANDLER_TO_ACTOR) is populated during module load.
    """
    if env_vars:
        for key, value in env_vars.items():
            os.environ[key] = value

    compiler = FlowCompiler()
    code = compiler.compile(source, "test.py")
    namespace = {}
    exec(code, namespace)
    return namespace


class TestRouterExecution:
    """Test that compiled routers correctly modify messages."""

    def setup_method(self):
        os.environ.clear()

    def test_simple_flow_routing(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler_a(p)
                return p

            def handler_a(p: dict) -> dict:
                return p
        """)

        namespace = _compile_and_exec(source, {"ASYA_HANDLER_HANDLER_A": "handler_a"})
        start_func = namespace["start_flow"]

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = _setup_vfs(tmpdir, [], [])
            namespace["_MSG_ROOT"] = vfs_root

            start_func({})

            next_actors = _read_vfs_next(vfs_root)
            assert "handler-a" in next_actors

    def test_sequential_handlers_routing(self):
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

        namespace = _compile_and_exec(source, {
            "ASYA_HANDLER_HANDLER_A": "handler_a",
            "ASYA_HANDLER_HANDLER_B": "handler_b",
            "ASYA_HANDLER_HANDLER_C": "handler_c",
        })
        start_func = namespace["start_flow"]

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = _setup_vfs(tmpdir, [], [])
            namespace["_MSG_ROOT"] = vfs_root

            start_func({})

            next_actors = _read_vfs_next(vfs_root)
            assert "handler-a" in next_actors
            assert "handler-b" in next_actors
            assert "handler-c" in next_actors


class TestConditionalRouting:
    """Test conditional routing logic."""

    def setup_method(self):
        os.environ.clear()

    def test_true_branch_routing(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["go_left"]:
                    p = left_handler(p)
                else:
                    p = right_handler(p)
                return p

            def left_handler(p: dict) -> dict:
                return p
            def right_handler(p: dict) -> dict:
                return p
        """)

        namespace = _compile_and_exec(source, {
            "ASYA_HANDLER_LEFT_HANDLER": "left_handler",
            "ASYA_HANDLER_RIGHT_HANDLER": "right_handler",
        })

        cond_router_name = [name for name in namespace if name.startswith("router_") and "_if" in name][0]
        cond_func = namespace[cond_router_name]

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = _setup_vfs(tmpdir, [], [])
            namespace["_MSG_ROOT"] = vfs_root

            cond_func({"go_left": True})

            next_actors = _read_vfs_next(vfs_root)
            assert "left-handler" in next_actors
            assert "right-handler" not in next_actors

    def test_false_branch_routing(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["go_left"]:
                    p = left_handler(p)
                else:
                    p = right_handler(p)
                return p

            def left_handler(p: dict) -> dict:
                return p
            def right_handler(p: dict) -> dict:
                return p
        """)

        namespace = _compile_and_exec(source, {
            "ASYA_HANDLER_LEFT_HANDLER": "left_handler",
            "ASYA_HANDLER_RIGHT_HANDLER": "right_handler",
        })

        cond_router_name = [name for name in namespace if name.startswith("router_") and "_if" in name][0]
        cond_func = namespace[cond_router_name]

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = _setup_vfs(tmpdir, [], [])
            namespace["_MSG_ROOT"] = vfs_root

            cond_func({"go_left": False})

            next_actors = _read_vfs_next(vfs_root)
            assert "right-handler" in next_actors
            assert "left-handler" not in next_actors

    def test_complex_condition_evaluation(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["x"] > 10 and p["y"] < 20:
                    p = handler_match(p)
                else:
                    p = handler_no_match(p)
                return p

            def handler_match(p: dict) -> dict:
                return p
            def handler_no_match(p: dict) -> dict:
                return p
        """)

        namespace = _compile_and_exec(source, {
            "ASYA_HANDLER_HANDLER_MATCH": "handler_match",
            "ASYA_HANDLER_HANDLER_NO_MATCH": "handler_no_match",
        })

        cond_router_name = [name for name in namespace if name.startswith("router_") and "_if" in name][0]
        cond_func = namespace[cond_router_name]

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = _setup_vfs(tmpdir, [], [])
            namespace["_MSG_ROOT"] = vfs_root

            cond_func({"x": 15, "y": 10})
            next_actors = _read_vfs_next(vfs_root)
            assert "handler-match" in next_actors

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = _setup_vfs(tmpdir, [], [])
            namespace["_MSG_ROOT"] = vfs_root

            cond_func({"x": 5, "y": 25})
            next_actors = _read_vfs_next(vfs_root)
            assert "handler-no-match" in next_actors


class TestMutationRouting:
    """Test routers with payload mutations."""

    def setup_method(self):
        os.environ.clear()

    def test_mutation_modifies_payload(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["key"] = "value"
                p = handler(p)
                return p

            def handler(p: dict) -> dict:
                return p
        """)

        namespace = _compile_and_exec(source, {"ASYA_HANDLER_HANDLER": "handler"})
        start_func = namespace["start_flow"]

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = _setup_vfs(tmpdir, [], [])
            namespace["_MSG_ROOT"] = vfs_root

            payload = {}
            result = start_func(payload)

            assert result["key"] == "value"
            next_actors = _read_vfs_next(vfs_root)
            assert "handler" in next_actors

    def test_multiple_mutations(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["x"] = 1
                p["y"] = 2
                p["z"] = 3
                return p
        """)

        namespace = _compile_and_exec(source)
        start_func = namespace["start_flow"]

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = _setup_vfs(tmpdir, [], [])
            namespace["_MSG_ROOT"] = vfs_root

            payload = {}
            result = start_func(payload)

            assert result["x"] == 1
            assert result["y"] == 2
            assert result["z"] == 3

    def test_mutations_in_conditional_branches(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["type"] == "A":
                    p["label"] = "A"
                else:
                    p["label"] = "B"
                return p
        """)

        # Compile first to discover router names, then set env vars and exec
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        env_vars = {}
        for router in compiler.routers:
            env_name = router.name.upper().replace("-", "_")
            env_vars[f"ASYA_HANDLER_{env_name}"] = router.name
        for key, value in env_vars.items():
            os.environ[key] = value

        namespace = {}
        exec(code, namespace)

        cond_router_name = [name for name in namespace if name.startswith("router_") and "_if" in name][0]
        cond_func = namespace[cond_router_name]

        # Conditional router selects the correct mutation branch via VFS
        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = _setup_vfs(tmpdir, [], [])
            namespace["_MSG_ROOT"] = vfs_root

            cond_func({"type": "A"})
            next_actors = _read_vfs_next(vfs_root)

            # Find the true-branch mutation router (the one with p["label"] = "A")
            true_branch_router = next(
                r for r in compiler.routers
                if r.mutations and any("'A'" in m.code for m in r.mutations)
            )
            # resolve() converts underscores to hyphens (kebab-case)
            expected_name = true_branch_router.name.replace("_", "-")
            assert expected_name in next_actors


class TestConvergenceRouting:
    """Test that branches properly converge."""

    def setup_method(self):
        os.environ.clear()

    def test_branches_converge_to_same_handler(self):
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

        namespace = _compile_and_exec(source, {
            "ASYA_HANDLER_HANDLER_A": "handler_a",
            "ASYA_HANDLER_HANDLER_B": "handler_b",
            "ASYA_HANDLER_FINAL_HANDLER": "final_handler",
        })

        cond_router_name = [name for name in namespace if name.startswith("router_") and "_if" in name][0]
        cond_func = namespace[cond_router_name]

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = _setup_vfs(tmpdir, [], [])
            namespace["_MSG_ROOT"] = vfs_root

            cond_func({"condition": True})
            next_actors = _read_vfs_next(vfs_root)
            assert "handler-a" in next_actors
            assert "final-handler" in next_actors

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = _setup_vfs(tmpdir, [], [])
            namespace["_MSG_ROOT"] = vfs_root

            cond_func({"condition": False})
            next_actors = _read_vfs_next(vfs_root)
            assert "handler-b" in next_actors
            assert "final-handler" in next_actors


class TestEndRouter:
    """Test end router behavior."""

    def test_end_router_returns_message_unchanged(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                return p
        """)

        namespace = _compile_and_exec(source)

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = _setup_vfs(tmpdir, [], [])
            namespace["_MSG_ROOT"] = vfs_root

            payload = {"test": "data"}
            end_func = namespace["end_flow"]
            result = end_func(payload)

            assert result == payload
            assert result["test"] == "data"

            next_actors = _read_vfs_next(vfs_root)
            assert next_actors == []


class TestResolveFunction:
    """Test the resolve() function behavior."""

    def setup_method(self):
        os.environ.clear()

    def test_resolve_finds_handler_from_env(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)
                return p

            def handler(p: dict) -> dict:
                return p
        """)

        namespace = _compile_and_exec(source, {"ASYA_HANDLER_MY_ACTOR": "handler"})

        resolve_func = namespace["resolve"]
        actor_name = resolve_func("handler")

        assert actor_name == "my-actor"

    def test_resolve_raises_on_missing_handler(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)
                return p

            def handler(p: dict) -> dict:
                return p
        """)

        namespace = _compile_and_exec(source)
        resolve_func = namespace["resolve"]

        with pytest.raises(ValueError, match="not found in environment variables"):
            resolve_func("nonexistent_handler")

    def test_resolve_loads_mappings_at_import(self):
        os.environ["ASYA_HANDLER_ACTOR1"] = "handler1"
        os.environ["ASYA_HANDLER_ACTOR2"] = "handler2"

        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)
                return p

            def handler(p: dict) -> dict:
                return p
        """)

        namespace = _compile_and_exec(source)

        assert "_HANDLER_TO_ACTOR" in namespace
        assert "handler1" in namespace["_HANDLER_TO_ACTOR"]
        assert "handler2" in namespace["_HANDLER_TO_ACTOR"]


class TestRouteInsertion:
    """Test that routers correctly prepend actors into next."""

    def setup_method(self):
        os.environ.clear()

    def test_router_prepends_to_next(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["init"] = True
                p = handler(p)
                return p

            def handler(p: dict) -> dict:
                return p
        """)

        namespace = _compile_and_exec(source, {"ASYA_HANDLER_HANDLER": "handler"})
        start_func = namespace["start_flow"]

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = _setup_vfs(tmpdir, [], ["router_after"])
            namespace["_MSG_ROOT"] = vfs_root

            start_func({})

            next_actors = _read_vfs_next(vfs_root)
            assert "handler" in next_actors
            assert next_actors[-1] == "router_after"

    def test_router_preserves_existing_route(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)
                return p

            def handler(p: dict) -> dict:
                return p
        """)

        namespace = _compile_and_exec(source, {"ASYA_HANDLER_HANDLER": "handler"})
        start_func = namespace["start_flow"]

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_root = _setup_vfs(tmpdir, [], [])
            namespace["_MSG_ROOT"] = vfs_root

            start_func({})

            next_actors = _read_vfs_next(vfs_root)
            assert "handler" in next_actors
