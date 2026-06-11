"""CLI commands for exposing and unexposing flows via the gateway.

`asya expose` writes a normalized flow-exposure intent (`flow-expose.yaml`) into the
flow's manifests. `asya k apply` reads it and upserts the flow as an A2A agent and/or
MCP tool into the gateway's shared, hot-reloaded ConfigMaps
(`asya-gateway-a2a-agents` / `asya-gateway-mcp-tools`).

The intent file is NOT a Kubernetes resource and is NOT added to kustomization.

    asya expose text-flow -d "Analyze text" --mcp --a2a
    asya expose text-flow -d "Analyze text" --mcp --a2a --context dev
    asya unexpose text-flow
    asya unexpose text-flow --context dev
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import yaml

from asya_lab.cli_types import ASYA_REF, AsyaRef
from asya_lab.config.discovery import BASE_DIR, COMMON_DIR, OVERLAYS_DIR, find_asya_dir
from asya_lab.config.project import AsyaProject
from asya_lab.gateway_register import EXPOSE_FILENAME, build_flow_expose


def _load_project(flow_name: str | None = None) -> AsyaProject:
    """Load the AsyaProject, failing fast if .asya/ is missing."""
    asya_dir = find_asya_dir(Path.cwd())
    if asya_dir is None:
        click.echo("[-] No .asya/ directory found. Run 'asya init' first.", err=True)
        sys.exit(1)
    arg_values = {"flow_name": flow_name} if flow_name else None
    return AsyaProject.from_dir(asya_dir.parent, arg_values=arg_values)


def _find_manifests_root(project: AsyaProject, flow_name: str) -> Path:
    """Locate the manifest root directory for a compiled flow."""
    manifests_root = project.resolve_path("compiler.manifests")
    if not manifests_root.is_dir():
        click.echo(
            f"[-] Manifests not found: {manifests_root}\n[-] Run 'asya compile' first.",
            err=True,
        )
        sys.exit(1)
    return manifests_root


def _find_entrypoint(base_dir: Path) -> str:
    """Scan base/ YAML files for the actor with label asya.sh/role: start."""
    for yaml_file in sorted(base_dir.glob("*.yaml")):
        if yaml_file.name in ("kustomization.yaml", "configmap-routers.yaml"):
            continue

        text = yaml_file.read_text()
        for doc in yaml.safe_load_all(text):
            if not isinstance(doc, dict):
                continue
            labels = doc.get("metadata", {}).get("labels", {})
            if labels.get("asya.sh/role") == "start":
                return doc["metadata"]["name"]

    click.echo("[-] No actor with label asya.sh/role=start found in base/", err=True)
    sys.exit(1)


def _resolve_input_schema(schema_inline: str | None, schema_file: str | None) -> dict | None:
    if schema_inline and schema_file:
        raise click.BadParameter("Specify only one of --input-schema or --input-schema-file")
    if schema_inline:
        return json.loads(schema_inline)
    if schema_file:
        return json.loads(Path(schema_file).read_text())
    return None


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(Path.cwd()))
    except ValueError:
        return str(p)


@click.command("expose")
@click.argument("target", type=ASYA_REF)
@click.option("--description", "-d", required=True, help="Flow description")
@click.option("--timeout", "-t", type=int, default=None, help="End-to-end timeout in seconds")
@click.option(
    "--mcp", "enable_mcp", is_flag=True, default=False, help="Expose as MCP tool (default if neither --mcp nor --a2a)"
)
@click.option("--input-schema", "input_schema_inline", default=None, help="MCP: JSON Schema inline")
@click.option("--input-schema-file", "input_schema_file", default=None, help="MCP: JSON Schema from file")
@click.option("--a2a", "enable_a2a", is_flag=True, default=False, help="Expose as A2A agent")
@click.option("--tags", default=None, help="A2A: comma-separated skill tags")
@click.option("--examples", multiple=True, help="A2A: example prompts (repeatable)")
@click.option("--input-modes", default=None, help="A2A: comma-separated input MIME types")
@click.option("--output-modes", default=None, help="A2A: comma-separated output MIME types")
@click.option("--context", "ctx", default=None, help="Write intent into this context's overlay")
def expose(
    target,
    description,
    timeout,
    enable_mcp,
    input_schema_inline,
    input_schema_file,
    enable_a2a,
    tags,
    examples,
    input_modes,
    output_modes,
    ctx,
):
    """Expose a compiled flow to the gateway.

    Writes a flow-exposure intent that `asya k apply` upserts into the gateway's
    A2A/MCP registry ConfigMaps. Use --context to target a specific overlay.

    \b
    Examples:
      asya expose text-flow -d "Analyze text" --mcp --a2a
      asya expose text-flow -d "Analyze text" --mcp --context dev
      asya unexpose text-flow --context dev
    """
    if not enable_mcp and not enable_a2a:
        enable_mcp = True

    flow_name = target.name
    project = _load_project(flow_name)
    manifests_root = _find_manifests_root(project, flow_name)
    base_dir = manifests_root / BASE_DIR

    if not base_dir.is_dir():
        click.echo(f"[-] base/ not found: {base_dir}\n[-] Run 'asya compile' first.", err=True)
        sys.exit(1)

    entrypoint = _find_entrypoint(base_dir)
    input_schema = _resolve_input_schema(input_schema_inline, input_schema_file)

    intent = build_flow_expose(
        flow_name,
        entrypoint,
        description,
        timeout,
        mcp=enable_mcp,
        a2a=enable_a2a,
        input_schema=input_schema,
        tags=tags,
        examples=examples,
        input_modes=input_modes,
        output_modes=output_modes,
    )

    if ctx:
        target_dir = manifests_root / OVERLAYS_DIR / ctx
        if not target_dir.is_dir():
            click.echo(f"[-] Overlay not found: {target_dir}\n[-] Run 'asya compile' first.", err=True)
            sys.exit(1)
    else:
        target_dir = manifests_root / COMMON_DIR
        target_dir.mkdir(parents=True, exist_ok=True)

    intent_path = target_dir / EXPOSE_FILENAME
    intent_path.write_text(yaml.dump(intent, default_flow_style=False, sort_keys=False))
    click.echo(f"[+] {_rel(intent_path)}")

    protocols = [p for p, on in (("mcp", enable_mcp), ("a2a", enable_a2a)) if on]
    click.echo(f"[+] Flow '{flow_name}' exposed via {'+'.join(protocols)} (entrypoint: {entrypoint})")
    suffix = f" --context {ctx}" if ctx else ""
    click.echo(f"[.] Run 'asya k apply {flow_name}{suffix}' to register with the gateway.")


@click.command("unexpose")
@click.argument("target", type=ASYA_REF)
@click.option("--context", "ctx", default=None, help="Remove from this context's overlay only")
def unexpose(target: AsyaRef, ctx: str | None):
    """Remove a flow's gateway-exposure intent.

    \b
    Without --context: removes the intent from common/.
    With --context: removes the intent from the context overlay.

    Note: this removes the local intent only. To drop an already-registered flow
    from the running gateway, edit the asya-gateway-a2a-agents / asya-gateway-mcp-tools
    ConfigMap (the gateway hot-reloads the removal).
    """
    flow_name = target.name
    project = _load_project(flow_name)
    manifests_root = _find_manifests_root(project, flow_name)

    target_dir = (manifests_root / OVERLAYS_DIR / ctx) if ctx else (manifests_root / COMMON_DIR)
    intent_path = target_dir / EXPOSE_FILENAME

    if intent_path.exists():
        intent_path.unlink()
        click.echo(f"[+] Removed {_rel(intent_path)}")
        scope = f"context '{ctx}'" if ctx else "common/"
        click.echo(f"[+] Flow '{flow_name}' unexposed from {scope}")
    else:
        click.echo(f"[.] {EXPOSE_FILENAME} not found in {_rel(target_dir)}")
