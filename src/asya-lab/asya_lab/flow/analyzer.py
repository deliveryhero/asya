"""Static yield analysis for graph topology extraction.

Reads generated router code and user handler source to extract routing
edges via AST pattern matching on yield ABI events.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field


@dataclass
class GraphData:
    """Graph topology extracted from yield analysis."""

    nodes: list[dict] = field(default_factory=list)  # {"id", "flow_role", "label", "is_generated"}
    edges: list[dict] = field(default_factory=list)  # {"from", "to", "label", "type", "override"}
    groups: list[dict] = field(default_factory=list)  # {"id", "nodes"}


def _extract_yield_edges(source: str, handler_name: str) -> list[dict]:
    """Parse yield ABI patterns from a Python handler source.

    Walks the AST to find yield expressions matching the ABI protocol:
    - yield "SET", ".route.next", [...]  -> explicit routing edge
    - yield "SET", ".route.next[:0]", [...]  -> prepend routing edge
    - yield "SET", ".route.next", []  -> abort / terminal
    - yield payload  -> implicit pass-through
    - yield "FLY", {...}  -> no routing edge (streaming only)

    Returns list of edge dicts: {"from": handler_name, "to": target, "label": condition, "type": edge_type}
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    edges: list[dict] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Yield | ast.YieldFrom):
            continue
        if not isinstance(node, ast.Yield) or node.value is None:
            continue

        value = node.value

        # Match: yield "SET", ".route.next...", [targets]
        if not isinstance(value, ast.Tuple) or len(value.elts) < 3:
            continue

        cmd_node, path_node, targets_node = value.elts[0], value.elts[1], value.elts[2]

        if not isinstance(cmd_node, ast.Constant) or cmd_node.value != "SET":
            continue
        if not isinstance(path_node, ast.Constant):
            continue

        path_str = path_node.value
        if not isinstance(path_str, str) or not path_str.startswith(".route.next"):
            continue

        edge_type = "prepend" if "[:0]" in path_str else "set"

        # Extract target names from resolve() calls in the list
        targets = _extract_resolve_targets(targets_node)

        # Walk up AST to find enclosing if condition
        condition = _find_enclosing_condition(tree, node)

        if not targets and edge_type == "set":
            # yield "SET", ".route.next", [] -> abort/terminal
            edges.append(
                {
                    "from": handler_name,
                    "to": "__terminal__",
                    "label": condition,
                    "type": "abort",
                }
            )
        else:
            for target in targets:
                edges.append(
                    {
                        "from": handler_name,
                        "to": target,
                        "label": condition,
                        "type": edge_type,
                    }
                )

    return edges


def _extract_resolve_targets(node: ast.expr) -> list[str]:
    """Extract handler names from resolve() calls in a list expression."""
    targets: list[str] = []

    if isinstance(node, ast.List):
        for elt in node.elts:
            name = _extract_resolve_arg(elt)
            if name:
                targets.append(name)

    return targets


def _extract_resolve_arg(node: ast.expr) -> str | None:
    """Extract the string argument from a resolve("name") call."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "resolve"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        return node.args[0].value
    return None


def _find_enclosing_condition(tree: ast.Module, target_node: ast.AST) -> str | None:
    """Walk up the AST to find the nearest enclosing if condition for a node."""
    # Build parent map
    parent_map: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent_map[id(child)] = node

    current = target_node
    while id(current) in parent_map:
        parent = parent_map[id(current)]
        if isinstance(parent, ast.If):
            return ast.unparse(parent.test)
        current = parent
    return None


def analyze(
    routers_source: str,
    handler_sources: dict[str, str] | None = None,
) -> GraphData:
    """Analyze generated routers and user handlers to build graph topology.

    Steps:
    1. Parse generated routers -> extract yield edges
    2. Parse user handlers (if source available) -> extract override edges
    3. Merge: router edges + override edges

    Args:
        routers_source: Python source of generated routers.py
        handler_sources: Dict of {handler_name: source_code} for user handlers

    Returns:
        GraphData with nodes, edges, and groups
    """
    handler_sources = handler_sources or {}

    # Step 1: Extract edges from generated routers
    try:
        tree = ast.parse(routers_source)
    except SyntaxError:
        return GraphData()

    all_edges: list[dict] = []
    router_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            func_source = ast.unparse(node)
            func_edges = _extract_yield_edges(func_source, node.name)
            all_edges.extend(func_edges)
            router_names.add(node.name)

    # Step 2: Extract edges from user handlers (best-effort)
    for handler_name, source in handler_sources.items():
        handler_edges = _extract_yield_edges(source, handler_name)
        for edge in handler_edges:
            edge["override"] = True
        all_edges.extend(handler_edges)

    # Step 3: TODO - Parse manifests for resiliency.rules error routing

    # Build nodes from all referenced names
    all_names: set[str] = set()
    for edge in all_edges:
        all_names.add(edge["from"])
        if edge["to"] != "__terminal__":
            all_names.add(edge["to"])

    nodes = []
    for name in sorted(all_names):
        is_generated = name in router_names
        flow_role = _determine_flow_role(name, router_names, all_edges)
        nodes.append(
            {
                "id": name,
                "flow_role": flow_role,
                "label": name,
                "is_generated": is_generated,
            }
        )

    return GraphData(nodes=nodes, edges=all_edges)


def _determine_flow_role(name: str, router_names: set[str], edges: list[dict]) -> str:
    """Determine the flow role of a node."""
    if name.startswith("start_"):
        return "entry"
    if name.startswith("end_"):
        return "exit"

    # Check if it's a target of any edge but not a source -> could be exit
    is_source = any(e["from"] == name for e in edges)
    is_target = any(e["to"] == name for e in edges)

    if is_target and not is_source:
        return "actor"
    if name in router_names:
        return "router"
    return "actor"
