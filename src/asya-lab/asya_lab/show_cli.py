"""CLI command for rendering kustomize manifests of a compiled flow.

Primary command is `asya render`. `asya show` is kept as an alias.
"""

from __future__ import annotations

import subprocess  # nosec B404
import sys
from pathlib import Path

import click
import yaml

from asya_lab.cli_types import ASYA_REF, AsyaRef
from asya_lab.config.discovery import BASE_DIR, COMMON_DIR, OVERLAYS_DIR, find_asya_dir
from asya_lab.config.project import AsyaProject


@click.command("render")
@click.argument("target", type=ASYA_REF)
@click.option("--context", "ctx", default=None, help="Overlay context to select (uses common/ or base/ if omitted)")
@click.option(
    "--actor", "-a", "actor_ref", default=None, help="Show only this actor (accepts function name or manifest name)"
)
def render(target: AsyaRef, ctx: str | None, actor_ref: str | None) -> None:
    """Render kustomize manifests for a compiled flow.

    TARGET is a flow name (kebab-case, snake_case, or path/to/flow.py).

    \b
    Examples:
      asya show text-flow                    # all resources
      asya show text-flow --actor analyze    # single actor
      asya show text-flow --context dev      # dev overlay
    """
    asya_dir = find_asya_dir(Path.cwd())
    if asya_dir is None:
        click.echo("[-] No .asya/ directory found. Run 'asya init' first.", err=True)
        sys.exit(1)

    project = AsyaProject.from_dir(asya_dir.parent, arg_values={"flow_name": target.name})
    flow_dir = project.resolve_path("compiler.manifests")
    if not flow_dir.is_dir():
        click.echo(f"[-] Flow not found: {flow_dir}", err=True)
        sys.exit(1)

    if ctx:
        kustomize_path = flow_dir / OVERLAYS_DIR / ctx
    elif (flow_dir / COMMON_DIR).is_dir():
        kustomize_path = flow_dir / COMMON_DIR
    else:
        kustomize_path = flow_dir / BASE_DIR

    if not kustomize_path.is_dir():
        click.echo(f"[-] Kustomize path not found: {kustomize_path}", err=True)
        sys.exit(1)

    result = subprocess.run(  # nosec B603, B607
        ["kubectl", "kustomize", str(kustomize_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        click.echo(result.stderr, err=True)
        sys.exit(result.returncode)

    if actor_ref is None:
        click.echo(result.stdout, nl=False)
        return

    # Filter to single actor
    k8s_name = actor_ref.replace("_", "-")
    candidates = [k8s_name, f"actor-{k8s_name}", f"start-{k8s_name}"]

    for doc in yaml.safe_load_all(result.stdout):
        if not isinstance(doc, dict):
            continue
        name = doc.get("metadata", {}).get("name", "")
        if name in candidates:
            click.echo(yaml.dump(doc, default_flow_style=False, sort_keys=False), nl=False)
            return

    click.echo(f"[-] Actor '{actor_ref}' not found. Available:", err=True)
    for doc in yaml.safe_load_all(result.stdout):
        if isinstance(doc, dict) and doc.get("kind") == "AsyncActor":
            click.echo(f"    {doc['metadata']['name']}", err=True)
    sys.exit(1)
