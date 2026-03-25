"""Tests for graph rendering (graphgen.py)."""

from asya_lab.flow.analyzer import GraphData
from asya_lab.flow.graphgen import to_dot, to_json, to_mermaid


def _make_graph() -> GraphData:
    return GraphData(
        nodes=[
            {"id": "start_flow", "label": "start_flow", "role": "start", "generated": True},
            {"id": "handler_a", "label": "handler_a"},
            {"id": "handler_b", "label": "handler_b", "role": "end"},
            {"id": "__end__", "label": "__end__", "role": "end"},
        ],
        edges=[
            {"from": "start_flow", "to": "handler_a", "label": None, "type": "prepend"},
            {"from": "handler_a", "to": "handler_b", "label": None, "type": "continuation"},
            {"from": "handler_b", "to": "__end__", "label": None, "type": "set"},
        ],
        groups=[],
    )


class TestToDot:
    def test_digraph_header(self):
        dot = to_dot(_make_graph(), "test_flow")
        assert dot.startswith('digraph "test_flow"')

    def test_nodes_present(self):
        dot = to_dot(_make_graph(), "test_flow")
        assert "start_flow" in dot
        assert "handler_a" in dot
        assert "handler_b" in dot

    def test_edges_present(self):
        dot = to_dot(_make_graph(), "test_flow")
        assert "start_flow -> handler_a" in dot
        assert "handler_a -> handler_b" in dot

    def test_end_node_links_to_end_marker(self):
        dot = to_dot(_make_graph(), "test_flow")
        assert "handler_b -> __end__" in dot
        assert "__end__" in dot

    def test_groups_as_subgraphs(self):
        graph = _make_graph()
        graph.groups = [{"id": "my_group", "nodes": ["handler_a", "handler_b"]}]
        dot = to_dot(graph, "test_flow")
        assert "subgraph cluster_my_group" in dot
        assert "handler_a" in dot
        assert "handler_b" in dot


class TestToMermaid:
    def test_flowchart_header(self):
        mmd = to_mermaid(_make_graph(), "test_flow")
        assert mmd.startswith("flowchart TD")

    def test_edges_present(self):
        mmd = to_mermaid(_make_graph(), "test_flow")
        assert "start_flow --> handler_a" in mmd
        assert "handler_a --> handler_b" in mmd

    def test_groups_as_subgraphs(self):
        graph = _make_graph()
        graph.groups = [{"id": "my_group", "nodes": ["handler_a", "handler_b"]}]
        mmd = to_mermaid(graph, "test_flow")
        assert "subgraph my_group" in mmd
        assert "end" in mmd

    def test_class_styling(self):
        mmd = to_mermaid(_make_graph(), "test_flow")
        assert "classDef start" in mmd
        assert "classDef endnode" in mmd
        assert "class start_flow start" in mmd
        assert "handler_b" in mmd and "endnode" in mmd


class TestToJson:
    def test_flow_name(self):
        result = to_json(_make_graph(), "test_flow")
        assert result["flow_name"] == "test_flow"

    def test_nodes_edges_groups_counts(self):
        result = to_json(_make_graph(), "test_flow")
        assert len(result["nodes"]) == 4
        assert len(result["edges"]) == 3
        assert len(result["groups"]) == 0

    def test_warnings_included_when_present(self):
        graph = _make_graph()
        graph.warnings = ["some warning"]
        result = to_json(graph, "test_flow")
        assert "warnings" in result
        assert result["warnings"] == ["some warning"]

    def test_warnings_absent_when_empty(self):
        graph = _make_graph()
        graph.warnings = []
        result = to_json(graph, "test_flow")
        assert "warnings" not in result
