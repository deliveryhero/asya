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


def _collect_resolve_vars(func_node: ast.AST) -> dict[str, str]:
    """Collect variable assignments from resolve() calls.

    Tracks patterns like: _agg = resolve("fanin_name")
    Returns: {"_agg": "fanin_name"}
    """
    var_map: dict[str, str] = {}
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = _extract_resolve_arg(node.value)
            if name:
                var_map[node.targets[0].id] = name
    return var_map


def _collect_slices_targets(func_node: ast.AST) -> list[str]:
    """Collect handler names from _slices.append((resolve("name"), ...)) patterns.

    Fanout codegen populates _slices with (actor, payload) tuples:
        _slices.append((resolve("research_agent"), t))

    Returns list of handler names used as fanout slice targets.
    """
    targets: list[str] = []
    for node in ast.walk(func_node):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "append"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "_slices"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Tuple)
            and len(node.args[0].elts) >= 1
        ):
            name = _extract_resolve_arg(node.args[0].elts[0])
            if name:
                targets.append(name)
    return targets


def _is_in_slices_loop(parent_map: dict[int, ast.AST], node: ast.AST) -> bool:
    """Check if a node is inside a for-loop iterating over _slices."""
    current = node
    while id(current) in parent_map:
        parent = parent_map[id(current)]
        if isinstance(parent, ast.For):
            iter_node = parent.iter
            if isinstance(iter_node, ast.Name) and iter_node.id == "_slices":
                return True
            if (
                isinstance(iter_node, ast.Call)
                and isinstance(iter_node.func, ast.Name)
                and iter_node.func.id == "enumerate"
                and len(iter_node.args) == 1
                and isinstance(iter_node.args[0], ast.Name)
                and iter_node.args[0].id == "_slices"
            ):
                return True
        current = parent
    return False


def _extract_yield_edges(func_node: ast.AST, handler_name: str) -> list[dict]:
    """Extract yield ABI patterns from an AST function node.

    Walks the AST to find yield expressions matching the ABI protocol:
    - yield "SET", ".route.next", [...]  -> explicit routing edge
    - yield "SET", ".route.next[:0]", [...]  -> prepend routing edge
    - yield "SET", ".route.next[:0]", _next  -> prepend via variable (codegen pattern)
    - yield "SET", ".route.next", [a, b] + tail  -> BinOp list concat (fanout parent yield)
    - yield "SET", ".route.next", []  -> abort / terminal
    - yield payload  -> implicit pass-through
    - yield "FLY", {...}  -> no routing edge (streaming only)

    Returns list of edge dicts: {"from": handler_name, "to": target, "label": condition, "type": edge_type}
    """
    edges: list[dict] = []
    parent_map = _build_parent_map(func_node)
    # Pre-collect targets from _next.append(resolve(...)) grouped by branch
    append_chains = _collect_append_chains(func_node, parent_map)
    # Track resolve() variable assignments for fanout patterns
    resolve_vars = _collect_resolve_vars(func_node)
    # Collect fanout slice targets from _slices.append((resolve("name"), ...))
    slice_targets = _collect_slices_targets(func_node)

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

        # Skip yields inside for-loops over _slices — handled separately below
        if slice_targets and _is_in_slices_loop(parent_map, node):
            continue

        edge_type = "prepend" if "[:0]" in path_str else "set"

        # Extract target names from resolve() calls in the list literal or BinOp
        inline_targets = _extract_resolve_targets(targets_node, resolve_vars)

        if inline_targets:
            # Inline list literal or BinOp: build sequential chain
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

    # Fanout slice edges: router → each slice actor → aggregator
    if slice_targets:
        agg_name = resolve_vars.get("_agg")
        for target in slice_targets:
            edges.append({"from": handler_name, "to": target, "label": None, "type": "fanout"})
            if agg_name:
                edges.append({"from": target, "to": agg_name, "label": None, "type": "continuation"})

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


def _extract_resolve_targets(node: ast.expr, resolve_vars: dict[str, str] | None = None) -> list[str]:
    """Extract handler names from resolve() calls in a list expression.

    Handles:
    - Plain list: [resolve("a"), resolve("b")]
    - Variable references: [_agg, resolve("b")] where _agg = resolve("fanin_...")
    - BinOp (list concat): [resolve("a"), _agg] + _next_tail — extracts from left list
    """
    resolve_vars = resolve_vars or {}
    targets: list[str] = []

    # Handle BinOp: [targets...] + variable — extract from the list portion
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        if isinstance(node.left, ast.List):
            return _extract_resolve_targets(node.left, resolve_vars)
        return []

    if isinstance(node, ast.List):
        for elt in node.elts:
            name = _extract_resolve_arg(elt)
            if name:
                targets.append(name)
            elif isinstance(elt, ast.Name) and elt.id in resolve_vars:
                targets.append(resolve_vars[elt.id])

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


def _splice_prepend_continuations(edges: list[dict]) -> None:
    """Splice prepend chains into continuation chains.

    When router R prepends [P] and has a continuation edge R → C (from a parent
    chain), the runtime route is [..., P, C, ...]. This function rewrites edges
    to reflect the actual runtime ordering:
    - Find the end of each prepend chain (follow continuations from prepend target)
    - Connect chain end → C (continuation)
    - Remove R → C (now routed through the prepend chain)
    """
    from collections import defaultdict

    outgoing: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for edge in edges:
        outgoing[edge["from"]][edge["type"]].append(edge)

    edges_to_add: list[dict] = []
    edges_to_remove: list[dict] = []

    for node, by_type in outgoing.items():
        prepend_edges = by_type.get("prepend", [])
        continuation_edges = by_type.get("continuation", [])

        if not prepend_edges or not continuation_edges:
            continue

        for cont_edge in continuation_edges:
            cont_target = cont_edge["to"]

            for prep_edge in prepend_edges:
                chain_end = _find_chain_end(prep_edge["to"], edges)
                if chain_end != cont_target and chain_end != node:
                    edges_to_add.append({"from": chain_end, "to": cont_target, "label": None, "type": "continuation"})

            edges_to_remove.append(cont_edge)

    for edge in edges_to_remove:
        if edge in edges:
            edges.remove(edge)
    edges.extend(edges_to_add)


def _find_chain_end(node: str, edges: list[dict]) -> str:
    """Follow continuation edges from node to find the chain end (leaf)."""
    visited = {node}
    current = node
    while True:
        next_nodes = [e["to"] for e in edges if e["from"] == current and e["type"] == "continuation"]
        if not next_nodes or next_nodes[0] in visited:
            return current
        current = next_nodes[0]
        visited.add(current)


def _deduplicate_edges(edges: list[dict]) -> None:
    """Remove duplicate edges with the same from/to/type."""
    seen: set[tuple[str, str, str]] = set()
    i = 0
    while i < len(edges):
        key = (edges[i]["from"], edges[i]["to"], edges[i]["type"])
        if key in seen:
            edges.pop(i)
        else:
            seen.add(key)
            i += 1


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

    # Step 4: Splice prepend chains into continuation chains.
    # When router R prepends [P1, P2] and has continuation R → C (from a parent chain),
    # the runtime route becomes [..., P1, P2, C, ...]. Rewrite the graph edges to
    # reflect this: connect the last prepended handler to C, remove R → C.
    _splice_prepend_continuations(all_edges)

    # Step 5: Deduplicate edges (same from/to/type can appear from multiple branches).
    _deduplicate_edges(all_edges)

    # Step 6: Connect endpoint handlers to end_ node (implicit flow continuation).
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
    if name.startswith("fanin_"):
        return "router"

    # Check if it's a target of any edge but not a source -> could be exit
    is_source = any(e["from"] == name for e in edges)
    is_target = any(e["to"] == name for e in edges)

    if is_target and not is_source:
        return "actor"
    if name in router_names:
        return "router"
    return "actor"
