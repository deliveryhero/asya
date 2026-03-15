"""CLI commands for exposing and unexposing flows via gateway ConfigMap."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import yaml

from asya_lab.cli_types import ASYA_REF, AsyaRef
from asya_lab.compiler.templater import _Dumper
from asya_lab.config.discovery import BASE_DIR, find_asya_dir
from asya_lab.config.project import AsyaProject


def _load_project() -> AsyaProject:
    """Load the AsyaProject, failing fast if .asya/ is missing."""
    asya_dir = find_asya_dir(Path.cwd())
    if asya_dir is None:
        click.echo("[-] No .asya/ directory found. Run 'asya init' first.", err=True)
        sys.exit(1)
    return AsyaProject.from_dir(asya_dir.parent)


def _find_base_dir(project: AsyaProject, flow_name: str) -> Path:
    """Locate the base/ manifest directory for a compiled flow."""
    base_dir = project.resolve_path("compiler.manifests") / flow_name / BASE_DIR
    if not base_dir.is_dir():
        click.echo(
            f"[-] Manifest directory not found: {base_dir}\n[-] Run 'asya flow compile' first.",
            err=True,
        )
        sys.exit(1)

    return base_dir


def _find_entrypoint(base_dir: Path) -> str:
    """Scan base/ YAML files for the actor with label asya.sh/flow-role: entrypoint."""
    for yaml_file in sorted(base_dir.glob("*.yaml")):
        if yaml_file.name in ("kustomization.yaml", "configmap-routers.yaml", "configmap-flows.yaml"):
            continue

        text = yaml_file.read_text()
        for doc in yaml.safe_load_all(text):
            if not isinstance(doc, dict):
                continue
            labels = doc.get("metadata", {}).get("labels", {})
            if labels.get("asya.sh/flow-role") == "entrypoint":
                actor_name = doc["metadata"]["name"]
                return actor_name

    click.echo("[-] No actor with label asya.sh/flow-role=entrypoint found in base/", err=True)
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
    """Build the flow configuration data for the ConfigMap.

    Per ADR configmap-flow-registry: mcp: present = MCP tool,
    a2a: present = A2A skill, both = both.
    """
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


def _build_configmap(flow_name: str, namespace: str, flow_data: dict) -> dict:
    """Build the gateway-flows ConfigMap manifest."""
    flow_yaml = yaml.dump(flow_data, Dumper=_Dumper, default_flow_style=False, sort_keys=False)
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": "gateway-flows",
            "namespace": namespace,
            "labels": {
                "asya.sh/managed-by": "asya-compiler",
            },
        },
        "data": {
            f"{flow_name}.yaml": flow_yaml,
        },
    }


def _resolve_namespace(project: AsyaProject) -> str:
    """Resolve namespace from project config."""
    templates = project.cfg.get("templates")
    if templates is None:
        click.echo("[-] Missing 'templates' section in config", err=True)
        sys.exit(1)
    namespace = templates.get("namespace")
    if namespace is None:
        click.echo("[-] Missing 'templates.namespace' in config", err=True)
        sys.exit(1)
    return str(namespace)


def _update_kustomization_add(base_dir: Path, resource: str) -> None:
    """Add a resource to kustomization.yaml if not already present."""
    kust_path = base_dir / "kustomization.yaml"
    if not kust_path.exists():
        return

    kust = yaml.safe_load(kust_path.read_text()) or {}
    resources = kust.get("resources", [])
    if resource not in resources:
        resources.append(resource)
        resources.sort()
        kust["resources"] = resources
        kust_path.write_text(yaml.dump(kust, Dumper=_Dumper, default_flow_style=False, sort_keys=False))


def _update_kustomization_remove(base_dir: Path, resource: str) -> None:
    """Remove a resource from kustomization.yaml if present."""
    kust_path = base_dir / "kustomization.yaml"
    if not kust_path.exists():
        return

    kust = yaml.safe_load(kust_path.read_text()) or {}
    resources = kust.get("resources", [])
    if resource in resources:
        resources.remove(resource)
        kust["resources"] = resources
        kust_path.write_text(yaml.dump(kust, Dumper=_Dumper, default_flow_style=False, sort_keys=False))


def _resolve_input_schema(schema_inline: str | None, schema_file: str | None) -> dict | None:
    """Parse input schema from inline JSON or file path."""
    if schema_inline and schema_file:
        raise click.BadParameter("Specify only one of --input-schema or --input-schema-file")

    if schema_inline:
        return json.loads(schema_inline)

    if schema_file:
        path = Path(schema_file)
        return json.loads(path.read_text())

    return None


CONFIGMAP_FILENAME = "configmap-flows.yaml"


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
):
    """Expose a compiled flow to the gateway via ConfigMap.

    TARGET is a flow name in kebab-case or a .py file path.

    \b
    MCP tool (default):
      asya expose my-flow -d "Process orders" --input-schema-file schema.json

    \b
    A2A skill:
      asya expose my-flow -d "Research topics" --a2a --tags research,general

    \b
    Both protocols:
      asya expose my-flow -d "Analyze docs" --mcp --a2a --tags analysis
    """
    # Default to MCP if neither flag specified
    if not enable_mcp and not enable_a2a:
        enable_mcp = True

    flow_name = target.name
    project = _load_project()
    base_dir = _find_base_dir(project, flow_name)
    entrypoint = _find_entrypoint(base_dir)
    input_schema = _resolve_input_schema(input_schema_inline, input_schema_file)
    namespace = _resolve_namespace(project)

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
    configmap = _build_configmap(flow_name, namespace, flow_data)

    cm_path = base_dir / CONFIGMAP_FILENAME
    cm_path.write_text(yaml.dump(configmap, Dumper=_Dumper, default_flow_style=False, sort_keys=False))
    click.echo(f"[+] Created {cm_path}")

    _update_kustomization_add(base_dir, CONFIGMAP_FILENAME)
    click.echo(f"[+] Updated kustomization.yaml with {CONFIGMAP_FILENAME}")

    protocols = []
    if enable_mcp:
        protocols.append("mcp")
    if enable_a2a:
        protocols.append("a2a")
    click.echo(f"[+] Flow '{flow_name}' exposed via {'+'.join(protocols)} (entrypoint: {entrypoint})")


@click.command("unexpose")
@click.argument("target", type=ASYA_REF)
def unexpose(target: AsyaRef):
    """Remove flow exposure from the gateway.

    TARGET is a flow name (kebab-case, snake_case, or path/to/flow.py).
    """
    flow_name = target.name
    project = _load_project()
    base_dir = _find_base_dir(project, flow_name)

    cm_path = base_dir / CONFIGMAP_FILENAME
    if cm_path.exists():
        cm_path.unlink()
        click.echo(f"[+] Removed {cm_path}")
    else:
        click.echo(f"[.] {CONFIGMAP_FILENAME} not found in {base_dir}, nothing to remove")

    _update_kustomization_remove(base_dir, CONFIGMAP_FILENAME)
    click.echo("[+] Updated kustomization.yaml")
    click.echo(f"[+] Flow '{flow_name}' unexposed")
