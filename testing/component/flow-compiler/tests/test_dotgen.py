"""Component tests for DotGenerator."""

import textwrap

from asya_lab.flow import FlowCompiler
from asya_lab.flow.dotgen import DotGenerator
from asya_lab.flow.grouper import OperationGrouper, Router
from asya_lab.flow.ir import ActorCall, Condition, Mutation, Return
from asya_lab.flow.parser import FlowParser


class TestDotGeneration:
    """Test DOT diagram generation."""

    def test_generate_basic_structure(self):
        routers = [
            Router(name="start_flow", lineno=1, true_branch_actors=["handler_a", "end_flow"]),
            Router(name="end_flow", lineno=10),
        ]
        generator = DotGenerator("flow", routers)
        dot = generator.generate()

        assert "digraph flow {" in dot
        assert "}" in dot
        assert "rankdir=TB" in dot

    def test_generate_includes_router_nodes(self):
        routers = [
            Router(name="start_flow", lineno=1, true_branch_actors=["end_flow"]),
            Router(name="end_flow", lineno=10),
        ]
        generator = DotGenerator("flow", routers)
        dot = generator.generate()

        assert "start_flow" in dot
        assert "end_flow" in dot

    def test_generate_includes_user_actors(self):
        routers = [
            Router(name="start_flow", lineno=1, true_branch_actors=["handler_a", "handler_b", "end_flow"]),
            Router(name="end_flow", lineno=10),
        ]
        generator = DotGenerator("flow", routers)
        dot = generator.generate()

        assert "handler_a" in dot or "handler-a" in dot
        assert "handler_b" in dot or "handler-b" in dot

    def test_generate_with_conditionals(self):
        condition = Condition(lineno=5, test='p["x"] > 10', true_branch=[], false_branch=[])
        routers = [
            Router(
                name="start_flow",
                lineno=1,
                condition=condition,
                true_branch_actors=["handler_a", "end_flow"],
                false_branch_actors=["handler_b", "end_flow"],
            ),
            Router(name="end_flow", lineno=10),
        ]
        generator = DotGenerator("flow", routers)
        dot = generator.generate()

        assert "if" in dot.lower()
        assert "true" in dot.lower() or "darkseagreen4" in dot
        assert "false" in dot.lower() or "indianred4" in dot

    def test_generate_with_mutations(self):
        routers = [
            Router(
                name="start_flow",
                lineno=1,
                mutations=[Mutation(lineno=2, code='p["status"] = "processing"')],
                true_branch_actors=["handler_a", "end_flow"],
            ),
            Router(name="end_flow", lineno=10),
        ]
        generator = DotGenerator("flow", routers)
        dot = generator.generate()

        assert "status" in dot or "processing" in dot

    def test_generate_edge_arrows(self):
        routers = [
            Router(name="start_flow", lineno=1, true_branch_actors=["handler_a", "end_flow"]),
            Router(name="end_flow", lineno=10),
        ]
        generator = DotGenerator("flow", routers)
        dot = generator.generate()

        assert "->" in dot

    def test_generate_conditional_edges_colored(self):
        condition = Condition(lineno=5, test='p["x"]', true_branch=[], false_branch=[])
        routers = [
            Router(
                name="start_flow",
                lineno=1,
                condition=condition,
                true_branch_actors=["handler_a"],
                false_branch_actors=["handler_b"],
            ),
        ]
        generator = DotGenerator("flow", routers)
        dot = generator.generate()

        assert "darkseagreen4" in dot
        assert "indianred4" in dot


class TestActorCollection:
    """Test _collect_actors functionality."""

    def test_collect_user_actors(self):
        routers = [
            Router(name="start_flow", lineno=1, true_branch_actors=["user_handler", "end_flow"]),
            Router(name="end_flow", lineno=10),
        ]
        generator = DotGenerator("flow", routers)
        generator._collect_actors()

        assert "user_handler" in generator.user_actors
        assert "start_flow" not in generator.user_actors
        assert "end_flow" not in generator.user_actors

    def test_collect_actors_from_both_branches(self):
        condition = Condition(lineno=5, test='p["x"]', true_branch=[], false_branch=[])
        routers = [
            Router(
                name="start_flow",
                lineno=1,
                condition=condition,
                true_branch_actors=["handler_a"],
                false_branch_actors=["handler_b"],
            ),
        ]
        generator = DotGenerator("flow", routers)
        generator._collect_actors()

        assert "handler_a" in generator.user_actors
        assert "handler_b" in generator.user_actors


class TestNodeGeneration:
    """Test node generation methods."""

    def test_generate_actor_node_start(self):
        router = Router(name="start_flow", lineno=1, true_branch_actors=["end_flow"])
        generator = DotGenerator("flow", [router])
        node = generator._generate_actor_node(router)

        assert "start_flow" in node
        assert "lightgreen" in node

    def test_generate_actor_node_end(self):
        router = Router(name="end_flow", lineno=10)
        generator = DotGenerator("flow", [router])
        node = generator._generate_actor_node(router)

        assert "end_flow" in node
        assert "lightgreen" in node

    def test_generate_actor_node_regular(self):
        router = Router(name="router_flow_line_5_seq", lineno=5, true_branch_actors=[])
        generator = DotGenerator("flow", [router])
        node = generator._generate_actor_node(router)

        assert "router_flow_line_5_seq" in node
        assert "wheat" in node

    def test_generate_user_actor_node(self):
        generator = DotGenerator("flow", [])
        node = generator._generate_user_actor_node("my_handler")

        assert "my_handler" in node
        assert "lightblue" in node


class TestEdgeGeneration:
    """Test edge generation methods."""

    def test_generate_edges_sequential(self):
        router = Router(name="start_flow", lineno=1, true_branch_actors=["handler_a", "handler_b", "end_flow"])
        generator = DotGenerator("flow", [router])
        edges = generator._generate_edges(router)

        edges_str = " ".join(edges)
        assert "start_flow" in edges_str
        assert "handler_a" in edges_str or "handler-a" in edges_str

    def test_generate_edges_conditional(self):
        condition = Condition(lineno=5, test='p["x"]', true_branch=[], false_branch=[])
        router = Router(
            name="router",
            lineno=1,
            condition=condition,
            true_branch_actors=["handler_a"],
            false_branch_actors=["handler_b"],
        )
        generator = DotGenerator("flow", [router])
        edges = generator._generate_edges(router)

        assert len(edges) >= 2
        edges_str = " ".join(edges)
        assert "darkseagreen4" in edges_str
        assert "indianred4" in edges_str

    def test_generate_edges_empty_branches(self):
        condition = Condition(lineno=5, test='p["x"]', true_branch=[], false_branch=[])
        router = Router(name="router", lineno=1, condition=condition, true_branch_actors=[], false_branch_actors=[])
        generator = DotGenerator("flow", [router])
        edges = generator._generate_edges(router)

        assert edges == set()


class TestHelperMethods:
    """Test helper utility methods."""

    def test_node_id_replaces_hyphens(self):
        generator = DotGenerator("flow", [])
        node_id = generator._node_id("my-handler-name")
        assert node_id == "my_handler_name"

    def test_escape_html_escapes_special_chars(self):
        generator = DotGenerator("flow", [])
        escaped = generator._escape_html('<tag attr="value"> & more')
        assert "&lt;" in escaped
        assert "&gt;" in escaped
        assert "&amp;" in escaped
        assert "&quot;" in escaped

    def test_truncate_text_short(self):
        generator = DotGenerator("flow", [])
        text = "short"
        truncated = generator._truncate_text(text)
        assert truncated == text

    def test_truncate_text_long(self):
        generator = DotGenerator("flow", [], step_width=20)
        text = "this is a very long text that should be truncated"
        truncated = generator._truncate_text(text)
        assert len(truncated) <= len(text)
        assert "\u2026" in truncated

    def test_truncate_display_name_short(self):
        generator = DotGenerator("flow", [], step_width=40)
        result = generator._truncate_display_name("short_func")
        assert result == "p = short_func(p)"

    def test_truncate_display_name_long(self):
        generator = DotGenerator("flow", [], step_width=20)
        result = generator._truncate_display_name("very_long_function_name_that_exceeds")
        assert len(result) <= 20


class TestEndToEnd:
    """Test DOT generation with full compiler pipeline."""

    def test_simple_flow_dot(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler_a(p)
                p = handler_b(p)
                return p
        """)
        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        generator = DotGenerator(compiler.flow_name, compiler.routers)
        dot = generator.generate()

        assert "digraph flow {" in dot
        assert "start_flow" in dot
        assert "end_flow" in dot
        assert "->" in dot

    def test_conditional_flow_dot(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["condition"]:
                    p = handler_a(p)
                else:
                    p = handler_b(p)
                return p
        """)
        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        generator = DotGenerator(compiler.flow_name, compiler.routers)
        dot = generator.generate()

        assert "if" in dot.lower()
        assert "darkseagreen4" in dot
        assert "indianred4" in dot

    def test_mutation_flow_dot(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["status"] = "processing"
                p = handler(p)
                return p
        """)
        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        generator = DotGenerator(compiler.flow_name, compiler.routers)
        dot = generator.generate()

        assert "status" in dot or "processing" in dot
