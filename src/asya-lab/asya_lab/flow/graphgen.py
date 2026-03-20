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

    # Collect exitpoint node IDs for the __end__ sink
    exitpoints: list[str] = []

    # Pin start_ to top
    start_ids = [_sanitize_id(n["id"]) for n in data.nodes if n["flow_role"] == "entrypoint"]
    if start_ids:
        lines.append("    { rank=source; " + "; ".join(start_ids) + "; }")
        lines.append("")

    for node in data.nodes:
        nid = _sanitize_id(node["id"])
        label = _dot_node_label(node)
        if node["flow_role"] == "entrypoint":
            lines.append(f'    {nid} [label="{label}", fillcolor=palegreen];')
        elif node.get("is_generated"):
            lines.append(f'    {nid} [label="{label}", fillcolor=wheat];')
        else:
            lines.append(f'    {nid} [label="{label}", fillcolor=lightblue];')
        if node["flow_role"] == "exitpoint":
            exitpoints.append(nid)

    # Add ephemeral __end__ node for layout clarity
    if exitpoints:
        lines.append("")
        lines.append('    __end__ [label="", shape=doublecircle, fillcolor=black, width=0.3, fixedsize=true];')

    lines.append("")

    for edge in data.edges:
        src = _sanitize_id(edge["from"])
        dst = _sanitize_id(edge["to"])
        attrs = []
        if edge.get("label"):
            attrs.append(f'label="{_escape_dot(edge["label"])}"')
        if edge.get("override"):
            attrs.append("color=red")
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

    exitpoints: list[str] = []

    for node in data.nodes:
        nid = _sanitize_id(node["id"])
        label = _mermaid_node_label(node)
        if node["flow_role"] == "entrypoint":
            lines.append(f"    {nid}([{label}])")
        elif node.get("is_generated"):
            lines.append(f"    {nid}{{{{{label}}}}}")
        else:
            lines.append(f"    {nid}[{label}]")
        if node["flow_role"] == "exitpoint":
            exitpoints.append(nid)

    # Ephemeral __end__ node
    if exitpoints:
        lines.append("    __end__((( )))")

    lines.append("")

    for edge in data.edges:
        src = _sanitize_id(edge["from"])
        dst = _sanitize_id(edge["to"])
        label = edge.get("label", "")
        if label:
            lines.append(f"    {src} -->|{label}| {dst}")
        else:
            lines.append(f"    {src} --> {dst}")

    # Exitpoint edges to __end__
    for nid in exitpoints:
        lines.append(f"    {nid} --> __end__")

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
