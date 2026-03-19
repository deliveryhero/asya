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

    for node in data.nodes:
        nid = _sanitize_id(node["id"])
        label = _display_name(node["id"])
        if node["flow_role"] in ("entry", "exit"):
            lines.append(f'    {nid} [label="{label}", fillcolor=palegreen];')
        elif node.get("is_generated"):
            lines.append(f'    {nid} [label="{label}", fillcolor=wheat];')
        else:
            lines.append(f'    {nid} [label="{label}", fillcolor=lightblue];')

    lines.append("")

    for edge in data.edges:
        if edge["to"] == "__terminal__":
            continue
        src = _sanitize_id(edge["from"])
        dst = _sanitize_id(edge["to"])
        attrs = []
        if edge.get("label"):
            attrs.append(f'label="{_escape_dot(edge["label"])}"')
        if edge.get("type") == "abort":
            attrs.append("style=dashed")
        if edge.get("override"):
            attrs.append("color=red")
        attr_str = f" [{', '.join(attrs)}]" if attrs else ""
        lines.append(f"    {src} -> {dst}{attr_str};")

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

    for node in data.nodes:
        nid = _sanitize_id(node["id"])
        label = _display_name(node["id"])
        if node["flow_role"] in ("entry", "exit"):
            lines.append(f"    {nid}([{label}])")
        elif node.get("is_generated"):
            lines.append(f"    {nid}{{{{{label}}}}}")
        else:
            lines.append(f"    {nid}[{label}]")

    lines.append("")

    for edge in data.edges:
        if edge["to"] == "__terminal__":
            continue
        src = _sanitize_id(edge["from"])
        dst = _sanitize_id(edge["to"])
        label = edge.get("label", "")
        if label:
            lines.append(f"    {src} -->|{label}| {dst}")
        else:
            lines.append(f"    {src} --> {dst}")

    # Groups as subgraphs
    for group in data.groups:
        gid = _sanitize_id(group["id"])
        lines.append(f"    subgraph {gid}[{group['id']}]")
        for member in group.get("nodes", []):
            lines.append(f"        {_sanitize_id(member)}")
        lines.append("    end")

    return "\n".join(lines)


def to_json(data: GraphData, flow_name: str) -> dict:
    """Render GraphData as a JSON-serializable dict."""
    return {
        "flow_name": flow_name,
        "nodes": data.nodes,
        "edges": data.edges,
        "groups": data.groups,
    }


def to_json_string(data: GraphData, flow_name: str) -> str:
    """Render GraphData as a formatted JSON string."""
    return json.dumps(to_json(data, flow_name), indent=2)


# -- Helpers --


def _sanitize_id(name: str) -> str:
    """Make a name safe for DOT/Mermaid node IDs."""
    return name.replace(".", "_").replace("-", "_").replace(" ", "_")


def _display_name(name: str) -> str:
    """Extract a human-readable display name."""
    if name.startswith("start_") or name.startswith("end_"):
        return name
    if name.startswith("router_") or name.startswith("fanout_") or name.startswith("fanin_"):
        return name
    # For handler names, show just the last component
    parts = name.split(".")
    if len(parts) > 1:
        return ".".join(parts[-2:])
    return name


def _escape_dot(text: str) -> str:
    """Escape special characters for DOT labels."""
    return text.replace('"', '\\"').replace("\n", "\\n")
