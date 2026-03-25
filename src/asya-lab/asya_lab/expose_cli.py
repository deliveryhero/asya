"""CLI commands for exposing and unexposing flows via gateway ConfigMap.

Expose writes the gateway-flows ConfigMap into common/ (user overlay),
and optionally enables it for a specific context via --context.

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


def _get_dumper() -> type:
    from asya_lab.compiler.templater import _Dumper

    return _Dumper


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


def _build_flow_config(
    flow_name: str,
    entrypoint: str,
    description: str,
    timeout: int | None,
    *,
    mcp: bool,
    a2a: bool,
    input_schema: dict | None,
    tags: str | None,
    examples: tuple[str, ...],
    input_modes: str | None,
    output_modes: str | None,
) -> dict:
    """Build the flow configuration data for the ConfigMap."""
    flow_data: dict = {
        "name": flow_name,
        "entrypoint": entrypoint,
        "description": description,
    }
    if timeout is not None:
        flow_data["timeout"] = timeout

    if mcp:
        mcp_section: dict = {}
        if input_schema is not None:
            mcp_section["inputSchema"] = input_schema
        flow_data["mcp"] = mcp_section

    if a2a:
        a2a_section: dict = {}
        if tags:
            a2a_section["tags"] = [t.strip() for t in tags.split(",")]
        if examples:
            a2a_section["examples"] = list(examples)
        if input_modes:
            a2a_section["input_modes"] = [m.strip() for m in input_modes.split(",")]
        if output_modes:
            a2a_section["output_modes"] = [m.strip() for m in output_modes.split(",")]
        flow_data["a2a"] = a2a_section

    return flow_data


def _build_configmap(flow_name: str, flow_data: dict) -> dict:
    """Build a per-flow gateway ConfigMap.

    Each flow gets its own CM with label asya.sh/config-type: flows.
    The gateway reads all *.yaml files in its config directory,
    so multiple per-flow CMs coexist.
    """
    flows_wrapper = {"flows": [flow_data]}
    flow_yaml = yaml.dump(flows_wrapper, Dumper=_get_dumper(), default_flow_style=False, sort_keys=False)
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": f"asya-flow-{flow_name}-config",
            "labels": {
                "asya.sh/flow": flow_name,
                "asya.sh/config-type": "flows",
                "asya.sh/managed-by": "asya-lab",
            },
        },
        "data": {
            f"{flow_name}.yaml": flow_yaml,
        },
    }


EXPOSE_FILENAME = "flow-expose.yaml"


def _update_kustomization(kust_path: Path, resource: str, *, add: bool) -> bool:
    """Add or remove a resource from a kustomization.yaml. Returns True if changed."""
    if not kust_path.exists():
        return False

    kust = yaml.safe_load(kust_path.read_text()) or {}
    resources = kust.get("resources", [])

    if add:
        if resource in resources:
            return False
        resources.append(resource)
    else:
        if resource not in resources:
            return False
        resources.remove(resource)

    kust["resources"] = resources
    kust_path.write_text(yaml.dump(kust, Dumper=_get_dumper(), default_flow_style=False, sort_keys=False))
    return True


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
@click.option("--a2a", "enable_a2a", is_flag=True, default=False, help="Expose as A2A skill")
@click.option("--tags", default=None, help="A2A: comma-separated skill tags")
@click.option("--examples", multiple=True, help="A2A: example prompts (repeatable)")
@click.option("--input-modes", default=None, help="A2A: comma-separated input MIME types")
@click.option("--output-modes", default=None, help="A2A: comma-separated output MIME types")
@click.option("--context", "ctx", default=None, help="Enable for this context (adds to overlay)")
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
    """Expose a compiled flow to the gateway via ConfigMap.

    Creates the flow config in common/ (user overlay). Use --context to
    enable it for a specific environment.

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
    common_dir = manifests_root / COMMON_DIR

    if not base_dir.is_dir():
        click.echo(f"[-] base/ not found: {base_dir}\n[-] Run 'asya compile' first.", err=True)
        sys.exit(1)

    entrypoint = _find_entrypoint(base_dir)
    input_schema = _resolve_input_schema(input_schema_inline, input_schema_file)

    flow_data = _build_flow_config(
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
    configmap = _build_configmap(flow_name, flow_data)

    # Write CM to common/
    common_dir.mkdir(parents=True, exist_ok=True)
    cm_path = common_dir / EXPOSE_FILENAME
    cm_path.write_text(yaml.dump(configmap, Dumper=_get_dumper(), default_flow_style=False, sort_keys=False))
    click.echo(f"[+] {_rel(cm_path)}")

    protocols = []
    if enable_mcp:
        protocols.append("mcp")
    if enable_a2a:
        protocols.append("a2a")

    if ctx:
        # Enable for specific context: copy CM into overlay directory
        overlay_dir = manifests_root / OVERLAYS_DIR / ctx
        if not overlay_dir.is_dir():
            click.echo(f"[-] Overlay not found: {overlay_dir}", err=True)
            click.echo("[-] Run 'asya compile' first or create the overlay", err=True)
            sys.exit(1)

        overlay_cm = overlay_dir / EXPOSE_FILENAME
        overlay_cm.write_text(cm_path.read_text())
        overlay_kust = overlay_dir / "kustomization.yaml"
        if _update_kustomization(overlay_kust, EXPOSE_FILENAME, add=True):
            click.echo(f"[+] Enabled for context '{ctx}': {_rel(overlay_kust)}")
        else:
            click.echo(f"[.] Already enabled for context '{ctx}'")
    else:
        # No context: add to common/ kustomization (all environments)
        common_kust = common_dir / "kustomization.yaml"
        if _update_kustomization(common_kust, EXPOSE_FILENAME, add=True):
            click.echo(f"[+] Enabled in {_rel(common_kust)}")
        else:
            click.echo("[.] Already enabled in common/")

    click.echo(f"[+] Flow '{flow_name}' exposed via {'+'.join(protocols)} (entrypoint: {entrypoint})")


@click.command("unexpose")
@click.argument("target", type=ASYA_REF)
@click.option("--context", "ctx", default=None, help="Disable for this context only")
def unexpose(target: AsyaRef, ctx: str | None):
    """Remove flow exposure from the gateway.

    \b
    Without --context: removes the flow config from common/ entirely.
    With --context: removes only the overlay reference (keeps config in common/).
    """
    flow_name = target.name
    project = _load_project(flow_name)
    manifests_root = _find_manifests_root(project, flow_name)
    common_dir = manifests_root / COMMON_DIR

    if ctx:
        # Remove from specific overlay
        overlay_dir = manifests_root / OVERLAYS_DIR / ctx
        overlay_kust = overlay_dir / "kustomization.yaml"
        if _update_kustomization(overlay_kust, EXPOSE_FILENAME, add=False):
            click.echo(f"[+] Disabled for context '{ctx}'")
        else:
            click.echo(f"[.] Not enabled for context '{ctx}'")
        overlay_cm = overlay_dir / EXPOSE_FILENAME
        if overlay_cm.exists():
            overlay_cm.unlink()
    else:
        # Remove from common/ entirely
        cm_path = common_dir / EXPOSE_FILENAME
        if cm_path.exists():
            cm_path.unlink()
            click.echo(f"[+] Removed {_rel(cm_path)}")
        else:
            click.echo(f"[.] {EXPOSE_FILENAME} not found in common/")

        common_kust = common_dir / "kustomization.yaml"
        _update_kustomization(common_kust, EXPOSE_FILENAME, add=False)
        click.echo(f"[+] Flow '{flow_name}' unexposed")
