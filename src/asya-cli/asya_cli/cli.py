#!/usr/bin/env python3
"""
Main CLI entry point for asya developer tools.

Usage:
    asya mcp call <tool-name> [args]
    asya mcp list
    asya mcp show <tool-name>
    asya mcp status <envelope-id>
    asya mcp stream <envelope-id>
    asya mcp port-forward [options]
"""

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="asya",
        description="Developer tools for debugging and operating Asya framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    subparsers.add_parser("mcp", help="MCP gateway tools", add_help=False)

    args, remaining = parser.parse_known_args()

    if args.command == "mcp":
        from asya_cli.mcp.commands import main as mcp_main

        sys.argv = ["asya mcp", *remaining]
        mcp_main()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
