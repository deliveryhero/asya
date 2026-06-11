"""Flow → gateway registration for the split gateway.

A compiled flow is exposed to the gateway as an A2A *agent* and/or an MCP *tool*.
`asya expose` / `asya patch --gateway` write a normalized intent file
(`flow-expose.yaml`) into the flow's manifests; `asya k apply` reads it and upserts
the entry into the gateway's shared, hot-reloaded ConfigMaps:

- A2A agents: ``asya-gateway-a2a-agents`` → ``data["agents.yaml"]`` = ``{agents: [...]}``
- MCP tools:  ``asya-gateway-mcp-tools``  → ``data["tools.yaml"]``  = ``{tools: [...]}``

The a2a/mcp adapters watch their mounted ConfigMap and hot-reload within
``ASYA_CONFIG_POLL_INTERVAL`` (default 10s) once the kubelet propagates the change
(up to ~60s). No deployment patch and no Helm upgrade are required.

The intent file is NOT a Kubernetes resource and is NOT added to kustomization —
it is consumed only by `asya k apply`.
"""

from __future__ import annotations

import json
from pathlib import Path

import click
import yaml


# Gateway ConfigMaps follow the chart fullname convention for release "asya-gateway".
A2A_AGENTS_CM = "asya-gateway-a2a-agents"
MCP_TOOLS_CM = "asya-gateway-mcp-tools"

# Filename of the normalized flow-exposure intent, written by expose / patch --gateway.
EXPOSE_FILENAME = "flow-expose.yaml"

_DEFAULT_MODES = ["text/plain", "application/json"]


def _modes(value: str | None) -> list[str]:
    if value:
        return [m.strip() for m in value.split(",") if m.strip()]
    return list(_DEFAULT_MODES)


def build_flow_expose(
    flow_name: str,
    entrypoint: str,
    description: str,
    timeout: int | None,
    *,
    mcp: bool,
    a2a: bool,
    input_schema: dict | None = None,
    tags: str | None = None,
    examples: tuple[str, ...] = (),
    input_modes: str | None = None,
    output_modes: str | None = None,
    progress: bool = True,
    streaming: bool = True,
) -> dict:
    """Build the normalized flow-exposure intent for the split gateway.

    Produces an ``a2a`` agent entry and/or an ``mcp`` tool entry in the exact shape
    the gateway's ``agents.yaml`` / ``tools.yaml`` expect. ``entrypoint`` (the
    ``start-<flow>`` actor) becomes the entry's ``actor``.
    """
    intent: dict = {"flow": flow_name}

    if a2a:
        agent: dict = {"name": flow_name, "description": description, "actor": entrypoint}
        if timeout is not None:
            agent["timeout"] = timeout
        agent["streaming"] = streaming
        skill: dict = {"id": flow_name, "name": flow_name, "description": description}
        if tags:
            skill["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
        if examples:
            skill["examples"] = list(examples)
        agent["skills"] = [skill]
        agent["inputModes"] = _modes(input_modes)
        agent["outputModes"] = _modes(output_modes)
        intent["a2a"] = agent

    if mcp:
        tool: dict = {"name": flow_name, "description": description, "actor": entrypoint}
        if timeout is not None:
            tool["timeout"] = timeout
        if input_schema is not None:
            tool["inputSchema"] = input_schema
        tool["progress"] = progress
        intent["mcp"] = tool

    return intent


def find_flow_expose(overlay: Path, manifests_dir: Path) -> Path | None:
    """Locate the flow-exposure intent, preferring the resolved overlay over common/."""
    for candidate in (overlay / EXPOSE_FILENAME, manifests_dir / "common" / EXPOSE_FILENAME):
        if candidate.is_file():
            return candidate
    return None


def _upsert(items: list[dict], entry: dict) -> list[dict]:
    """Upsert ``entry`` into ``items`` keyed by ``name`` (idempotent)."""
    out = [it for it in items if it.get("name") != entry.get("name")]
    out.append(entry)
    return out


def _patch_registry_cm(runner, cm_name: str, data_key: str, list_key: str, entry: dict) -> bool:
    """Get the gateway registry ConfigMap, upsert ``entry``, and patch it back.

    Returns True on success, False if the ConfigMap is absent (protocol not enabled).
    """
    got = runner.kubectl("get", "cm", cm_name, "-o", "json", quiet=True, capture_output=True, text=True)
    if got.returncode != 0:
        click.echo(f"[!] Gateway ConfigMap '{cm_name}' not found — is that protocol enabled? Skipping.", err=True)
        return False

    cm = json.loads(got.stdout)
    raw = (cm.get("data") or {}).get(data_key, "") or ""
    parsed = yaml.safe_load(raw) or {}
    items = parsed.get(list_key) or []
    items = _upsert(items, entry)

    new_yaml = yaml.dump({list_key: items}, default_flow_style=False, sort_keys=False)
    patch = json.dumps({"data": {data_key: new_yaml}})
    res = runner.kubectl(
        "patch", "cm", cm_name, "--type", "merge", "-p", patch, quiet=True, capture_output=True, text=True
    )
    if res.returncode != 0:
        click.echo(f"[-] Failed to patch '{cm_name}': {res.stderr.strip()}", err=True)
        return False
    return True


def register_flow_with_gateway(runner, overlay: Path, manifests_dir: Path) -> None:
    """Upsert a flow's a2a/mcp entries into the gateway registry ConfigMaps.

    Reads the flow-exposure intent (if present) and merges its entries into the
    shared, hot-reloaded gateway ConfigMaps. No-op if the flow was not exposed.
    """
    intent_path = find_flow_expose(overlay, manifests_dir)
    if intent_path is None:
        return

    intent = yaml.safe_load(intent_path.read_text()) or {}
    flow_name = intent.get("flow", "?")
    registered = []

    if intent.get("a2a") and _patch_registry_cm(runner, A2A_AGENTS_CM, "agents.yaml", "agents", intent["a2a"]):
        registered.append(f"a2a→{A2A_AGENTS_CM}")
    if intent.get("mcp") and _patch_registry_cm(runner, MCP_TOOLS_CM, "tools.yaml", "tools", intent["mcp"]):
        registered.append(f"mcp→{MCP_TOOLS_CM}")

    if registered:
        click.echo(f"[+] Registered flow '{flow_name}' with gateway ({', '.join(registered)})")
        click.echo("[.] Gateway hot-reloads the registry within ~60s (ConfigMap propagation).")
