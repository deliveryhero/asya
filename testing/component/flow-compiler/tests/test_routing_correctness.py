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

        message = {"route": {"actors": ["start_flow"], "current": 0}, "payload": {}}
        start_func = namespace["start_flow"]
        result = start_func(message)

        assert len(result["route"]["actors"]) == 3
        assert result["route"]["actors"][1] == "handler-a"
        assert result["route"]["actors"][2] == "end-flow"

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

        message = {"route": {"actors": ["start_flow"], "current": 0}, "payload": {}}
        start_func = namespace["start_flow"]
        result = start_func(message)

        assert "handler-a" in result["route"]["actors"]
        assert "handler-b" in result["route"]["actors"]
        assert "handler-c" in result["route"]["actors"]
        assert "end-flow" in result["route"]["actors"]


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
            "route": {"actors": [cond_router_name], "current": 0},
            "payload": {"go_left": True}
        }
        result_true = cond_func(message_true)

        assert "left-handler" in result_true["route"]["actors"]
        assert "right-handler" not in result_true["route"]["actors"]

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
            "route": {"actors": [cond_router_name], "current": 0},
            "payload": {"go_left": False}
        }
        result_false = cond_func(message_false)

        assert "right-handler" in result_false["route"]["actors"]
        assert "left-handler" not in result_false["route"]["actors"]

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
            "route": {"actors": [cond_router_name], "current": 0},
            "payload": {"x": 15, "y": 10}
        }
        result_match = cond_func(message_match)
        assert "handler-match" in result_match["route"]["actors"]

        message_no_match = {
            "route": {"actors": [cond_router_name], "current": 0},
            "payload": {"x": 5, "y": 25}
        }
        result_no_match = cond_func(message_no_match)
        assert "handler-no-match" in result_no_match["route"]["actors"]


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
            "route": {"actors": [mutation_router_name], "current": 0},
            "payload": {}
        }
        result = mutation_func(message)

        assert result["payload"]["key"] == "value"
        assert "handler" in result["route"]["actors"]

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
            "route": {"actors": [mutation_router_name], "current": 0},
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

        message_a = {
            "route": {"actors": ["router"], "current": 0},
            "payload": {"type": "A"}
        }

        cond_router_name = [name for name in namespace if name.startswith("router_") and "_if" in name][0]
        cond_func = namespace[cond_router_name]
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
            "route": {"actors": [cond_router_name], "current": 0},
            "payload": {"condition": True}
        }
        result_true = cond_func(message_true)
        assert "handler-a" in result_true["route"]["actors"]
        assert "final-handler" in result_true["route"]["actors"]

        message_false = {
            "route": {"actors": [cond_router_name], "current": 0},
            "payload": {"condition": False}
        }
        result_false = cond_func(message_false)
        assert "handler-b" in result_false["route"]["actors"]
        assert "final-handler" in result_false["route"]["actors"]


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
            "route": {"actors": ["end_flow"], "current": 0},
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
    """Test that routers correctly insert actors into route."""

    def setup_method(self):
        os.environ.clear()

    def test_router_inserts_at_correct_position(self):
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

        message = {
            "route": {"actors": ["router_before", router_name, "router_after"], "current": 1},
            "payload": {}
        }
        result = router_func(message)

        assert result["route"]["actors"][0] == "router_before"
        assert "handler" in result["route"]["actors"]
        assert "router_after" in result["route"]["actors"]
        assert result["route"]["actors"][-1] == "router_after"

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
            "route": {"actors": ["start_flow"], "current": 0},
            "payload": {}
        }
        result = start_func(message)

        assert result["route"]["actors"][0] == "start_flow"
