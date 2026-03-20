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
    verbose: bool,
    strict: bool = False,
    plot: bool = False,
    plot_format: str = "png",
) -> None:
    """Compile a flow from a .py source file."""
    from asya_lab.flow import _infer_flow_function

    source_path = Path(target).resolve()

    # Load project config (if .asya/ exists)
    project = None
    rule_engine = None
    try:
        project = AsyaProject.from_dir(source_path.parent)
        rule_engine = project.load_rules()
    except FileNotFoundError:
        pass

    # Infer flow function name via lightweight AST scan (no full compile)
    flow_function = _infer_flow_function(source_path) or source_path.stem

    if flow_name_override:
        flow_name = flow_name_override
    else:
        flow_name = flow_function.replace("_", "-")

    # Resolve compiled output dir from config or CLI override
    if output_dir:
        compiled_dir = Path(output_dir).resolve()
    else:
        compiled_dir = _resolve_compiled_dir(source_path, flow_function)

    # Single compile call — handles code + manifests + graph outputs
    compiler = FlowCompiler(verbose=verbose, rule_engine=rule_engine, project=project)
    result = compiler.compile_file(str(source_path), str(compiled_dir), overwrite=True)

    # Print warnings before summary
    warnings = result.warnings
    if warnings:
        for w in warnings:
            click.echo(f"[!] {w}", err=True)
        if strict:
            click.echo(f"[-] {len(warnings)} warning(s) in --strict mode", err=True)
            sys.exit(1)

    # Print compilation summary
    num_actors = len(result.actors)
    num_routers = sum(1 for a in result.actors if a.generated)
    click.echo(f"[+] Compiled flow '{flow_name}' ({num_actors} actors, {num_routers} routers)")

    click.echo(f"    routers:   {result.routers_path}")

    graph_file = compiled_dir / "graph.json"
    if graph_file.exists():
        click.echo(f"    graph:     {graph_file}")

    dot_file = compiled_dir / "flow.dot"
    if dot_file.exists():
        click.echo(f"    dot:       {dot_file}")

    mmd_file = compiled_dir / "flow.mmd"
    if mmd_file.exists():
        click.echo(f"    mermaid:   {mmd_file}")

    if plot:
        plot_file = compiled_dir / f"flow.{plot_format}"
        if plot_file.exists():
            click.echo(f"    plot:      {plot_file}")
        else:
            click.echo("[!] Plot requested but graphviz 'dot' not found; skipping render", err=True)

    if verbose:
        actor = compiler.single_actor_name
        if actor is not None:
            click.echo("[+] Single-actor flow: no router actor needed")

        if result.manifests_dir and result.manifests_dir != compiled_dir:
            click.echo(f"[+] Stamped manifests to: {result.manifests_dir}")


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
    default="png",
    type=click.Choice(["svg", "png"]),
    show_default=True,
    help="Output format for flow diagram",
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option("--strict", is_flag=True, help="Treat warnings as errors")
def compile_cmd(target: AsyaRef, flow_name, output_dir, plot, plot_format, verbose, strict):
    """Compile a flow or actor into Kubernetes manifests.

    TARGET can be:

    \b
      flow.py              Compile flow from Python source
      flow.py:my_flow      Compile specific flow function from file
      my-flow              Recompile from existing .asya/ manifests
    """
    try:
        if target.source is not None:
            _compile_flow_file(
                str(target.source),
                flow_name,
                output_dir,
                verbose,
                strict,
                plot=plot,
                plot_format=plot_format,
            )
        else:
            _recompile_kebab_target(target.name, output_dir, verbose)
    except FlowCompileError as e:
        click.echo(f"[-] Compilation failed for {target.name}\n", err=True)
        click.echo(str(e), err=True)
        sys.exit(1)
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"[-] {e}", err=True)
        sys.exit(1)
