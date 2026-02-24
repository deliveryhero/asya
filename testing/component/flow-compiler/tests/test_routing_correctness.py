"""Test routing correctness by executing compiled routers."""

import os
import textwrap

import pytest

from asya_cli.flow import FlowCompiler


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

        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        namespace = {}
        exec(code, namespace)

        os.environ["ASYA_HANDLER_HANDLER_A"] = "handler_a"
        os.environ["ASYA_HANDLER_END_FLOW"] = "end_flow"
        os.environ["ASYA_HANDLER_START_FLOW"] = "start_flow"

        message = {"route": {"prev": [], "curr": "start_flow", "next": []}, "payload": {}}
        start_func = namespace["start_flow"]
        result = start_func(message)

        assert "handler-a" in result["route"]["next"]

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

        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        namespace = {}
        exec(code, namespace)

        os.environ["ASYA_HANDLER_HANDLER_A"] = "handler_a"
        os.environ["ASYA_HANDLER_HANDLER_B"] = "handler_b"
        os.environ["ASYA_HANDLER_HANDLER_C"] = "handler_c"
        os.environ["ASYA_HANDLER_END_FLOW"] = "end_flow"
        os.environ["ASYA_HANDLER_START_FLOW"] = "start_flow"

        message = {"route": {"prev": [], "curr": "start_flow", "next": []}, "payload": {}}
        start_func = namespace["start_flow"]
        result = start_func(message)

        assert "handler-a" in result["route"]["next"]
        assert "handler-b" in result["route"]["next"]
        assert "handler-c" in result["route"]["next"]


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

        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        namespace = {}
        exec(code, namespace)

        os.environ["ASYA_HANDLER_LEFT_HANDLER"] = "left_handler"
        os.environ["ASYA_HANDLER_RIGHT_HANDLER"] = "right_handler"
        os.environ["ASYA_HANDLER_END_FLOW"] = "end_flow"

        cond_router_name = [name for name in namespace if name.startswith("router_") and "_if" in name][0]
        cond_func = namespace[cond_router_name]

        message_true = {
            "route": {"prev": [], "curr": cond_router_name, "next": []},
            "payload": {"go_left": True}
        }
        result_true = cond_func(message_true)

        assert "left-handler" in result_true["route"]["next"]
        assert "right-handler" not in result_true["route"]["next"]

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

        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        namespace = {}
        exec(code, namespace)

        os.environ["ASYA_HANDLER_LEFT_HANDLER"] = "left_handler"
        os.environ["ASYA_HANDLER_RIGHT_HANDLER"] = "right_handler"
        os.environ["ASYA_HANDLER_END_FLOW"] = "end_flow"

        cond_router_name = [name for name in namespace if name.startswith("router_") and "_if" in name][0]
        cond_func = namespace[cond_router_name]

        message_false = {
            "route": {"prev": [], "curr": cond_router_name, "next": []},
            "payload": {"go_left": False}
        }
        result_false = cond_func(message_false)

        assert "right-handler" in result_false["route"]["next"]
        assert "left-handler" not in result_false["route"]["next"]

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

        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        namespace = {}
        exec(code, namespace)

        os.environ["ASYA_HANDLER_HANDLER_MATCH"] = "handler_match"
        os.environ["ASYA_HANDLER_HANDLER_NO_MATCH"] = "handler_no_match"
        os.environ["ASYA_HANDLER_END_FLOW"] = "end_flow"

        cond_router_name = [name for name in namespace if name.startswith("router_") and "_if" in name][0]
        cond_func = namespace[cond_router_name]

        message_match = {
            "route": {"prev": [], "curr": cond_router_name, "next": []},
            "payload": {"x": 15, "y": 10}
        }
        result_match = cond_func(message_match)
        assert "handler-match" in result_match["route"]["next"]

        message_no_match = {
            "route": {"prev": [], "curr": cond_router_name, "next": []},
            "payload": {"x": 5, "y": 25}
        }
        result_no_match = cond_func(message_no_match)
        assert "handler-no-match" in result_no_match["route"]["next"]


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

        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        namespace = {}
        exec(code, namespace)

        os.environ["ASYA_HANDLER_HANDLER"] = "handler"
        os.environ["ASYA_HANDLER_END_FLOW"] = "end_flow"

        mutation_router_name = [name for name in namespace if name.startswith("router_") and "_seq" in name][0]
        mutation_func = namespace[mutation_router_name]

        message = {
            "route": {"prev": [], "curr": mutation_router_name, "next": []},
            "payload": {}
        }
        result = mutation_func(message)

        assert result["payload"]["key"] == "value"
        assert "handler" in result["route"]["next"]

    def test_multiple_mutations(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["x"] = 1
                p["y"] = 2
                p["z"] = 3
                return p
        """)

        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        namespace = {}
        exec(code, namespace)

        os.environ["ASYA_HANDLER_END_FLOW"] = "end_flow"

        mutation_router_name = [name for name in namespace if name.startswith("router_") and "_seq" in name][0]
        mutation_func = namespace[mutation_router_name]

        message = {
            "route": {"prev": [], "curr": mutation_router_name, "next": []},
            "payload": {}
        }
        result = mutation_func(message)

        assert result["payload"]["x"] == 1
        assert result["payload"]["y"] == 2
        assert result["payload"]["z"] == 3

    def test_mutations_in_conditional_branches(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["type"] == "A":
                    p["label"] = "A"
                else:
                    p["label"] = "B"
                return p
        """)

        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        namespace = {}
        exec(code, namespace)

        os.environ["ASYA_HANDLER_END_FLOW"] = "end_flow"

        for router_name in namespace:
            if router_name.startswith("router_"):
                env_name = router_name.upper().replace("-", "_")
                os.environ[f"ASYA_HANDLER_{env_name}"] = router_name

        mutation_routers = [name for name in namespace if name.startswith("router_") and "_seq" in name]

        cond_router_name = [name for name in namespace if name.startswith("router_") and "_if" in name][0]
        cond_func = namespace[cond_router_name]

        message_a = {
            "route": {"prev": [], "curr": cond_router_name, "next": []},
            "payload": {"type": "A"}
        }
        result_a = cond_func(message_a)

        if mutation_routers:
            mutation_router = namespace[mutation_routers[0]]
            result_a = mutation_router(result_a)
            assert result_a["payload"]["label"] == "A"


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

        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        namespace = {}
        exec(code, namespace)

        os.environ["ASYA_HANDLER_HANDLER_A"] = "handler_a"
        os.environ["ASYA_HANDLER_HANDLER_B"] = "handler_b"
        os.environ["ASYA_HANDLER_FINAL_HANDLER"] = "final_handler"
        os.environ["ASYA_HANDLER_END_FLOW"] = "end_flow"

        cond_router_name = [name for name in namespace if name.startswith("router_") and "_if" in name][0]
        cond_func = namespace[cond_router_name]

        message_true = {
            "route": {"prev": [], "curr": cond_router_name, "next": []},
            "payload": {"condition": True}
        }
        result_true = cond_func(message_true)
        assert "handler-a" in result_true["route"]["next"]
        assert "final-handler" in result_true["route"]["next"]

        message_false = {
            "route": {"prev": [], "curr": cond_router_name, "next": []},
            "payload": {"condition": False}
        }
        result_false = cond_func(message_false)
        assert "handler-b" in result_false["route"]["next"]
        assert "final-handler" in result_false["route"]["next"]


class TestEndRouter:
    """Test end router behavior."""

    def test_end_router_returns_message_unchanged(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        namespace = {}
        exec(code, namespace)

        message = {
            "route": {"prev": [], "curr": "end_flow", "next": []},
            "payload": {"test": "data"}
        }
        end_func = namespace["end_flow"]
        result = end_func(message)

        assert result == message
        assert result["payload"]["test"] == "data"


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

        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        namespace = {}
        exec(code, namespace)

        os.environ["ASYA_HANDLER_MY_ACTOR"] = "handler"

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

        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        namespace = {}
        exec(code, namespace)

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

        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        namespace = {}
        exec(code, namespace)

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

        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        namespace = {}
        exec(code, namespace)

        os.environ["ASYA_HANDLER_HANDLER"] = "handler"
        os.environ["ASYA_HANDLER_END_FLOW"] = "end_flow"

        router_name = [name for name in namespace if name.startswith("router_")][0]
        router_func = namespace[router_name]

        # Router receives message with router_after already in next
        message = {
            "route": {"prev": ["router_before"], "curr": router_name, "next": ["router_after"]},
            "payload": {}
        }
        result = router_func(message)

        # Handler should be prepended before router_after in next
        assert "handler" in result["route"]["next"]
        assert result["route"]["next"][-1] == "router_after"

    def test_router_preserves_existing_route(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)
                return p

            def handler(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        namespace = {}
        exec(code, namespace)

        os.environ["ASYA_HANDLER_HANDLER"] = "handler"
        os.environ["ASYA_HANDLER_END_FLOW"] = "end_flow"
        os.environ["ASYA_HANDLER_START_FLOW"] = "start_flow"

        start_func = namespace["start_flow"]

        message = {
            "route": {"prev": [], "curr": "start_flow", "next": []},
            "payload": {}
        }
        result = start_func(message)

        # prev should be unchanged (curr hasn't been shifted yet - runtime does that)
        assert result["route"]["prev"] == []
        assert result["route"]["curr"] == "start_flow"
        # handler should be in next
        assert "handler" in result["route"]["next"]
