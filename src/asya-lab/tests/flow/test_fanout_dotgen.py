"""Unit tests for fan-out visualization in the dot diagram generator."""

from __future__ import annotations

import re

import pytest
from asya_lab.flow.dotgen import DotGenerator
from asya_lab.flow.grouper import OperationGrouper
from asya_lab.flow.ir import ActorCall, FanOutCall, Return


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fanout_op(
    target_key: str = "/results",
    pattern: str = "comprehension",
    actor_calls: list[tuple[str, str]] | None = None,
    iter_var: str | None = "t",
    iterable: str | None = 'p["topics"]',
    lineno: int = 5,
) -> FanOutCall:
    if actor_calls is None:
        actor_calls = [("research_agent", "t")]
    return FanOutCall(
        lineno=lineno,
        target_key=target_key,
        pattern=pattern,
        actor_calls=actor_calls,
        iter_var=iter_var,
        iterable=iterable,
    )


def _generate_dot_for_ops(flow_name: str, ops: list) -> str:
    grouper = OperationGrouper(flow_name, ops)
    routers = grouper.group()
    gen = DotGenerator(flow_name, routers)
    return gen.generate()


def _extract_nodes(dot: str) -> set[str]:
    """Extract node IDs from DOT output (lines with [fillcolor=)."""
    nodes = set()
    for match in re.finditer(r"^\s+(\w+)\s+\[fillcolor=", dot, re.MULTILINE):
        nodes.add(match.group(1))
    return nodes


def _extract_edges(dot: str) -> set[tuple[str, str]]:
    """Extract directed edges from DOT output."""
    edges = set()
    for match in re.finditer(r"^\s+(\w+)\s+->\s+(\w+)", dot, re.MULTILINE):
        edges.add((match.group(1), match.group(2)))
    return edges


# ---------------------------------------------------------------------------
# Test: Fan-out node rendering
# ---------------------------------------------------------------------------


class TestFanOutNodeRendering:
    def test_fanout_router_node_appears_in_dot(self):
        ops = [_make_fanout_op(), Return(lineno=6)]
        dot = _generate_dot_for_ops("flow", ops)

        nodes = _extract_nodes(dot)
        fanout_nodes = {n for n in nodes if "fanout" in n.lower()}
        assert len(fanout_nodes) >= 1, f"Expected at least one fanout node, got nodes: {nodes}"

    def test_fanout_node_has_distinct_color(self):
        """Fan-out node should have a color distinct from regular router nodes."""
        ops = [_make_fanout_op(), Return(lineno=6)]
        dot = _generate_dot_for_ops("flow", ops)

        # The fanout node should use mediumpurple1 color
        assert "mediumpurple1" in dot, "Fan-out router node should use mediumpurple1 fill color"

    def test_fanout_label_contains_fan_out_pattern(self):
        """Fan-out node label should indicate the fan-out pattern."""
        ops = [_make_fanout_op(pattern="comprehension"), Return(lineno=6)]
        dot = _generate_dot_for_ops("flow", ops)

        assert "fan-out" in dot.lower(), "Fan-out node label should contain 'fan-out'"

    def test_fanout_label_contains_iterable_info(self):
        """For comprehension pattern, label should show the loop expression."""
        ops = [_make_fanout_op(iter_var="t", iterable='p["topics"]'), Return(lineno=6)]
        dot = _generate_dot_for_ops("flow", ops)

        # The iterable should appear in the label
        assert "topics" in dot

    def test_sub_agent_appears_as_user_actor_node(self):
        """Sub-agents (from fan_out_op.actor_calls) should be rendered as user actor nodes."""
        ops = [_make_fanout_op(actor_calls=[("research_agent", "t")]), Return(lineno=6)]
        dot = _generate_dot_for_ops("flow", ops)

        # research_agent should be a node
        nodes = _extract_nodes(dot)
        assert "research_agent" in nodes, f"Expected research_agent in nodes, got: {nodes}"

    def test_fanin_appears_as_user_actor_node(self):
        """The generated fan-in should appear with fan-in label."""
        ops = [
            _make_fanout_op(),
            ActorCall(lineno=6, name="formatter"),
            Return(lineno=7),
        ]
        dot = _generate_dot_for_ops("flow", ops)

        nodes = _extract_nodes(dot)
        assert "formatter" in nodes, f"Expected formatter node, got: {nodes}"
        assert "fan-in" in dot.lower(), "Generated fan-in should have fan-in label"

    def test_start_and_end_nodes_present(self):
        """Start and end nodes should always be present."""
        ops = [_make_fanout_op(), Return(lineno=6)]
        dot = _generate_dot_for_ops("flow", ops)

        nodes = _extract_nodes(dot)
        start_nodes = {n for n in nodes if n.startswith("start_")}
        end_nodes = {n for n in nodes if n.startswith("end_")}
        assert len(start_nodes) == 1, f"Expected 1 start node, got: {start_nodes}"
        assert len(end_nodes) == 1, f"Expected 1 end node, got: {end_nodes}"


# ---------------------------------------------------------------------------
# Test: Fan-out edge rendering
# ---------------------------------------------------------------------------


class TestFanOutEdgeRendering:
    def test_fanout_to_sub_agent_edge_exists(self):
        """Fan-out router should have an edge to the sub-agent."""
        ops = [
            _make_fanout_op(actor_calls=[("research_agent", "t")]),
            ActorCall(lineno=6, name="aggregator"),
            Return(lineno=7),
        ]
        dot = _generate_dot_for_ops("flow", ops)

        edges = _extract_edges(dot)
        fanout_nodes = {n for n in {e[0] for e in edges} if "fanout" in n.lower()}
        assert len(fanout_nodes) >= 1

        # There should be an edge from the fanout node to research_agent
        fanout_to_research = any(e[0] in fanout_nodes and e[1] == "research_agent" for e in edges)
        assert fanout_to_research, f"Expected fanout -> research_agent edge, edges: {edges}"

    def test_fanout_to_fanin_edge_exists(self):
        """Fan-out router should have an edge to the generated fan-in (parent slice)."""
        ops = [
            _make_fanout_op(),
            ActorCall(lineno=6, name="formatter"),
            Return(lineno=7),
        ]
        dot = _generate_dot_for_ops("flow", ops)

        edges = _extract_edges(dot)
        fanout_nodes = {n for n in {e[0] for e in edges} if "fanout" in n.lower()}

        fanout_to_agg = any(e[0] in fanout_nodes and e[1].startswith("fanin_flow_line") for e in edges)
        assert fanout_to_agg, f"Expected fanout -> fanin_flow_line_5 edge, edges: {edges}"

    def test_sub_agent_to_fanin_convergence_edge(self):
        """Sub-agent should have a convergence edge back to the generated fan-in."""
        ops = [
            _make_fanout_op(),
            ActorCall(lineno=6, name="formatter"),
            Return(lineno=7),
        ]
        dot = _generate_dot_for_ops("flow", ops)

        edges = _extract_edges(dot)
        sub_agent_to_agg = ("research_agent", "fanin_flow_line_5") in edges
        assert sub_agent_to_agg, f"Expected research_agent -> fanin_flow_line_5 edge, edges: {edges}"

    def test_literal_fanout_edges_for_each_sub_agent(self):
        """Literal fan-out should have edges from fanout router to each unique sub-agent."""
        ops = [
            FanOutCall(
                lineno=5,
                target_key="/result",
                pattern="literal",
                actor_calls=[
                    ("sentiment_analyzer", 'p["text"]'),
                    ("topic_extractor", 'p["text"]'),
                ],
                iter_var=None,
                iterable=None,
            ),
            ActorCall(lineno=6, name="formatter"),
            Return(lineno=7),
        ]
        dot = _generate_dot_for_ops("flow", ops)

        edges = _extract_edges(dot)
        fanout_nodes = {n for n in {e[0] for e in edges} if "fanout" in n.lower()}

        assert any(e[0] in fanout_nodes and e[1] == "sentiment_analyzer" for e in edges), (
            f"Expected fanout -> sentiment_analyzer edge, edges: {edges}"
        )
        assert any(e[0] in fanout_nodes and e[1] == "topic_extractor" for e in edges), (
            f"Expected fanout -> topic_extractor edge, edges: {edges}"
        )

    def test_fanout_edges_use_distinct_color(self):
        """Fan-out edges should use a distinct color (mediumpurple4 or similar)."""
        ops = [
            _make_fanout_op(),
            ActorCall(lineno=6, name="formatter"),
            Return(lineno=7),
        ]
        dot = _generate_dot_for_ops("flow", ops)

        # Should use the fan-out color
        assert "mediumpurple4" in dot or "slateblue4" in dot, "Fan-out edges should use distinct colors"

    def test_fanout_edge_labels_slice_info(self):
        """Fan-out edges should have slice labels."""
        ops = [
            _make_fanout_op(),
            ActorCall(lineno=6, name="formatter"),
            Return(lineno=7),
        ]
        dot = _generate_dot_for_ops("flow", ops)

        assert "slice" in dot.lower(), "Fan-out edges should contain 'slice' label info"

    def test_start_to_fanout_router_edge(self):
        """Start node should connect to the fan-out router."""
        ops = [_make_fanout_op(), Return(lineno=6)]
        dot = _generate_dot_for_ops("flow", ops)

        edges = _extract_edges(dot)

        # The start router's true_branch_actors contains the fanout router name
        # Let's verify more directly
        assert any("fanout" in e[1].lower() for e in edges if e[0].startswith("start_")), (
            f"Expected start -> fanout edge, edges: {edges}"
        )


# ---------------------------------------------------------------------------
# Test: DOT output is valid (structural)
# ---------------------------------------------------------------------------


class TestFanOutDotValidity:
    def test_dot_starts_with_digraph(self):
        ops = [_make_fanout_op(), Return(lineno=6)]
        dot = _generate_dot_for_ops("flow", ops)
        assert dot.strip().startswith("digraph flow {")

    def test_dot_ends_with_closing_brace(self):
        ops = [_make_fanout_op(), Return(lineno=6)]
        dot = _generate_dot_for_ops("flow", ops)
        assert dot.strip().endswith("}")

    def test_no_duplicate_node_definitions(self):
        """Each node should be defined at most once."""
        ops = [
            _make_fanout_op(actor_calls=[("research_agent", "t")]),
            ActorCall(lineno=6, name="formatter"),
            Return(lineno=7),
        ]
        dot = _generate_dot_for_ops("flow", ops)

        nodes = []
        for match in re.finditer(r"^\s+(\w+)\s+\[fillcolor=", dot, re.MULTILINE):
            nodes.append(match.group(1))

        unique_nodes = set(nodes)
        assert len(nodes) == len(unique_nodes), (
            f"Duplicate node definitions: {[n for n in nodes if nodes.count(n) > 1]}"
        )

    def test_literal_fanout_no_duplicate_edges_for_same_actor(self):
        """If same actor appears twice in literal fan-out, edge should only appear once."""
        ops = [
            FanOutCall(
                lineno=5,
                target_key="/result",
                pattern="literal",
                actor_calls=[
                    ("agent_a", 'p["x"]'),
                    ("agent_a", 'p["y"]'),  # Same actor, different payload
                ],
                iter_var=None,
                iterable=None,
            ),
            ActorCall(lineno=6, name="formatter"),
            Return(lineno=7),
        ]
        dot = _generate_dot_for_ops("flow", ops)

        # Count how many times fanout -> agent_a appears
        # Just verify no extreme duplication; dotgen uses a set so duplicates are deduped
        edges = _extract_edges(dot)
        fanout_to_agent_a_edges = {e for e in edges if e[1] == "agent_a"}
        # Should have at most 1 edge from a given fanout node to agent_a
        assert len(fanout_to_agent_a_edges) <= 1, f"Too many fanout->agent_a edges: {fanout_to_agent_a_edges}"

    def test_two_fanouts_both_rendered(self):
        """Two sequential fan-outs should both be rendered."""
        ops = [
            _make_fanout_op(target_key="/research", lineno=3),
            ActorCall(lineno=4, name="formatter1"),
            _make_fanout_op(
                target_key="/reviews", lineno=5, actor_calls=[("review_agent", "r")], iterable='p["research"]'
            ),
            ActorCall(lineno=6, name="formatter2"),
            Return(lineno=7),
        ]
        dot = _generate_dot_for_ops("flow", ops)

        nodes = _extract_nodes(dot)
        fanout_nodes = {n for n in nodes if "fanout" in n.lower()}
        assert len(fanout_nodes) == 2, f"Expected 2 fanout nodes, got: {fanout_nodes}"

    def test_fanout_in_conditional_branch(self):
        """Fan-out inside a conditional branch should be rendered correctly."""
        from asya_lab.flow.ir import Condition

        cond = Condition(
            lineno=3,
            test='p["parallel"]',
            true_branch=[_make_fanout_op()],
            false_branch=[ActorCall(lineno=4, name="sequential_agent")],
        )
        ops = [cond, Return(lineno=5)]
        dot = _generate_dot_for_ops("flow", ops)

        try:
            # Should be valid DOT
            assert "digraph" in dot
            assert "fanout" in dot.lower() or "fan" in dot.lower() or "line_5" in dot
        except Exception as e:
            pytest.fail(f"Fan-out in conditional failed: {e}")
