"""Graph rendering: DOT, Mermaid, and JSON from GraphData.

Replaces the 783-line dotgen.py with ~150 lines covering three output formats.
"""

from __future__ import annotations

import json

from asya_lab.flow.analyzer import GraphData


def to_dot(data: GraphData, flow_name: str) -> str:
    """Render GraphData as a Graphviz DOT graph."""
    lines = [f'digraph "{flow_name}" {{']
    lines.append("    rankdir=TB;")
    lines.append('    node [shape=box, style=filled, fontname="Helvetica"];')
    lines.append("")

    # Derive exit nodes from topology: nodes with no outgoing edges
    sources = {e["from"] for e in data.edges}
    targets = {e["to"] for e in data.edges}
    node_ids = {n["id"] for n in data.nodes}
    exitpoints = [_sanitize_id(nid) for nid in sorted(node_ids - sources) if nid in targets]

    # Pin start_ to top
    start_ids = [_sanitize_id(n["id"]) for n in data.nodes if n.get("role") == "start"]
    if start_ids:
        lines.append("    { rank=source; " + "; ".join(start_ids) + "; }")
        lines.append("")

    for node in data.nodes:
        nid = _sanitize_id(node["id"])
        label = _dot_node_label(node)
        if node.get("role") == "start":
            lines.append(f'    {nid} [label="{label}", fillcolor=palegreen];')
        elif node.get("role") == "end":
            lines.append(f'    {nid} [label="{label}", fillcolor=lightsalmon];')
        elif node.get("generated"):
            lines.append(f'    {nid} [label="{label}", fillcolor=wheat];')
        else:
            lines.append(f'    {nid} [label="{label}", fillcolor=lightblue];')

    # Add ephemeral __end__ node for layout clarity
    if exitpoints:
        lines.append("")
        lines.append('    __end__ [label="", shape=doublecircle, fillcolor=black, width=0.3, fixedsize=true];')

    lines.append("")

    for edge in data.edges:
        src = _sanitize_id(edge["from"])
        dst = _sanitize_id(edge["to"])
        attrs = []
        label = edge.get("label") or ""
        # SET overrides abort envelope processing — annotate in label
        if edge.get("override") and edge.get("type") == "set" and label:
            label = f"{label}\n[ABORT]"
        if label:
            attrs.append(f'label="{_escape_dot(label)}"')
        # Override edges use brighter versions of the same green/orange scheme
        if edge.get("override"):
            if label == "else":
                color = "#FF5500"
            else:
                color = "#00B84D"
        elif label == "else":
            color = "#D35400"
        elif edge.get("type") == "error":
            color = "#DC143C"
        elif label.startswith("fanout"):
            color = "#6C35EA"
        elif label:
            color = "#2E8B57"
        else:
            color = None
        if color:
            attrs.append(f'color="{color}"')
            attrs.append(f'fontcolor="{color}"')
        attr_str = f" [{', '.join(attrs)}]" if attrs else ""
        lines.append(f"    {src} -> {dst}{attr_str};")

    # Exitpoint edges to __end__
    for nid in exitpoints:
        lines.append(f"    {nid} -> __end__;")

    # Groups as subgraphs (nested when one group's nodes are a subset of another's)
    _render_dot_groups(data.groups, lines, indent="    ")

    lines.append("}")
    return "\n".join(lines)


def to_mermaid(data: GraphData, flow_name: str) -> str:
    """Render GraphData as a Mermaid flowchart."""
    lines = ["flowchart TD"]
    lines.append(f"    %% Flow: {flow_name}")
    lines.append("")

    # Derive exit nodes from topology
    sources = {e["from"] for e in data.edges}
    targets = {e["to"] for e in data.edges}
    node_ids = {n["id"] for n in data.nodes}
    exitpoints = [_sanitize_id(nid) for nid in sorted(node_ids - sources) if nid in targets]

    start_nodes: list[str] = []
    end_nodes: list[str] = []
    routers: list[str] = []
    handlers: list[str] = []

    for node in data.nodes:
        nid = _sanitize_id(node["id"])
        label = _mermaid_node_label(node)
        if node.get("role") == "start":
            lines.append(f"    {nid}([{label}])")
            start_nodes.append(nid)
        elif node.get("role") == "end":
            lines.append(f"    {nid}[{label}]")
            end_nodes.append(nid)
        elif node.get("generated"):
            lines.append(f"    {nid}{{{{{label}}}}}")
            routers.append(nid)
        else:
            lines.append(f"    {nid}[{label}]")
            handlers.append(nid)

    # Ephemeral __end__ node
    if exitpoints:
        lines.append("    __end__((( )))")

    lines.append("")

    # Edges — track indices for linkStyle coloring
    edge_index = 0
    conditional_indices: list[int] = []
    else_indices: list[int] = []
    fanout_indices: list[int] = []
    override_indices: list[int] = []
    error_indices: list[int] = []

    for edge in data.edges:
        src = _sanitize_id(edge["from"])
        dst = _sanitize_id(edge["to"])
        label = edge.get("label") or ""
        if edge.get("override") and edge.get("type") == "set" and label:
            label = f"{label}\n[ABORT]"
        if label:
            label = str(label).replace('"', "'")
            lines.append(f'    {src} -->|"{label}"| {dst}')
        else:
            lines.append(f"    {src} --> {dst}")
        if edge.get("override"):
            override_indices.append(edge_index)
        elif edge.get("type") == "error":
            error_indices.append(edge_index)
        elif label == "else":
            else_indices.append(edge_index)
        elif label.startswith("fanout"):
            fanout_indices.append(edge_index)
        elif label:
            conditional_indices.append(edge_index)
        edge_index += 1

    # Exitpoint edges to __end__
    for nid in exitpoints:
        lines.append(f"    {nid} --> __end__")
        edge_index += 1

    # Groups as subgraphs (nested when one group's nodes are a subset of another's)
    _render_mermaid_groups(data.groups, lines, indent="    ")

    # Styling — match DOT color scheme
    lines.append("")
    lines.append("    classDef start fill:#98FB98,stroke:#333")
    lines.append("    classDef endnode fill:#FFA07A,stroke:#333")
    lines.append("    classDef router fill:#F5DEB3,stroke:#333")
    lines.append("    classDef handler fill:#ADD8E6,stroke:#333")
    lines.append("    classDef endpoint fill:#000,stroke:#333,color:#fff")
    if start_nodes:
        lines.append(f"    class {','.join(start_nodes)} start")
    if end_nodes:
        lines.append(f"    class {','.join(end_nodes)} endnode")
    if routers:
        lines.append(f"    class {','.join(routers)} router")
    if handlers:
        lines.append(f"    class {','.join(handlers)} handler")
    if exitpoints:
        lines.append("    class __end__ endpoint")
    if conditional_indices:
        lines.append(f"    linkStyle {','.join(str(i) for i in conditional_indices)} stroke:#2E8B57")
    if fanout_indices:
        lines.append(f"    linkStyle {','.join(str(i) for i in fanout_indices)} stroke:#7B68EE")
    if else_indices:
        lines.append(f"    linkStyle {','.join(str(i) for i in else_indices)} stroke:#E07040")
    if error_indices:
        lines.append(f"    linkStyle {','.join(str(i) for i in error_indices)} stroke:#DC143C")
    if override_indices:
        lines.append(f"    linkStyle {','.join(str(i) for i in override_indices)} stroke:#3CB371")

    return "\n".join(lines)


def to_json(data: GraphData, flow_name: str) -> dict:
    """Render GraphData as a JSON-serializable dict."""
    result = {
        "flow_name": flow_name,
        "nodes": data.nodes,
        "edges": data.edges,
        "groups": data.groups,
    }
    if data.warnings:
        result["warnings"] = data.warnings
    return result


def to_json_string(data: GraphData, flow_name: str) -> str:
    """Render GraphData as a formatted JSON string."""
    return json.dumps(to_json(data, flow_name), indent=2) + "\n"


# -- Group nesting --


def _build_group_tree(groups: list[dict]) -> list[tuple[dict, list]]:
    """Build a tree of groups where children have nodes that are a strict subset of their parent.

    Returns a forest (list of root nodes), each node is (group, children).
    Groups are sorted largest-first so parents are processed before children.
    """
    if not groups:
        return []

    sorted_groups = sorted(groups, key=lambda g: len(g.get("nodes", [])), reverse=True)
    node_sets = {id(g): set(g.get("nodes", [])) for g in sorted_groups}

    # tree_nodes[id(group)] = (group, children_list)
    tree_nodes: dict[int, tuple[dict, list]] = {id(g): (g, []) for g in sorted_groups}
    roots: list[tuple[dict, list]] = []
    assigned: set[int] = set()

    for child in sorted_groups:
        child_id = id(child)
        child_nodes = node_sets[child_id]
        placed = False
        for parent in sorted_groups:
            parent_id = id(parent)
            if parent_id == child_id:
                continue
            if child_nodes < node_sets[parent_id]:
                tree_nodes[parent_id][1].append(tree_nodes[child_id])
                assigned.add(child_id)
                placed = True
                break
        if not placed and child_id not in assigned:
            roots.append(tree_nodes[child_id])

    return roots


def _render_dot_groups(groups: list[dict], lines: list[str], indent: str) -> None:
    """Render groups as nested DOT subgraphs."""
    tree = _build_group_tree(groups)
    for node in tree:
        _render_dot_group_node(node, lines, indent)


def _render_dot_group_node(node: tuple[dict, list], lines: list[str], indent: str) -> None:
    group, children = node
    gid = _sanitize_id(group["id"])
    child_nodes = set()
    for child_group, _child_children in children:
        child_nodes.update(child_group.get("nodes", []))

    lines.append(f"{indent}subgraph cluster_{gid} {{")
    lines.append(f'{indent}    label="{group["id"]}";')
    lines.append(f"{indent}    style=dashed;")
    for member in group.get("nodes", []):
        if member not in child_nodes:
            lines.append(f"{indent}    {_sanitize_id(member)};")
    for child in children:
        _render_dot_group_node(child, lines, indent + "    ")
    lines.append(f"{indent}}}")


def _render_mermaid_groups(groups: list[dict], lines: list[str], indent: str) -> None:
    """Render groups as nested Mermaid subgraphs."""
    tree = _build_group_tree(groups)
    for node in tree:
        _render_mermaid_group_node(node, lines, indent)


def _render_mermaid_group_node(node: tuple[dict, list], lines: list[str], indent: str) -> None:
    group, children = node
    gid = _sanitize_id(group["id"])
    child_nodes = set()
    for child_group, _child_children in children:
        child_nodes.update(child_group.get("nodes", []))

    lines.append(f"{indent}subgraph {gid}[{group['id']}]")
    for member in group.get("nodes", []):
        if member not in child_nodes:
            lines.append(f"{indent}    {_sanitize_id(member)}")
    for child in children:
        _render_mermaid_group_node(child, lines, indent + "    ")
    lines.append(f"{indent}end")


# -- Helpers --


def _sanitize_id(name: str) -> str:
    """Make a name safe for DOT/Mermaid node IDs."""
    return (
        name.replace(".", "_").replace("-", "_").replace(" ", "_").replace("(", "_").replace(")", "_").replace(",", "_")
    )


def _display_name(name: str) -> str:
    """Extract a human-readable display name."""
    if name.startswith("start_"):
        return name
    if name.startswith("router_") or name.startswith("fanout_") or name.startswith("fanin_"):
        return name
    # For handler names, show just the last component
    parts = name.split(".")
    if len(parts) > 1:
        return ".".join(parts[-2:])
    return name


def _dot_node_label(node: dict) -> str:
    """Build a DOT node label, including mutations for generated routers."""
    name = _display_name(node["id"])
    mutations = node.get("mutations", [])
    if not mutations:
        return _escape_dot(name)
    body = "\\n".join(_escape_dot(m) for m in mutations)
    return f"{_escape_dot(name)}\\n\\n{body}"


def _mermaid_node_label(node: dict) -> str:
    """Build a Mermaid node label, including mutations for generated routers."""
    name = _display_name(node["id"])
    mutations = node.get("mutations", [])
    if not mutations:
        return name
    # Mermaid uses <br/> for line breaks inside quotes
    body = "<br/>".join(mutations)
    return f'"{name}<br/><br/>{body}"'


def _escape_dot(text: str) -> str:
    """Escape special characters for DOT labels."""
    return text.replace('"', '\\"').replace("\n", "\\n")
