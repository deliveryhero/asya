"""Click wrapper for asya init command."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from asya_lab.init import _KNOWN_TRANSPORTS, init_project


def _prompt_registry() -> str:
    try:
        return click.prompt("Container image registry (e.g. ghcr.io/my-org)")
    except (EOFError, KeyboardInterrupt):
        click.echo("\n[-] Registry is required", err=True)
        sys.exit(1)


def _prompt_transport() -> str:
    choices = list(_KNOWN_TRANSPORTS)
    try:
        return click.prompt(
            "Transport",
            type=click.Choice(choices, case_sensitive=False),
        )
    except (EOFError, KeyboardInterrupt):
        click.echo("\n[-] Transport is required", err=True)
        sys.exit(1)


@click.command()
@click.option("--registry", default=None, help="Container image registry (e.g. ghcr.io/my-org)")
@click.option(
    "--transport",
    default=None,
    type=click.Choice(list(_KNOWN_TRANSPORTS), case_sensitive=False),
    help="Message transport (sqs, rabbitmq, pubsub)",
)
@click.option("--dir", "target_dir", default=".", help="Target directory (default: current directory)")
def init(registry, transport, target_dir):
    """Scaffold .asya/ project directory."""
    target = Path(target_dir).resolve()
    if not target.is_dir():
        click.echo(f"Error: {target} is not a directory", err=True)
        sys.exit(1)

    if registry is None:
        registry = _prompt_registry()

    if transport is None:
        transport = _prompt_transport()

    asya_dir = init_project(target, registry=registry, transport=transport)
    click.echo(f"[+] Initialized project at {asya_dir}")
