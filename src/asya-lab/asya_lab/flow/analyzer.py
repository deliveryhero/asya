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


def _build_parent_map(tree: ast.AST) -> dict[int, ast.AST]:
    """Build a child-id → parent mapping for an AST tree."""
    parent_map: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent_map[id(child)] = node
    return parent_map


def _collect_append_chains(
    func_node: ast.AST, parent_map: dict[int, ast.AST], var_name: str = "_next"
) -> list[list[tuple[str, str | None]]]:
    """Collect resolve() args from var.append(resolve("name")) calls, grouped by branch.

    The generated codegen builds sequential route lists via:
        _next = []
        if condition:
            _next.append(resolve("foo"))    # branch 1, step 1
            _next.append(resolve("bar"))    # branch 1, step 2
        else:
            _next.append(resolve("baz"))    # branch 2, step 1

    Returns a list of chains, where each chain is the sequence of targets
    within one branch. Each target is (name, condition_label).
    The route list [a, b] means a sequential chain: router → a → b.
    """
    # Collect all (name, condition) pairs in AST order
    all_targets: list[tuple[str, str | None]] = []
    for node in ast.walk(func_node):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "append"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == var_name
            and len(node.args) == 1
        ):
            name = _extract_resolve_arg(node.args[0])
            if name:
                condition = _find_enclosing_condition(parent_map, node)
                all_targets.append((name, condition))

    if not all_targets:
        return []

    # Group consecutive targets with the same condition into chains
    chains: list[list[tuple[str, str | None]]] = []
    current_chain: list[tuple[str, str | None]] = [all_targets[0]]
    for target in all_targets[1:]:
        if target[1] == current_chain[0][1]:
            current_chain.append(target)
        else:
            chains.append(current_chain)
            current_chain = [target]
    chains.append(current_chain)

    return chains


def _extract_yield_edges(func_node: ast.AST, handler_name: str) -> list[dict]:
    """Extract yield ABI patterns from an AST function node.

    Walks the AST to find yield expressions matching the ABI protocol:
    - yield "SET", ".route.next", [...]  -> explicit routing edge
    - yield "SET", ".route.next[:0]", [...]  -> prepend routing edge
    - yield "SET", ".route.next[:0]", _next  -> prepend via variable (codegen pattern)
    - yield "SET", ".route.next", []  -> abort / terminal
    - yield payload  -> implicit pass-through
    - yield "FLY", {...}  -> no routing edge (streaming only)

    Returns list of edge dicts: {"from": handler_name, "to": target, "label": condition, "type": edge_type}
    """
    edges: list[dict] = []
    parent_map = _build_parent_map(func_node)
    # Pre-collect targets from _next.append(resolve(...)) grouped by branch
    append_chains = _collect_append_chains(func_node, parent_map)

    for node in ast.walk(func_node):
        if not isinstance(node, ast.Yield | ast.YieldFrom):
            continue
        if not isinstance(node, ast.Yield) or node.value is None:
            continue

        value = node.value

        # Match: yield "SET", ".route.next...", [targets] or _next
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

        # Extract target names from resolve() calls in the list literal
        inline_targets = _extract_resolve_targets(targets_node)

        if inline_targets:
            # Inline list literal: build sequential chain
            condition = _find_enclosing_condition(parent_map, node)
            edges.extend(_chain_to_edges(handler_name, inline_targets, condition, edge_type))
        elif isinstance(targets_node, ast.Name) and targets_node.id == "_next":
            # Variable reference: each branch is a sequential chain
            if not append_chains:
                if edge_type == "set":
                    condition = _find_enclosing_condition(parent_map, node)
                    edges.append(
                        {
                            "from": handler_name,
                            "to": "__terminal__",
                            "label": condition,
                            "type": "abort",
                        }
                    )
            else:
                for chain in append_chains:
                    names = [t[0] for t in chain]
                    condition = chain[0][1]
                    edges.extend(_chain_to_edges(handler_name, names, condition, edge_type))
        elif isinstance(targets_node, ast.List) and not targets_node.elts:
            # yield "SET", ".route.next", [] -> abort/terminal
            if edge_type == "set":
                condition = _find_enclosing_condition(parent_map, node)
                edges.append(
                    {
                        "from": handler_name,
                        "to": "__terminal__",
                        "label": condition,
                        "type": "abort",
                    }
                )

    return edges


def _chain_to_edges(source: str, targets: list[str], condition: str | None, edge_type: str) -> list[dict]:
    """Convert a sequential route chain into graph edges.

    Route list [a, b, c] means: source → a → b → c (sequential).
    Only the first edge (source → a) carries the condition label.
    Subsequent edges (a → b, b → c) are unconditional continuations.
    """
    if not targets:
        return []
    result: list[dict] = [{"from": source, "to": targets[0], "label": condition, "type": edge_type}]
    for i in range(len(targets) - 1):
        result.append({"from": targets[i], "to": targets[i + 1], "label": None, "type": "continuation"})
    return result


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


def _find_enclosing_condition(parent_map: dict[int, ast.AST], target_node: ast.AST) -> str | None:
    """Walk up the AST to find the nearest enclosing if condition for a node.

    Distinguishes between if-body and else-body: nodes in the else branch
    get a "not (...)" label to show they take the false path.
    """
    current = target_node
    while id(current) in parent_map:
        parent = parent_map[id(current)]
        if isinstance(parent, ast.If):
            test_str = ast.unparse(parent.test)
            # Determine if current is in the if-body or else-body
            if _node_in_else_branch(parent, current):
                return f"not ({test_str})"
            return test_str
        current = parent
    return None


def _node_in_else_branch(if_node: ast.If, child: ast.AST) -> bool:
    """Check if child is contained in the else branch of an if statement."""
    return any(stmt is child or _ast_contains(stmt, child) for stmt in if_node.orelse)


def _ast_contains(tree: ast.AST, target: ast.AST) -> bool:
    """Check if target node is anywhere inside tree."""
    return any(node is target for node in ast.walk(tree))


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
            func_edges = _extract_yield_edges(node, node.name)
            all_edges.extend(func_edges)
            router_names.add(node.name)

    # Step 2: Extract edges from user handlers (best-effort)
    for handler_name, source in handler_sources.items():
        try:
            handler_tree = ast.parse(source)
        except SyntaxError:
            continue
        for func_node in ast.walk(handler_tree):
            if isinstance(func_node, ast.FunctionDef | ast.AsyncFunctionDef):
                handler_edges = _extract_yield_edges(func_node, handler_name)
                for edge in handler_edges:
                    edge["override"] = True
                all_edges.extend(handler_edges)

    # Step 3: TODO - Parse manifests for resiliency.rules error routing

    # Step 4: Connect endpoint handlers to end_ node (implicit flow continuation).
    # The end_ router is in the initial route.next; start_ prepends before it.
    # Endpoint handlers are leaf nodes that sit at the end of continuation chains
    # (e.g., handler_finalize), not intermediate dispatch targets (e.g., handler_type_b).
    end_nodes = [n for n in router_names if n.startswith("end_")]
    if end_nodes:
        sources = {e["from"] for e in all_edges}
        targets = {e["to"] for e in all_edges if e["to"] != "__terminal__"}
        leaf_handlers = targets - sources
        # Prefer leaf handlers that are continuation targets (final chain steps)
        continuation_targets = {e["to"] for e in all_edges if e["type"] == "continuation"}
        endpoints = leaf_handlers & continuation_targets
        if not endpoints:
            # Simple flows with no continuation edges — all leaves are endpoints
            endpoints = leaf_handlers
        for end_node in end_nodes:
            for ep in sorted(endpoints):
                all_edges.append({"from": ep, "to": end_node, "label": None, "type": "continuation"})

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
