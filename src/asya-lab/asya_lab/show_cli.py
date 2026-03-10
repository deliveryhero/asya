"""CLI command for rendering kustomize manifests of a compiled flow."""

from __future__ import annotations

import subprocess  # nosec B404
import sys
from pathlib import Path

import click

from asya_lab.config.config import ConfigLoader, FlowContext
from asya_lab.config.discovery import BASE_DIR, COMMON_DIR, OVERLAYS_DIR, find_asya_dir


@click.command()
@click.argument("target")
@click.option("--context", "ctx", default=None, help="Overlay context to select (uses common/ or base/ if omitted)")
def show(target: str, ctx: str | None) -> None:
    """Render kustomize manifests for a compiled flow.

    TARGET is the flow name in kebab-case.
    """
    asya_dir = find_asya_dir(Path.cwd())
    if asya_dir is None:
        click.echo("[-] No .asya/ directory found. Run 'asya init' first.", err=True)
        sys.exit(1)

    config = ConfigLoader().load(asya_dir.parent)
    flow_dir = config.with_values(FlowContext.from_flow_name(target)).resolve_path("compiler.manifests")
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

    click.echo(result.stdout, nl=False)
