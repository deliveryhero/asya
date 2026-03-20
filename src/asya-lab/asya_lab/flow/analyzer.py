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
    warnings: list[str] = field(default_factory=list)


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


def _collect_slices_targets(func_node: ast.AST) -> tuple[list[str], str | None]:
    """Collect handler names from _slices.append((resolve("name"), ...)) patterns.

    Fanout codegen populates _slices with (actor, payload) tuples:
        _slices.append((resolve("research_agent"), t))

    Returns (slice_targets, fanout_label):
    - slice_targets: handler names used as fanout slice targets
    - fanout_label: e.g. "fanout: p['topics']" (from for-loop iterable) or "fanout"
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

    if not targets:
        return [], None

    # Extract for-loop iterable for the fanout label
    for node in ast.walk(func_node):
        if not isinstance(node, ast.For):
            continue
        # Check if this for-loop body contains _slices.append
        if any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "append"
            and isinstance(child.func.value, ast.Name)
            and child.func.value.id == "_slices"
            for child in ast.walk(node)
        ):
            return targets, f"fanout: {ast.unparse(node.iter)}"

    return targets, "fanout"


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
    slice_targets, fanout_label = _collect_slices_targets(func_node)

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
                pass  # Empty route list = leaf node, no edge needed
            else:
                for chain in append_chains:
                    names = [t[0] for t in chain]
                    condition = chain[0][1]
                    edges.extend(_chain_to_edges(handler_name, names, condition, edge_type))
        elif isinstance(targets_node, ast.List) and not targets_node.elts:
            pass  # Empty route list = leaf node, no edge needed

    # Fanout slice edges: router → each slice actor → aggregator
    if slice_targets:
        agg_name = resolve_vars.get("_agg")
        # Label the router → fanin edge with the fanout info
        if agg_name and fanout_label:
            for edge in edges:
                if edge["from"] == handler_name and edge["to"] == agg_name and edge["type"] == "set":
                    edge["label"] = fanout_label
                    break
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
            elif isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                # Plain string target: ["actor_name"] (used in handler overrides)
                targets.append(elt.value)

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
    get an "else" label to show they take the false path.
    """
    current = target_node
    while id(current) in parent_map:
        parent = parent_map[id(current)]
        if isinstance(parent, ast.If):
            test_str = ast.unparse(parent.test)
            if _node_in_else_branch(parent, current):
                return "else"
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

    Runs iteratively because splicing can create new continuation edges that
    enable further splicing at deeper nesting levels.
    """
    for _ in range(20):
        if not _splice_one_pass(edges):
            break


def _splice_one_pass(edges: list[dict]) -> bool:
    """Single pass of prepend-continuation splicing. Returns True if changes made."""
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
                # Skip when prepend goes directly to the continuation target
                # (e.g., loop-back: if_3 prepends while_1 AND has continuation to while_1)
                if prep_edge["to"] == cont_target:
                    continue
                chain_end = _find_chain_end(prep_edge["to"], edges)
                if chain_end != cont_target and chain_end != node:
                    edges_to_add.append({"from": chain_end, "to": cont_target, "label": None, "type": "continuation"})

            edges_to_remove.append(cont_edge)

    if not edges_to_add and not edges_to_remove:
        return False

    for edge in edges_to_remove:
        if edge in edges:
            edges.remove(edge)
    edges.extend(edges_to_add)
    return True


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


def _ensure_else_edges(edges: list[dict]) -> list[str]:
    """Ensure every if router has both a conditional and an else edge.

    After splice, some if routers may have:
    1. A conditional edge + unlabeled continuation → label the continuation "else"
    2. A conditional edge + no else edge → add "else" edge to the merge point

    The merge point is found by following the true branch's prepend chain to its
    end — that's where both paths converge at runtime.

    Returns warnings for if routers where the else edge could not be determined.
    """
    warnings: list[str] = []

    # Find if routers
    if_routers: set[str] = set()
    for e in edges:
        if "_if_" in e["from"] and e["from"].startswith("router_"):
            if_routers.add(e["from"])

    for router in sorted(if_routers):
        outgoing = [e for e in edges if e["from"] == router]

        # Conditional edges: labeled with a condition (not "else", not None)
        conditional = [e for e in outgoing if e.get("label") and e["label"] != "else"]
        if not conditional:
            continue

        # Already has an else edge
        if any(e.get("label") == "else" for e in outgoing):
            continue

        # Case 1: unlabeled continuation → label it "else"
        unlabeled_cont = [e for e in outgoing if e.get("label") is None and e["type"] == "continuation"]
        if unlabeled_cont:
            for ue in unlabeled_cont:
                ue["label"] = "else"
            continue

        # Case 2: no else edge at all → find merge point via chain end
        found = False
        for cond_edge in conditional:
            if cond_edge["type"] == "prepend":
                chain_end = _find_chain_end(cond_edge["to"], edges)
                if chain_end != router:
                    edges.append({"from": router, "to": chain_end, "label": "else", "type": "continuation"})
                    found = True
                    break

        if not found:
            warnings.append(f"if router '{router}' has no else edge and merge point could not be determined")

    return warnings


def _deduplicate_edges(edges: list[dict]) -> None:
    """Remove truly duplicate edges (same from/to/type/label)."""
    seen: set[tuple[str, str, str, str | None]] = set()
    i = 0
    while i < len(edges):
        e = edges[i]
        key = (e["from"], e["to"], e["type"], e.get("label"))
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
    router_mutations: dict[str, list[str]] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            func_edges = _extract_yield_edges(node, node.name)
            all_edges.extend(func_edges)
            router_names.add(node.name)
            mutations = _extract_mutations(node)
            if mutations:
                router_mutations[node.name] = mutations

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

    # Step 4b: Propagate fanout continuations through fanin.
    # The fanout router's parent chain sets up continuation (e.g., router → formatter).
    # At runtime, fanin passes to whatever follows in _next_tail. Connect fanin → continuation.
    _propagate_fanin_continuations(all_edges)

    # Step 4c: Ensure every if router has an else edge.
    # Splice may remove continuation edges that represent the else path (when the
    # codegen emits `else: pass`). Restore them as labeled "else" edges, and label
    # any unlabeled continuations from if routers as "else".
    all_warnings: list[str] = []
    all_warnings.extend(_ensure_else_edges(all_edges))

    # Step 5: Deduplicate edges (same from/to/type can appear from multiple branches).
    _deduplicate_edges(all_edges)

    # Build nodes from all referenced names
    all_names: set[str] = set()
    for edge in all_edges:
        all_names.add(edge["from"])
        all_names.add(edge["to"])

    nodes = []
    for name in sorted(all_names):
        is_generated = name in router_names
        flow_role = _determine_flow_role(name, router_names, all_edges)
        node_dict: dict = {
            "id": name,
            "flow_role": flow_role,
            "label": name,
            "is_generated": is_generated,
        }
        if name in router_mutations:
            node_dict["mutations"] = router_mutations[name]
        nodes.append(node_dict)

    graph = GraphData(nodes=nodes, edges=all_edges)
    all_warnings.extend(_validate_graph(graph))
    graph.warnings = all_warnings
    return graph


def _validate_graph(graph: GraphData) -> list[str]:
    """Validate graph invariants and return warnings for violations.

    Checks:
    1. Fully connected: every node is reachable from the start node
    2. Disconnected sources: nodes with outgoing but no incoming edges must be start nodes
    3. If routers must have both conditional and else edges
    """
    warnings: list[str] = []
    node_ids = {n["id"] for n in graph.nodes}
    sources = {e["from"] for e in graph.edges}
    targets = {e["to"] for e in graph.edges}

    # Build adjacency for reachability
    adjacency: dict[str, set[str]] = {n: set() for n in node_ids}
    for edge in graph.edges:
        adjacency[edge["from"]].add(edge["to"])

    # Check 1: Reachability from start node
    start_nodes = [n["id"] for n in graph.nodes if n["flow_role"] == "start"]
    if start_nodes:
        reachable: set[str] = set()
        stack = list(start_nodes)
        while stack:
            current = stack.pop()
            if current in reachable:
                continue
            reachable.add(current)
            stack.extend(adjacency.get(current, set()))
        unreachable = node_ids - reachable
        for node_id in sorted(unreachable):
            warnings.append(f"node '{node_id}' is not reachable from start")

    # Check 2: Nodes that are sources but not targets (and not start nodes) are disconnected
    for node_id in sorted(sources - targets):
        node = next((n for n in graph.nodes if n["id"] == node_id), None)
        if node and node["flow_role"] != "start":
            warnings.append(f"node '{node_id}' has no incoming edges but is not an entry")

    # Check 4: Every if router must have both a conditional and an else edge
    for node_id in sorted(node_ids):
        if "_if_" not in node_id or not node_id.startswith("router_"):
            continue
        outgoing = [e for e in graph.edges if e["from"] == node_id]
        has_conditional = any(e.get("label") and e["label"] != "else" for e in outgoing)
        has_else = any(e.get("label") == "else" for e in outgoing)
        if has_conditional and not has_else:
            warnings.append(f"if router '{node_id}' has conditional edge but no else edge")

    # Check 5: Each generated router has at most one unconditional (unlabeled) outgoing edge.
    # Excluded: fanout edges (legitimately multi-target), handler nodes (may be reused
    # in multiple branches, each with a different continuation).
    router_ids = {n["id"] for n in graph.nodes if n.get("is_generated")}
    for node_id in sorted(router_ids):
        unlabeled = [
            e
            for e in graph.edges
            if e["from"] == node_id and not e.get("label") and e.get("type") not in ("fanout", "continuation")
        ]
        if len(unlabeled) > 1:
            unlabeled_targets = [e["to"] for e in unlabeled]
            warnings.append(
                f"router '{node_id}' has {len(unlabeled)} unconditional outgoing edges: {unlabeled_targets}"
            )

    return warnings


def _propagate_fanin_continuations(edges: list[dict]) -> None:
    """Connect fanin aggregators to the fanout router's continuation target.

    Fanout routers set route.next = [fanin, ...rest...] + _next_tail. The
    _next_tail is a runtime value containing the parent chain's continuation.
    After prepend-splicing, the fanout router's continuation edges point to the
    next step after the fanout. Connect fanin → that same target.

    When the fanout router has no direct continuation (e.g., it's in a loop body),
    walk back through the prepend chain to find a node whose continuation still
    exists, and connect the fanin to that.
    """
    # Find fanout routers (they have edges with type="fanout")
    fanout_routers: set[str] = set()
    for edge in edges:
        if edge["type"] == "fanout":
            fanout_routers.add(edge["from"])

    # Index: who prepends to whom (prepend_target → prepend_source)
    prepend_parents: dict[str, str] = {}
    for edge in edges:
        if edge["type"] == "prepend":
            prepend_parents[edge["to"]] = edge["from"]

    for router in fanout_routers:
        # Find the fanin aggregator
        fanin_name = None
        for edge in edges:
            if edge["from"] == router and edge["to"].startswith("fanin_"):
                fanin_name = edge["to"]
                break
        if not fanin_name:
            continue

        # Check if fanin already has outgoing edges
        if any(e["from"] == fanin_name for e in edges):
            continue

        # Find continuation target: first from the fanout router directly,
        # then walk back through prepend parents
        fanout_targets = {e["to"] for e in edges if e["from"] == router and e["type"] == "fanout"}
        cont_target = _find_continuation_for(router, fanin_name, fanout_targets, edges, prepend_parents)
        if cont_target:
            edges.append({"from": fanin_name, "to": cont_target, "label": None, "type": "continuation"})


def _find_continuation_for(
    node: str,
    fanin_name: str,
    fanout_targets: set[str],
    edges: list[dict],
    prepend_parents: dict[str, str],
) -> str | None:
    """Find the continuation target for a fanout router by walking its prepend ancestry."""
    visited: set[str] = set()
    current = node
    while current and current not in visited:
        visited.add(current)
        # Look for continuation edges from current (not to fanin or fanout targets)
        for edge in edges:
            if (
                edge["from"] == current
                and edge["type"] == "continuation"
                and edge["to"] != fanin_name
                and edge["to"] not in fanout_targets
            ):
                return edge["to"]
        # Walk up the prepend chain
        current = prepend_parents.get(current, "")


def _extract_mutations(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Extract payload mutation statements from a router function.

    Mutations are top-level statements that modify `p` (the payload alias):
    p['key'] = value, p['key'] += value, etc.
    Skips boilerplate: p = payload, _next, yield, resolve, _agg, _slices, etc.
    """
    mutations: list[str] = []
    for stmt in func_node.body:
        # Only look at top-level statements (and inside if/else branches)
        _collect_mutations_from_stmt(stmt, mutations)
    return mutations


def _collect_mutations_from_stmt(stmt: ast.stmt, mutations: list[str]) -> None:
    """Recursively collect mutation statements, descending into if/else."""
    if isinstance(stmt, ast.Assign):
        # p['key'] = value — target is a Subscript on Name 'p'
        if len(stmt.targets) == 1 and _is_payload_target(stmt.targets[0]):
            mutations.append(ast.unparse(stmt))
    elif isinstance(stmt, ast.AugAssign):
        # p['key'] += value
        if _is_payload_target(stmt.target):
            mutations.append(ast.unparse(stmt))
    elif isinstance(stmt, ast.If):
        for child in stmt.body:
            _collect_mutations_from_stmt(child, mutations)
        for child in stmt.orelse:
            _collect_mutations_from_stmt(child, mutations)


def _is_payload_target(node: ast.expr) -> bool:
    """Check if an assignment target is a payload mutation (p[...] or p.attr)."""
    return isinstance(node, ast.Subscript | ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "p"


def _determine_flow_role(name: str, router_names: set[str], edges: list[dict]) -> str:
    """Determine the flow role of a node.

    Roles: start, router, actor.
    """
    if name.startswith("start_"):
        return "start"
    if name.startswith("fanin_"):
        return "router"

    if name in router_names:
        return "router"
    return "actor"
