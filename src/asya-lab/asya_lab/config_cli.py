"""CLI entry point for 'asya config' commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from omegaconf import OmegaConf


def main_config(args: list[str]) -> None:
    """CLI entry point for 'asya config' subcommand."""
    parser = argparse.ArgumentParser(
        prog="asya config",
        description="Project configuration commands",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    get_parser = subparsers.add_parser("get", help="Get a config value")
    get_parser.add_argument("key", help="Dot-separated config key (e.g. var.image_registry)")
    get_parser.add_argument(
        "--dir",
        default=".",
        help="Start directory for config discovery (default: cwd)",
    )
    get_parser.add_argument(
        "--arg",
        action="append",
        default=[],
        help="Set arg resolver value (key=value), repeatable",
    )
    get_parser.add_argument(
        "-o",
        "--output",
        choices=["yaml", "json"],
        default="yaml",
        help="Output format (default: yaml)",
    )

    parsed = parser.parse_args(args)

    if parsed.subcommand == "get":
        _cmd_get(parsed)


def _cmd_get(parsed: argparse.Namespace) -> None:
    """Handle 'asya config get <key>'."""
    from asya_lab.config.config import load_effective_config

    arg_values = {}
    for item in parsed.arg:
        if "=" not in item:
            print(f"Error: --arg must be key=value, got: {item}", file=sys.stderr)
            sys.exit(1)
        k, v = item.split("=", 1)
        arg_values[k.strip()] = v.strip()

    start_dir = Path(parsed.dir).resolve()
    try:
        cfg = load_effective_config(start_dir, arg_values=arg_values)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        value = OmegaConf.select(cfg, parsed.key)
    except Exception as e:
        print(f"Error resolving '{parsed.key}': {e}", file=sys.stderr)
        sys.exit(1)

    if value is None:
        print(f"Error: key '{parsed.key}' not found", file=sys.stderr)
        sys.exit(1)

    if OmegaConf.is_dict(value) or OmegaConf.is_list(value):
        container = OmegaConf.to_container(value, resolve=True)
        if parsed.output == "json":
            print(json.dumps(container, indent=2))
        else:
            print(OmegaConf.to_yaml(value), end="")
    elif parsed.output == "json":
        print(json.dumps(value))
    else:
        print(value)
