"""Click wrapper for asya init command."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from asya_lab.init import init_project, scan_and_generate_skaffold


@click.command()
@click.option("--dir", "target_dir", default=".", help="Target directory (default: current directory)")
@click.option(
    "--scan", is_flag=True, help="Scan for Dockerfiles/pyproject.toml and generate skaffold.yaml per build context"
)
def init(target_dir, scan):
    """Scaffold .asya/ project directory.

    Creates .asya/config.yaml, templates, and compiler rules.
    With --scan, also discovers build contexts (Dockerfiles, pyproject.toml,
    requirements.txt) and generates a skaffold.yaml next to each one.
    """
    target = Path(target_dir).resolve()
    if not target.is_dir():
        click.echo(f"Error: {target} is not a directory", err=True)
        sys.exit(1)

    asya_dir = init_project(target)

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(Path.cwd()))
        except ValueError:
            return str(p)

    click.echo(f"[+] Initialized {_rel(asya_dir)}/")

    if scan:
        results = scan_and_generate_skaffold(target)
        if not results:
            click.echo("[.] No Dockerfiles found")
        for r in results:
            if r.created:
                click.echo(f"[+] {_rel(r.path)} -> {r.image}")
            else:
                click.echo(f"[.] {_rel(r.path)} -> {r.image} (already defined)")
