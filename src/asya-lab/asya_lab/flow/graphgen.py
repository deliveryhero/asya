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
    start_ids = [_sanitize_id(n["id"]) for n in data.nodes if n["flow_role"] == "start"]
    if start_ids:
        lines.append("    { rank=source; " + "; ".join(start_ids) + "; }")
        lines.append("")

    for node in data.nodes:
        nid = _sanitize_id(node["id"])
        label = _dot_node_label(node)
        if node["flow_role"] == "start":
            lines.append(f'    {nid} [label="{label}", fillcolor=palegreen];')
        elif node.get("is_generated"):
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

    # Groups as subgraphs
    for group in data.groups:
        gid = _sanitize_id(group["id"])
        lines.append(f"    subgraph cluster_{gid} {{")
        lines.append(f'        label="{group["id"]}";')
        lines.append("        style=dashed;")
        for member in group.get("nodes", []):
            lines.append(f"        {_sanitize_id(member)};")
        lines.append("    }")

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
    routers: list[str] = []
    handlers: list[str] = []

    for node in data.nodes:
        nid = _sanitize_id(node["id"])
        label = _mermaid_node_label(node)
        if node["flow_role"] == "start":
            lines.append(f"    {nid}([{label}])")
            start_nodes.append(nid)
        elif node.get("is_generated"):
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

    # Groups as subgraphs
    for group in data.groups:
        gid = _sanitize_id(group["id"])
        lines.append(f"    subgraph {gid}[{group['id']}]")
        for member in group.get("nodes", []):
            lines.append(f"        {_sanitize_id(member)}")
        lines.append("    end")

    # Styling — match DOT color scheme
    lines.append("")
    lines.append("    classDef start fill:#98FB98,stroke:#333")
    lines.append("    classDef router fill:#F5DEB3,stroke:#333")
    lines.append("    classDef handler fill:#ADD8E6,stroke:#333")
    lines.append("    classDef endpoint fill:#000,stroke:#333,color:#fff")
    if start_nodes:
        lines.append(f"    class {','.join(start_nodes)} start")
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


# -- Helpers --


def _sanitize_id(name: str) -> str:
    """Make a name safe for DOT/Mermaid node IDs."""
    return name.replace(".", "_").replace("-", "_").replace(" ", "_")


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
