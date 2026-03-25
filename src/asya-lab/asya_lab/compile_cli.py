"""Top-level `asya compile` command.

Compiles a flow from a Python source file into code, artifacts, and manifests.
The flow name is explicitly set by the user. On first compile, -f is required.
After that, `asya compile <flow-name>` recompiles from the saved source path.

Flow registry: .asya/flows/<flow-name>.yaml
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

import click
import yaml

from asya_lab.config.project import AsyaProject
from asya_lab.flow import FlowCompileError, FlowCompiler


# -- Flow registry (.asya/flows/<name>.yaml) --------------------------------


def _flow_registry_path(asya_dir: Path, flow_name: str) -> Path:
    return asya_dir / "flows" / f"{flow_name}.yaml"


def _load_flow_registry(asya_dir: Path, flow_name: str) -> dict | None:
    p = _flow_registry_path(asya_dir, flow_name)
    if p.exists():
        return yaml.safe_load(p.read_text()) or {}
    return None


def _save_flow_registry(asya_dir: Path, flow_name: str, source: str, function: str) -> Path:
    p = _flow_registry_path(asya_dir, flow_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump({"source": source, "function": function}, default_flow_style=False))
    return p


# -- Compiler dir resolution ------------------------------------------------


def _resolve_compiler_dirs(project: AsyaProject) -> dict[str, Path]:
    """Resolve compiler directories (code, artifacts, manifests, templates) from project config."""
    dirs = {}
    for key in ("compiler.code", "compiler.artifacts", "compiler.manifests", "compiler.templates"):
        with contextlib.suppress(KeyError):
            dirs[key.split(".")[-1]] = project.resolve_path(key)
    return dirs


def _rel(p: Path) -> str:
    """Path relative to CWD for display."""
    try:
        return str(p.relative_to(Path.cwd()))
    except ValueError:
        return str(p)


# -- Compile -----------------------------------------------------------------


@click.command("compile")
@click.argument("flow_name")
@click.option("-f", "--file", "source_file", default=None, help="Python source file containing the flow")
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
def compile_cmd(
    flow_name: str, source_file: str | None, plot: bool, plot_format: str, verbose: bool, strict: bool
) -> None:
    """Compile a flow into Kubernetes manifests.

    FLOW_NAME is the flow name (e.g. text-improver). On first compile,
    -f is required. After that, the source path is remembered.

    \b
      asya compile text-improver -f src/flow.py   # first compile
      asya compile text-improver                   # recompile (source remembered)
    """
    from asya_lab.config.discovery import find_asya_dir
    from asya_lab.flow import _infer_flow_function

    asya_dir = find_asya_dir(Path.cwd())
    if asya_dir is None:
        click.echo("[-] No .asya/config.yaml found. Run 'asya init' first.", err=True)
        sys.exit(1)

    # Resolve source file: -f flag > saved registry > error
    if source_file is None:
        reg = _load_flow_registry(asya_dir, flow_name)
        if reg and reg.get("source"):
            source_file = reg["source"]
            click.echo(f"[.] Using saved source: {source_file}", err=True)
        else:
            click.echo(
                f"[-] No source file for '{flow_name}'. Usage: asya compile {flow_name} -f path/to/flow.py", err=True
            )
            sys.exit(1)

    source_path = Path(source_file).resolve()
    if not source_path.exists():
        click.echo(f"[-] Source file not found: {source_file}", err=True)
        sys.exit(1)

    # Use flow_name (user-provided) for all path interpolation
    project = AsyaProject.from_dir(source_path.parent, arg_values={"flow_name": flow_name})
    rule_engine = project.load_rules()

    # Infer flow function name from AST
    flow_function = _infer_flow_function(source_path) or source_path.stem

    # Save to registry
    rel_source = str(source_path.relative_to(Path.cwd()))
    reg_path = _save_flow_registry(asya_dir, flow_name, rel_source, flow_function)
    if verbose:
        click.echo(f"[.] Saved flow registry: {_rel(reg_path)}", err=True)

    # Resolve output dirs from config
    dirs = _resolve_compiler_dirs(project)
    code_dir = dirs["code"]
    artifacts_dir = dirs["artifacts"]
    manifests_dir = dirs["manifests"]
    templates_dir = dirs.get("templates")

    try:
        compiler = FlowCompiler(verbose=verbose, rule_engine=rule_engine, project=project)
        result = compiler.compile_file(
            str(source_path),
            str(code_dir),
            overwrite=True,
            artifacts_dir=artifacts_dir,
            manifests_dir=manifests_dir,
            templates_dir=templates_dir,
        )
    except FlowCompileError as e:
        click.echo(f"[-] Compilation failed for {flow_name}\n", err=True)
        click.echo(str(e), err=True)
        sys.exit(1)
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"[-] {e}", err=True)
        sys.exit(1)

    # Print warnings
    for w in result.warnings:
        click.echo(f"[!] {w}", err=True)
    if strict and result.warnings:
        click.echo(f"[-] {len(result.warnings)} warning(s) in --strict mode", err=True)
        sys.exit(1)

    # Print summary
    num_actors = len(result.actors)
    num_routers = sum(1 for a in result.actors if a.generated)
    click.echo(f"[+] Compiled flow '{flow_name}' ({num_actors} actors, {num_routers} routers)")
    click.echo(f"    code:      {_rel(code_dir)}")

    if artifacts_dir != code_dir:
        click.echo(f"    artifacts: {_rel(artifacts_dir)}")

    for name, subpath in [("graph", "graph.json"), ("dot", "flow.dot"), ("mermaid", "flow.mmd")]:
        f = artifacts_dir / subpath
        if f.exists():
            click.echo(f"    {name + ':':<10} {_rel(f)}")

    if plot:
        plot_file = artifacts_dir / f"flow.{plot_format}"
        if plot_file.exists():
            click.echo(f"    plot:      {_rel(plot_file)}")
        else:
            click.echo("[!] Plot requested but graphviz 'dot' not found; skipping render", err=True)

    if result.manifests_dir:
        click.echo(f"    manifests: {_rel(result.manifests_dir)}")
