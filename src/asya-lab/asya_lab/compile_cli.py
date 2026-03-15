"""Top-level `asya compile` command.

Unified entry point that dispatches to the appropriate compilation strategy
based on the target argument:
  - *.py file (or file.py:function) -> compile flow from source
  - kebab-case or snake_case name   -> recompile from existing manifests
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from asya_lab.cli_types import ASYA_REF, AsyaRef
from asya_lab.config.project import AsyaProject
from asya_lab.flow import FlowCompileError, FlowCompiler


def _resolve_compiled_dir(source_path: Path, flow_function: str) -> Path:
    """Resolve compiled output dir from config (compiler.routers)."""
    from asya_lab.config.discovery import find_asya_dir

    asya_dir = find_asya_dir(source_path.parent)
    if not asya_dir:
        click.echo("[-] No .asya/ directory found. Run 'asya init' first.", err=True)
        sys.exit(1)

    project = AsyaProject.from_dir(source_path.parent)
    return project.resolve_path("compiler.routers") / flow_function


def _compile_flow_file(
    target: str,
    flow_name_override: str | None,
    output_dir: str | None,
    plot: bool,
    plot_format: str,
    verbose: bool,
    force: bool,
) -> None:
    """Compile a flow from a .py source file."""
    from asya_lab.flow_cli import _stamp_manifests

    source_path = Path(target).resolve()
    source_code = source_path.read_text()

    # Compile in-memory to learn flow_function before resolving output paths
    compiler = FlowCompiler(verbose=verbose)
    compiled_code = compiler.compile(source_code, str(source_path))
    flow_function = compiler.flow_name

    if flow_name_override:
        flow_name = flow_name_override
    elif flow_function:
        flow_name = flow_function.replace("_", "-")
    else:
        flow_name = source_path.stem.replace("_", "-")

    # Resolve compiled output dir from config or CLI override
    if output_dir:
        compiled_dir = Path(output_dir).resolve()
    else:
        compiled_dir = _resolve_compiled_dir(source_path, flow_function or source_path.stem)

    # Write compiled code to resolved dir
    compiled_dir.mkdir(parents=True, exist_ok=True)
    compiled_file = compiled_dir / "routers.py"
    compiled_file.write_text(compiled_code)

    click.echo(f"[+] Successfully compiled flow to: {compiled_file}")
    click.echo(f"[+] Using flow name '{flow_name}'")

    actor = compiler.single_actor_name
    if actor is not None:
        click.echo("[+] Single-actor flow detected: no router actor needed")
        click.echo(f"[+] Apply these labels to actor '{actor}':")
        click.echo(f"[+]   asya.sh/flow: {flow_name}")
        click.echo("[+]   asya.sh/flow-role: entrypoint")

    if plot:
        try:
            dot_file, plot_path = compiler.generate_plot(str(compiled_dir), plot_format=plot_format)
            click.echo(f"[+] Generated graphviz dot file: {dot_file}")
            if plot_path:
                click.echo(f"[+] Generated graphviz {plot_format} plot: {plot_path}")
        except (ImportError, RuntimeError) as e:
            click.echo(f"[!] Warning: {e}", err=True)
        except Exception as e:
            click.echo(f"[!] Warning: Failed to generate plot: {e}", err=True)

    manifests_dir = output_dir if output_dir else None
    _stamp_manifests(compiler, target, str(compiled_dir), manifests_dir, verbose)


def _recompile_kebab_target(
    target: str,
    output_dir: str | None,
    verbose: bool,
) -> None:
    """Recompile from existing manifests found in .asya/."""
    from asya_lab.config.discovery import find_asya_dir

    asya_dir = find_asya_dir(Path.cwd())
    if asya_dir is None:
        click.echo("[-] No .asya/ directory found; cannot recompile", err=True)
        click.echo("[-] Run 'asya init' to create one", err=True)
        sys.exit(1)

    project = AsyaProject.from_dir(asya_dir.parent)
    manifests_dir = project.resolve_path("compiler.manifests") / target
    if not manifests_dir.exists():
        click.echo(f"[-] No existing manifests found at: {manifests_dir}", err=True)
        sys.exit(1)

    click.echo(f"[+] Recompiling '{target}' from {manifests_dir}")

    if verbose:
        click.echo(f"[.] Manifests directory: {manifests_dir}")

    click.echo(f"[!] Recompilation from existing manifests is not yet implemented: {target}", err=True)
    sys.exit(1)


@click.command("compile")
@click.argument("target", type=ASYA_REF)
@click.option("--flow", "flow_name", default=None, help="Override flow name (kebab-case)")
@click.option("--output-dir", "-o", default=None, help="Override manifest output directory")
@click.option("--plot", is_flag=True, help="Generate flow diagram (DOT + SVG or PNG)")
@click.option(
    "--plot-format",
    "plot_format",
    default="svg",
    type=click.Choice(["svg", "png"]),
    show_default=True,
    help="Output format for flow diagram",
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option("--force", is_flag=True, help="Overwrite without checking git status")
def compile_cmd(target: AsyaRef, flow_name, output_dir, plot, plot_format, verbose, force):
    """Compile a flow or actor into Kubernetes manifests.

    TARGET can be:

    \b
      flow.py              Compile flow from Python source
      flow.py:my_flow      Compile specific flow function from file
      my-flow              Recompile from existing .asya/ manifests
    """
    try:
        if target.source is not None:
            _compile_flow_file(str(target.source), flow_name, output_dir, plot, plot_format, verbose, force)
        else:
            _recompile_kebab_target(target.name, output_dir, verbose)
    except FlowCompileError as e:
        click.echo(f"[-] Compilation failed for {target.name}\n", err=True)
        click.echo(str(e), err=True)
        sys.exit(1)
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"[-] {e}", err=True)
        sys.exit(1)
