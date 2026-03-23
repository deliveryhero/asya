"""Tests for the yield analysis module (analyzer.py)."""

import ast
import textwrap

from asya_lab.flow.analyzer import GraphData, _extract_yield_edges, analyze


def _parse_func(source: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(textwrap.dedent(source))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            return node
    raise ValueError("No function found")


class TestExtractYieldEdges:
    def test_set_route_next_with_resolve(self):
        func = _parse_func("""
            async def router_step1(payload):
                p = payload
                yield "SET", ".route.next", [resolve("actor_a")]
                yield p
        """)
        edges = _extract_yield_edges(func, "router_step1")
        assert len(edges) == 1
        assert edges[0]["from"] == "router_step1"
        assert edges[0]["to"] == "actor_a"
        assert edges[0]["type"] == "set"

    def test_prepend_via_next_append(self):
        func = _parse_func("""
            async def router_seq1(payload):
                p = payload
                _next = []
                _next.append(resolve("a"))
                _next.append(resolve("b"))
                yield "SET", ".route.next[:0]", _next
                yield p
        """)
        edges = _extract_yield_edges(func, "router_seq1")
        # Sequential chain: router_seq1 -> a -> b
        assert len(edges) == 2
        assert edges[0]["from"] == "router_seq1"
        assert edges[0]["to"] == "a"
        assert edges[0]["type"] == "prepend"
        assert edges[1]["from"] == "a"
        assert edges[1]["to"] == "b"
        assert edges[1]["type"] == "continuation"

    def test_conditional_edges_with_labels(self):
        func = _parse_func("""
            async def router_if_1(payload):
                p = payload
                _next = []
                if p['score'] > 0.5:
                    _next.append(resolve("good"))
                else:
                    _next.append(resolve("bad"))
                yield "SET", ".route.next[:0]", _next
                yield p
        """)
        edges = _extract_yield_edges(func, "router_if_1")
        assert len(edges) == 2
        good_edge = next(e for e in edges if e["to"] == "good")
        bad_edge = next(e for e in edges if e["to"] == "bad")
        # The if-branch gets the condition as label
        assert good_edge["label"] is not None
        assert "score" in good_edge["label"]
        # The else-branch gets "else"
        assert bad_edge["label"] == "else"

    def test_empty_route_no_edge(self):
        func = _parse_func("""
            async def router_terminal(payload):
                p = payload
                yield "SET", ".route.next", []
                yield p
        """)
        edges = _extract_yield_edges(func, "router_terminal")
        assert edges == []

    def test_fanout_slice_edges(self):
        func = _parse_func("""
            async def fanout_research(payload):
                p = payload
                _agg = resolve("fanin_research")
                _slices = []
                for t in p['topics']:
                    _slices.append((resolve("worker"), t))
                yield "SET", ".route.next", [_agg]
                for i, (_actor, _p) in enumerate(_slices):
                    yield "SET", ".route.next", [_actor, _agg]
                    yield _p
        """)
        edges = _extract_yield_edges(func, "fanout_research")
        # Should have: fanout_research -> fanin_research (set, labeled with fanout info),
        # fanout_research -> worker (fanout), worker -> fanin_research (continuation)
        fanout_edges = [e for e in edges if e["type"] == "fanout"]
        assert len(fanout_edges) == 1
        assert fanout_edges[0]["to"] == "worker"

        cont_edges = [e for e in edges if e["type"] == "continuation"]
        assert any(e["from"] == "worker" and e["to"] == "fanin_research" for e in cont_edges)


class TestAnalyzeIntegration:
    def test_simple_sequential_graph(self):
        routers_source = textwrap.dedent("""
            async def start_flow(payload):
                p = payload
                _next = []
                _next.append(resolve("handler_a"))
                _next.append(resolve("handler_b"))
                yield "SET", ".route.next[:0]", _next
                yield p
        """)
        graph = analyze(routers_source)
        assert isinstance(graph, GraphData)
        node_ids = {n["id"] for n in graph.nodes}
        assert "start_flow" in node_ids
        assert "handler_a" in node_ids
        assert "handler_b" in node_ids
        # Edges: start_flow -> handler_a -> handler_b
        assert any(e["from"] == "start_flow" and e["to"] == "handler_a" for e in graph.edges)
        assert any(e["from"] == "handler_a" and e["to"] == "handler_b" for e in graph.edges)

    def test_handler_override_edges_marked(self):
        routers_source = textwrap.dedent("""
            async def start_flow(payload):
                p = payload
                yield "SET", ".route.next", [resolve("my_handler")]
                yield p
        """)
        handler_sources = {
            "my_handler": textwrap.dedent("""
                async def my_handler(payload):
                    yield "SET", ".route.next", ["x-pause"]
                    yield payload
            """),
        }
        graph = analyze(routers_source, handler_sources)
        override_edges = [e for e in graph.edges if e.get("override")]
        assert len(override_edges) == 1
        assert override_edges[0]["from"] == "my_handler"
        assert override_edges[0]["to"] == "x-pause"
        assert override_edges[0]["override"] is True

    def test_graph_has_start_and_end_nodes(self):
        routers_source = textwrap.dedent("""
            async def start_myflow(payload):
                p = payload
                _next = []
                _next.append(resolve("handler_a"))
                _next.append(resolve("handler_b"))
                yield "SET", ".route.next[:0]", _next
                yield p
        """)
        graph = analyze(routers_source)
        start_nodes = [n for n in graph.nodes if n.get("role") == "start"]
        end_nodes = [n for n in graph.nodes if n.get("role") == "end"]
        assert len(start_nodes) == 1
        assert start_nodes[0]["id"] == "start_myflow"
        assert len(end_nodes) == 1
        assert end_nodes[0]["id"] == "handler_b"

    def test_duplicate_sequential_actor_gets_suffix(self):
        """Calling the same actor twice creates distinct graph nodes with same label."""
        routers_source = textwrap.dedent("""
            async def start_flow(payload):
                p = payload
                _next = []
                _next.append(resolve("analyze"))
                _next.append(resolve("analyze"))
                _next.append(resolve("summarize"))
                yield "SET", ".route.next[:0]", _next
                yield p
        """)
        graph = analyze(routers_source)

        # No self-loop edge
        self_edges = [e for e in graph.edges if e["from"] == e["to"]]
        assert self_edges == [], f"Unexpected self-loop edges: {self_edges}"

        # Graph: start_flow -> analyze -> analyze:2 -> summarize
        edge_pairs = [(e["from"], e["to"]) for e in graph.edges]
        assert ("start_flow", "analyze") in edge_pairs
        assert ("analyze", "analyze:2") in edge_pairs
        assert ("analyze:2", "summarize") in edge_pairs

        # 4 nodes with unique IDs
        node_ids = {n["id"] for n in graph.nodes}
        assert node_ids == {"start_flow", "analyze", "analyze:2", "summarize"}

        # Both analyze nodes have the same label
        analyze_nodes = [n for n in graph.nodes if n["label"] == "analyze"]
        assert len(analyze_nodes) == 2

    def test_disconnected_node_warning(self):
        routers_source = textwrap.dedent("""
            async def start_flow(payload):
                p = payload
                yield "SET", ".route.next", [resolve("handler_a")]
                yield p

            async def router_orphan(payload):
                p = payload
                yield "SET", ".route.next", [resolve("handler_b")]
                yield p
        """)
        graph = analyze(routers_source)
        # router_orphan and handler_b are not reachable from start_flow
        assert any("router_orphan" in w for w in graph.warnings)
