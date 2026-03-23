"""Top-level `asya compile` command.

Flow name is always explicit — the user must provide it as the primary
argument. Source file is provided via -f/--file.

    asya compile text-flow -f src/team-a/packages/nlp/text_flow.py
    asya compile greet-flow -f src/team-b/bare-scripts/greet_flow.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from asya_lab.config.project import AsyaProject
from asya_lab.flow import FlowCompileError, FlowCompiler


def _compile_flow_file(
    flow_name: str,
    source_file: str,
    output_dir: str | None,
    verbose: bool,
    strict: bool = False,
    plot: bool = False,
    plot_format: str = "png",
    python_path: tuple[str, ...] = (),
) -> None:
    """Compile a flow from a .py source file."""
    if python_path:
        import sys as _sys

        for p in reversed(python_path):
            resolved = str(Path(p).resolve())
            if resolved not in _sys.path:
                _sys.path.insert(0, resolved)
                if verbose:
                    click.echo(f"    [.] Added to sys.path: {resolved}")

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(Path.cwd()))
        except ValueError:
            return str(p)

    source_path = Path(source_file).resolve()

    if not source_path.exists():
        click.echo(f"[-] Source file not found: {source_path}", err=True)
        sys.exit(1)

    project = None
    rule_engine = None
    try:
        project = AsyaProject.from_dir(source_path.parent, arg_values={"flow_name": flow_name})
        rule_engine = project.load_rules()
    except FileNotFoundError:
        pass

    if project is None and not output_dir:
        click.echo("[-] No .asya/ directory found. Run 'asya init' first.", err=True)
        sys.exit(1)

    if output_dir:
        routers_dir = artifacts_dir = Path(output_dir).resolve()
    else:
        assert project is not None
        routers_dir = project.resolve_path("compiler.code")
        artifacts_dir = project.resolve_path("compiler.artifacts")

    compiler = FlowCompiler(verbose=verbose, rule_engine=rule_engine, project=project)
    result = compiler.compile_file(
        str(source_path),
        str(routers_dir),
        overwrite=True,
        flow_name=flow_name,
        routers_dir=str(routers_dir),
        artifacts_dir=str(artifacts_dir),
    )

    warnings = result.warnings
    if warnings:
        for w in warnings:
            click.echo(f"[!] {w}", err=True)
        if strict:
            click.echo(f"[-] {len(warnings)} warning(s) in --strict mode", err=True)
            sys.exit(1)

    handler_actors = [a for a in result.actors if not a.generated]
    router_actors = [a for a in result.actors if a.generated]
    actor_names = ", ".join(a.name for a in handler_actors) or "none"
    router_names = ", ".join(a.name for a in router_actors) or "none"

    click.echo(f"[+] Compiled flow '{flow_name}'")
    if result.num_actor_calls != len(handler_actors):
        click.echo(f"    actors:    {result.num_actor_calls} calls -> {len(handler_actors)} manifests [{actor_names}]")
    else:
        click.echo(f"    actors:    {len(handler_actors)} [{actor_names}]")
    if result.num_inline_mutations:
        click.echo(f"    inline:    {result.num_inline_mutations} mutations (inlined into routers)")
    click.echo(f"    routers:   {len(router_actors)} [{router_names}]")

    # Output paths
    click.echo(f"    routers:   {_rel(result.routers_path)}")
    if result.artifacts_dir != routers_dir:
        click.echo(f"    artifacts: {_rel(result.artifacts_dir)}/")
    if result.manifests_dir:
        base_dir = result.manifests_dir / "base"
        if base_dir.is_dir():
            manifests = sorted(f.name for f in base_dir.glob("*.yaml"))
            click.echo(f"    manifests: {_rel(result.manifests_dir)}/ ({len(manifests)} files)")
            for m in manifests:
                click.echo(f"                 - {m}")
        else:
            click.echo(f"    manifests: {_rel(result.manifests_dir)}/")

    if plot:
        plot_file = result.artifacts_dir / f"flow.{plot_format}"
        if plot_file.exists():
            click.echo(f"    plot:      {_rel(plot_file)}")
        else:
            click.echo("[!] Plot requested but graphviz 'dot' not found; skipping render", err=True)


@click.command("compile")
@click.argument("flow_name")
@click.option("--file", "-f", "source_file", required=True, help="Path to flow .py source file")
@click.option("--output-dir", "-o", default=None, help="Override compiled output directory")
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
@click.option(
    "--python-path",
    "-I",
    "python_path",
    multiple=True,
    help="Add directory to Python import path for compile-time resolution (repeatable).",
)
def compile_cmd(flow_name, source_file, output_dir, plot, plot_format, verbose, strict, python_path):
    """Compile a flow into Kubernetes manifests.

    FLOW_NAME is a kebab-case identifier used consistently across all commands:

    \b
      asya compile text-flow -f flows/text_flow.py
      asya k apply text-flow
      asya k status text-flow
      asya k logs text-flow

    For bare scripts not on sys.path, use -I to add import directories:

    \b
      asya compile greet-flow -f scripts/greet_flow.py -I scripts/
    """
    # Validate flow name is kebab-case
    if not all(c.isalnum() or c == "-" for c in flow_name) or flow_name.startswith("-"):
        click.echo(f"[-] Flow name must be kebab-case (got '{flow_name}')", err=True)
        sys.exit(1)
    if "_" in flow_name:
        suggested = flow_name.replace("_", "-")
        click.echo(f"[-] Flow name must be kebab-case: use '{suggested}' instead of '{flow_name}'", err=True)
        sys.exit(1)

    try:
        _compile_flow_file(
            flow_name,
            source_file,
            output_dir,
            verbose,
            strict,
            plot=plot,
            plot_format=plot_format,
            python_path=python_path,
        )
    except FlowCompileError as e:
        click.echo(f"[-] Compilation failed for {flow_name}\n", err=True)
        click.echo(str(e), err=True)
        sys.exit(1)
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"[-] {e}", err=True)
        sys.exit(1)
