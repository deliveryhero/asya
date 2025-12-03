#!/usr/bin/env python3
"""
Main CLI entry point for asya-cli.

Dispatches to subcommands: flow, mcp, etc.
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="asya-cli",
        description="Developer tools for Asya framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Subcommand to run")

    # Flow subcommand
    flow_parser = subparsers.add_parser("flow", help="Flow DSL compiler", add_help=False)

    args, remaining = parser.parse_known_args()

    if args.command == "flow":
        # Delegate to flow CLI
        from asya_cli.flow_cli import main as flow_main

        sys.argv = ["asya-cli flow"] + remaining
        flow_main()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
