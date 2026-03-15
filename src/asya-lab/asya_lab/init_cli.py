"""Click wrapper for asya init command."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from asya_lab.init import init_project


def _prompt_image_registry() -> str:
    try:
        value = click.prompt("Image registry", default="ghcr.io/my-org")
        return value.strip() if value else "ghcr.io/my-org"
    except (EOFError, KeyboardInterrupt):
        return "ghcr.io/my-org"


@click.command()
@click.option("--image-registry", default=None, help="Default image registry (e.g. ghcr.io/my-org)")
@click.option("--dir", "target_dir", default=".", help="Target directory (default: current directory)")
def init(image_registry, target_dir):
    """Scaffold .asya/ project directory."""
    target = Path(target_dir).resolve()
    if not target.is_dir():
        click.echo(f"Error: {target} is not a directory", err=True)
        sys.exit(1)

    if image_registry is None:
        image_registry = _prompt_image_registry()

    asya_dir = init_project(target, image_registry=image_registry)
    click.echo(f"[+] Initialized project at {asya_dir}")
