"""Click wrapper for MCP commands (delegates to existing argparse-based module)."""

from __future__ import annotations

import sys

import click


@click.command(
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
    add_help_option=False,
)
@click.pass_context
def mcp(ctx):
    """MCP gateway tools."""
    from asya_lab.mcp.commands import main as mcp_main

    sys.argv = ["asya mcp", *ctx.args]
    mcp_main()
