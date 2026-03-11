"""Tests for graph JSON emission."""

import json

from asya_lab.flow.compiler import FlowCompiler
from asya_lab.flow.graphgen import GraphGenerator


class TestGraphGenBasic:
    """Basic graph JSON generation from compiled flows."""

    def test_linear_flow_nodes(self):
        source = """
def my_flow(p: dict) -> dict:
    p = actor_a(p)
    p = actor_b(p)
    return p
"""
        compiler = FlowCompiler()
        compiler.compile(source, "test.py")
        assert compiler.flow_name is not None
        gen = GraphGenerator(compiler.flow_name, compiler.routers)
        graph = gen.generate()

        assert graph["flow"] == "my_flow"
        node_ids = {n["id"] for n in graph["nodes"]}
        assert "actor_a" in node_ids
        assert "actor_b" in node_ids

    def test_linear_flow_edges(self):
        source = """
def my_flow(p: dict) -> dict:
    p = actor_a(p)
    p = actor_b(p)
    return p
"""
        compiler = FlowCompiler()
        compiler.compile(source, "test.py")
        assert compiler.flow_name is not None
        gen = GraphGenerator(compiler.flow_name, compiler.routers)
        graph = gen.generate()

        edges = graph["edges"]
        assert len(edges) >= 1
        assert all(e["type"] in ("sequential", "true", "false", "except", "fanout") for e in edges)

    def test_node_type_axis(self):
        source = """
def my_flow(p: dict) -> dict:
    p["x"] = 1
    p = actor_a(p)
    return p
"""
        compiler = FlowCompiler()
        compiler.compile(source, "test.py")
        assert compiler.flow_name is not None
        gen = GraphGenerator(compiler.flow_name, compiler.routers)
        graph = gen.generate()

        nodes_by_id = {n["id"]: n for n in graph["nodes"]}
        assert nodes_by_id["actor_a"]["type"] == "actor"
        router_nodes = [n for n in graph["nodes"] if n["type"] == "router"]
        assert len(router_nodes) >= 1

    def test_entrypoint_exitpoint_flags(self):
        source = """
def my_flow(p: dict) -> dict:
    p = actor_a(p)
    return p
"""
        compiler = FlowCompiler()
        compiler.compile(source, "test.py")
        assert compiler.flow_name is not None
        gen = GraphGenerator(compiler.flow_name, compiler.routers)
        graph = gen.generate()

        entry_nodes = [n for n in graph["nodes"] if n.get("entrypoint")]
        exit_nodes = [n for n in graph["nodes"] if n.get("exitpoint")]
        assert len(entry_nodes) >= 1
        assert len(exit_nodes) >= 1

    def test_conditional_flow(self):
        source = """
def my_flow(p: dict) -> dict:
    if p["x"] == "A":
        p = handler_a(p)
    else:
        p = handler_b(p)
    return p
"""
        compiler = FlowCompiler()
        compiler.compile(source, "test.py")
        assert compiler.flow_name is not None
        gen = GraphGenerator(compiler.flow_name, compiler.routers)
        graph = gen.generate()

        cond_nodes = [n for n in graph["nodes"] if n["role"] == "conditional"]
        assert len(cond_nodes) >= 1
        true_edges = [e for e in graph["edges"] if e["type"] == "true"]
        false_edges = [e for e in graph["edges"] if e["type"] == "false"]
        assert len(true_edges) >= 1
        assert len(false_edges) >= 1

    def test_graph_is_json_serializable(self):
        source = """
def my_flow(p: dict) -> dict:
    p = actor_a(p)
    return p
"""
        compiler = FlowCompiler()
        compiler.compile(source, "test.py")
        assert compiler.flow_name is not None
        gen = GraphGenerator(compiler.flow_name, compiler.routers)
        graph = gen.generate()

        json_str = json.dumps(graph)
        roundtrip = json.loads(json_str)
        assert roundtrip == graph

    def test_groups_empty_for_simple_flow(self):
        source = """
def my_flow(p: dict) -> dict:
    p = actor_a(p)
    return p
"""
        compiler = FlowCompiler()
        compiler.compile(source, "test.py")
        assert compiler.flow_name is not None
        gen = GraphGenerator(compiler.flow_name, compiler.routers)
        graph = gen.generate()

        assert graph["groups"] == []


class TestGraphGenTryExcept:
    """Graph JSON for try-except flows produces groups."""

    def test_try_block_creates_group(self):
        source = """
def my_flow(p: dict) -> dict:
    try:
        p = risky_actor(p)
    except ValueError:
        p = fallback_actor(p)
    return p
"""
        compiler = FlowCompiler()
        compiler.compile(source, "test.py")
        assert compiler.flow_name is not None
        gen = GraphGenerator(compiler.flow_name, compiler.routers)
        graph = gen.generate()

        assert len(graph["groups"]) >= 1
        group = graph["groups"][0]
        assert group["type"] == "try"
        assert "risky_actor" in group["nodes"]


class TestGraphGenFanOut:
    """Graph JSON for fan-out flows."""

    def test_fanout_edge_type(self):
        source = """
def my_flow(p: dict) -> dict:
    p["results"] = [process(item) for item in p["items"]]
    return p
"""
        compiler = FlowCompiler()
        compiler.compile(source, "test.py")
        assert compiler.flow_name is not None
        gen = GraphGenerator(compiler.flow_name, compiler.routers)
        graph = gen.generate()

        fanout_edges = [e for e in graph["edges"] if e["type"] == "fanout"]
        assert len(fanout_edges) >= 1
        fanout_nodes = [n for n in graph["nodes"] if n["role"] == "fanout"]
        assert len(fanout_nodes) >= 1
