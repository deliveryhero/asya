"""CLI commands for the flow compiler."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from asya_lab.flow import FlowCompileError, FlowCompiler


@click.command("validate")
@click.argument("flow_file")
@click.option("--verbose", "-v", is_flag=True, help="Show verbose output")
@click.option("--strict", is_flag=True, help="Treat warnings as errors")
def validate(flow_file, verbose, strict):
    """Validate flow by compiling and checking graph invariants."""
    try:
        compiler = FlowCompiler(verbose=verbose)

        source_path = Path(flow_file)
        if not source_path.exists():
            click.echo(f"[-] Source file not found: {flow_file}", err=True)
            sys.exit(1)

        source_code = source_path.read_text()
        compiler.compile(source_code, str(source_path))

        click.echo(f"[+] Flow is valid: {flow_file}")

        warnings = compiler.get_warnings()
        if warnings:
            for w in warnings:
                click.echo(f"[!] {w}", err=True)
            if strict:
                click.echo(f"[-] {len(warnings)} warning(s) in --strict mode", err=True)
                sys.exit(1)

    except FlowCompileError as e:
        click.echo("[-] Validation failed:\n", err=True)
        click.echo(str(e), err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"[-] Unexpected error: {e}", err=True)
        if verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)
