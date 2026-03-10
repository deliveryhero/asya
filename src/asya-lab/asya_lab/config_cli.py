"""CLI commands for 'asya config'."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from omegaconf import OmegaConf


@click.group()
def config():
    """Project configuration commands."""


@config.command()
@click.argument("key")
@click.option("--dir", "start_dir", default=".", help="Start directory for config discovery (default: cwd)")
@click.option("--arg", "args", multiple=True, help="Set arg resolver value (key=value), repeatable")
@click.option(
    "-o", "--output", "output_format", type=click.Choice(["yaml", "json"]), default="yaml", help="Output format"
)
def get(key, start_dir, args, output_format):
    """Get a config value by dot-separated key."""
    from asya_lab.config.config import load_effective_config

    arg_values = {}
    for item in args:
        if "=" not in item:
            click.echo(f"Error: --arg must be key=value, got: {item}", err=True)
            sys.exit(1)
        k, v = item.split("=", 1)
        arg_values[k.strip()] = v.strip()

    resolved_dir = Path(start_dir).resolve()
    try:
        cfg = load_effective_config(resolved_dir, arg_values=arg_values)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    try:
        value = OmegaConf.select(cfg, key)
    except Exception as e:
        click.echo(f"Error resolving '{key}': {e}", err=True)
        sys.exit(1)

    if value is None:
        click.echo(f"Error: key '{key}' not found", err=True)
        sys.exit(1)

    if OmegaConf.is_dict(value) or OmegaConf.is_list(value):
        container = OmegaConf.to_container(value, resolve=True)
        if output_format == "json":
            click.echo(json.dumps(container, indent=2))
        else:
            click.echo(OmegaConf.to_yaml(value), nl=False)
    elif output_format == "json":
        click.echo(json.dumps(value))
    else:
        click.echo(value)


def main_config(args: list[str]) -> None:
    """Legacy entry point for argparse-based invocation."""
    config(standalone_mode=True, args=args)
