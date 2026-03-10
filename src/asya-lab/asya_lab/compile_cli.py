"""Top-level `asya compile` command.

Unified entry point that dispatches to the appropriate compilation strategy
based on the target argument:
  - *.py file   -> compile flow from source (FlowCompiler + ManifestStamper)
  - dotted name -> compile single actor manifest
  - kebab-case  -> recompile from existing manifests in .asya/
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import click

from asya_lab.flow import FlowCompileError, FlowCompiler


def _is_dotted_target(target: str) -> bool:
    """Target contains dots and is not a file path (e.g. module.Class.method)."""
    return "." in target and not target.endswith(".py")


def _is_kebab_case(target: str) -> bool:
    """Target is a kebab-case name (e.g. order-processing)."""
    return bool(re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+)*", target))


def _resolve_compiled_dir(source_path: Path, flow_function: str) -> Path:
    """Resolve compiled output dir from config (compiler.routers), fall back to .asya/compiled."""
    from asya_lab.config.config import ConfigLoader
    from asya_lab.config.discovery import find_asya_dir

    asya_dir = find_asya_dir(source_path.parent)
    if not asya_dir:
        return (source_path.parent / ".asya" / "compiled").resolve()

    try:
        flow_name = flow_function.replace("_", "-")
        loader = ConfigLoader(
            dynamic_values={"flow_function": flow_function, "flow_name": flow_name, "flow": flow_name}
        )
        config = loader.load(source_path.parent)
        routers_path = str(config.compiler.routers)
        return (asya_dir.parent / routers_path).resolve()
    except Exception:
        return (source_path.parent / ".asya" / "compiled").resolve()


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


def _compile_dotted_target(
    target: str,
    actor_name_override: str | None,
    output_dir: str | None,
    verbose: bool,
) -> None:
    """Compile a single actor manifest from a dotted module.Class.method reference."""
    actor_name = actor_name_override or target.rsplit(".", 1)[-1].replace("_", "-")
    resolved_dir = Path(output_dir).resolve() if output_dir else Path.cwd() / ".asya" / "manifests"
    resolved_dir.mkdir(parents=True, exist_ok=True)

    click.echo(f"[+] Compiling single actor '{actor_name}' from {target}")
    click.echo(f"[+] Output directory: {resolved_dir}")

    if verbose:
        click.echo(f"[.] Handler reference: {target}")
        click.echo(f"[.] Actor name: {actor_name}")

    click.echo(f"[!] Single-actor compilation from dotted target is not yet implemented: {target}", err=True)
    sys.exit(1)


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

    manifests_dir = asya_dir / "manifests" / target
    if not manifests_dir.exists():
        click.echo(f"[-] No existing manifests found at: {manifests_dir}", err=True)
        sys.exit(1)

    click.echo(f"[+] Recompiling '{target}' from {manifests_dir}")

    if verbose:
        click.echo(f"[.] Manifests directory: {manifests_dir}")

    click.echo(f"[!] Recompilation from existing manifests is not yet implemented: {target}", err=True)
    sys.exit(1)


@click.command("compile")
@click.argument("target")
@click.option("--flow", "flow_name", default=None, help="Override flow name (kebab-case)")
@click.option("--actor", "actor_name", default=None, help="Override actor name for single-actor compilation")
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
def compile_cmd(target, flow_name, actor_name, output_dir, plot, plot_format, verbose, force):
    """Compile a flow or actor into Kubernetes manifests.

    TARGET can be:

    \b
      file.py              Compile flow from Python source
      module.Class.method  Compile single actor manifest
      my-flow              Recompile from existing .asya/ manifests
    """
    try:
        if target.endswith(".py") and Path(target).exists():
            _compile_flow_file(target, flow_name, output_dir, plot, plot_format, verbose, force)
        elif _is_dotted_target(target):
            _compile_dotted_target(target, actor_name, output_dir, verbose)
        elif _is_kebab_case(target):
            _recompile_kebab_target(target, output_dir, verbose)
        else:
            click.echo(f"[-] Cannot resolve target: {target}", err=True)
            click.echo("[-] Expected a .py file, dotted name, or kebab-case flow name", err=True)
            sys.exit(1)
    except FlowCompileError as e:
        click.echo(f"[-] Compilation failed for {target}\n", err=True)
        click.echo(str(e), err=True)
        sys.exit(1)
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"[-] {e}", err=True)
        sys.exit(1)
