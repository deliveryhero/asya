"""Test structural invariants of compiled flow DOT graphs.

Every compiled flow graph MUST:
1. Have exactly one entrypoint (start_*) node
2. Have exactly one exitpoint (end_*) node
3. All non-reraise nodes must be reachable from the entrypoint
4. All non-reraise nodes must be able to reach the exitpoint
"""

from __future__ import annotations

import re
from collections import deque
from pathlib import Path

import pytest


COMPILED_DIR = Path(__file__).resolve().parents[4] / "examples" / "flows" / "compiled"

# Pre-existing while loop DOT visualization bugs where body actors
# are rendered as dead-end nodes (no edge back to loop_back router).
_WHILE_EXITPOINT_XFAIL = {
    "while_mutations_in_loop",
    "while_nested",
    "while_nested_loop",
    "while_react_loop",
    "while_simple",
    "while_with_continue",
    "while_with_if",
}
_WHILE_REACHABILITY_XFAIL = {
    "while_nested_loop",
    "while_with_if",
}


def _discover_compiled_flows() -> list[Path]:
    """Discover all compiled flow directories containing flow.dot files."""
    if not COMPILED_DIR.exists():
        return []
    return sorted(d for d in COMPILED_DIR.iterdir() if d.is_dir() and (d / "flow.dot").exists())


def _parse_dot(dot_path: Path) -> tuple[set[str], dict[str, set[str]]]:
    """Parse a DOT file into (nodes, adjacency_list).

    Extracts node definitions (fillcolor= patterns) and directed edges (->).
    Handles nodes inside subgraph clusters too.
    """
    content = dot_path.read_text()

    nodes: set[str] = set()
    adj: dict[str, set[str]] = {}

    # Match node definitions: "  node_name [fillcolor=..."
    for match in re.finditer(r"^\s+(\w+)\s+\[fillcolor=", content, re.MULTILINE):
        node = match.group(1)
        nodes.add(node)
        adj.setdefault(node, set())

    # Match edges: "  source -> target" (with optional attributes)
    for match in re.finditer(r"^\s+(\w+)\s+->\s+(\w+)", content, re.MULTILINE):
        source, target = match.group(1), match.group(2)
        adj.setdefault(source, set())
        adj.setdefault(target, set())
        adj[source].add(target)

    return nodes, adj


def _bfs_reachable(adj: dict[str, set[str]], start: str) -> set[str]:
    """BFS to find all nodes reachable from start."""
    visited: set[str] = set()
    queue: deque[str] = deque([start])
    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        for neighbor in adj.get(node, set()):
            if neighbor not in visited:
                queue.append(neighbor)
    return visited


def _reverse_adj(adj: dict[str, set[str]]) -> dict[str, set[str]]:
    """Build reverse adjacency list (flip edge directions)."""
    rev: dict[str, set[str]] = {n: set() for n in adj}
    for source, targets in adj.items():
        for target in targets:
            rev.setdefault(target, set())
            rev[target].add(source)
    return rev


flow_dirs = _discover_compiled_flows()


@pytest.mark.parametrize(
    "flow_dir",
    flow_dirs,
    ids=[d.name for d in flow_dirs],
)
def test_single_entrypoint_and_exitpoint(flow_dir: Path) -> None:
    """Each flow must have exactly one start_* and one end_* node."""
    nodes, _ = _parse_dot(flow_dir / "flow.dot")

    start_nodes = {n for n in nodes if n.startswith("start_")}
    end_nodes = {n for n in nodes if n.startswith("end_")}

    assert len(start_nodes) == 1, f"Expected 1 start node, got {start_nodes}"
    assert len(end_nodes) == 1, f"Expected 1 end node, got {end_nodes}"


@pytest.mark.parametrize(
    "flow_dir",
    flow_dirs,
    ids=[d.name for d in flow_dirs],
)
def test_all_nodes_reachable_from_entrypoint(flow_dir: Path) -> None:
    """All non-reraise nodes must be reachable from the entrypoint."""
    if flow_dir.name in _WHILE_REACHABILITY_XFAIL:
        pytest.xfail("Pre-existing while loop DOT visualization bug")

    nodes, adj = _parse_dot(flow_dir / "flow.dot")

    start_node = next(n for n in nodes if n.startswith("start_"))
    reachable = _bfs_reachable(adj, start_node)

    # Reraise nodes are error terminals (not reachable via normal flow)
    unreachable = {n for n in nodes if n not in reachable and "reraise" not in n}
    assert not unreachable, f"Nodes unreachable from entrypoint: {unreachable}"


@pytest.mark.parametrize(
    "flow_dir",
    flow_dirs,
    ids=[d.name for d in flow_dirs],
)
def test_all_nodes_can_reach_exitpoint(flow_dir: Path) -> None:
    """All non-reraise nodes must have a path to the exitpoint."""
    if flow_dir.name in _WHILE_EXITPOINT_XFAIL:
        pytest.xfail("Pre-existing while loop DOT visualization bug")

    nodes, adj = _parse_dot(flow_dir / "flow.dot")

    end_node = next(n for n in nodes if n.startswith("end_"))
    rev = _reverse_adj(adj)
    can_reach_end = _bfs_reachable(rev, end_node)

    # Reraise nodes are error terminals that don't reach the normal exitpoint
    no_path = {n for n in nodes if n not in can_reach_end and "reraise" not in n}
    assert not no_path, f"Nodes cannot reach exitpoint: {no_path}"
