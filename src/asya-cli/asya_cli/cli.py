#!/usr/bin/env python3
"""
Main CLI entry point for asya developer tools.

Usage:
    asya mcp call <tool-name> [args]
    asya mcp list
    asya mcp show <tool-name>
    asya mcp status <task-id>
    asya mcp stream <task-id>
    asya mcp port-forward [options]
    asya flow <subcommand> [args]
"""

import argparse
import sys
from importlib.metadata import PackageNotFoundError, version


def get_version() -> str:
    """Get version from package metadata in v1.2.3 format."""
    try:
        pkg_version = version("asya-cli")
        return f"v{pkg_version}"
    except PackageNotFoundError:
        return "v0.0.0-dev"


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="asya",
        description="Developer tools for debugging and operating Asya framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--version",
        action="version",
        version=get_version(),
        help="Show version and exit",
    )

    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    subparsers.add_parser("mcp", help="MCP gateway tools", add_help=False)
    subparsers.add_parser("flow", help="Flow DSL compiler", add_help=False)

    args, remaining = parser.parse_known_args()

    if args.command == "mcp":
        from asya_cli.mcp.commands import main as mcp_main

        sys.argv = ["asya mcp", *remaining]
        mcp_main()
    elif args.command == "flow":
        from asya_cli.flow_cli import main as flow_main

        flow_main(remaining)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
