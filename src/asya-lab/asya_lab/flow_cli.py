"""CLI commands for the flow compiler."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from asya_lab.flow import FlowCompileError, FlowCompiler
from asya_lab.flow.grouper import DEFAULT_MAX_LOOP_ITERATIONS


def _stamp_manifests(
    compiler: FlowCompiler, flow_file: str, output_dir: str, manifests_dir: str | None, verbose: bool
) -> None:
    """Stamp kustomize-structured manifests after flow compilation."""
    from asya_lab.compiler.stamper import ManifestStamper
    from asya_lab.config.config import ConfigLoader
    from asya_lab.config.discovery import find_asya_dir

    source_path = Path(flow_file).resolve()
    asya_dir = find_asya_dir(source_path.parent)
    if asya_dir is None:
        click.echo("[!] No .asya/ directory found; skipping manifest stamping", err=True)
        click.echo("[!] Run 'asya init' to create one", err=True)
        return

    template_path = asya_dir / "compiler" / "templates" / "actor.yaml"
    if not template_path.exists():
        click.echo(f"[!] Actor template not found: {template_path}", err=True)
        click.echo("[!] Run 'asya init' to create one; skipping manifest stamping", err=True)
        return

    # Naming convention (see rfc.md section 7.4):
    #   flow_function: Python function name with underscores (e.g. "my_flow")
    #   flow_name:     K8s/Asya name with hyphens (e.g. "my-flow")
    # The compiler works with flow_function; the stamper works with flow_name.
    flow_function = compiler.flow_name
    if not flow_function:
        click.echo("[!] No flow name available; skipping manifest stamping", err=True)
        return

    flow_name = flow_function.replace("_", "-")

    config_loader = ConfigLoader(
        dynamic_values={"flow_function": flow_function, "flow_name": flow_name, "flow": flow_name}
    )
    config = config_loader.load(source_path.parent)

    # Determine manifest output directory
    if manifests_dir:
        resolved_dir = Path(manifests_dir)
    else:
        try:
            manifests_path = str(config.compiler.manifests)
            resolved_dir = (asya_dir.parent / manifests_path).resolve()
        except Exception:
            click.echo(
                f"[!] Could not resolve manifests path from config, using default: .asya/manifests/{flow_name}",
                err=True,
            )
            resolved_dir = (asya_dir / "manifests" / flow_name).resolve()

    # Read the compiled router code
    router_code_path = Path(output_dir) / "routers.py"
    router_code = router_code_path.read_text()

    # Templates follow directory-to-key convention (see rfc.md section 7.1)
    templates_dir = template_path.parent
    configmap_template = templates_dir / "configmap_routers.yaml"
    kustomization_template = templates_dir / "kustomization.yaml"

    stamper = ManifestStamper(
        flow_name=flow_name,
        flow_function=flow_function,
        routers=compiler.routers,
        router_code=router_code,
        config=config,
        config_loader=config_loader,
        template_path=template_path,
        configmap_routers_template_path=configmap_template if configmap_template.exists() else None,
        kustomization_template_path=kustomization_template if kustomization_template.exists() else None,
    )

    generated = stamper.stamp(resolved_dir)
    click.echo(f"[+] Stamped {len(generated)} manifest files to: {resolved_dir}")
    if verbose:
        for f in generated:
            click.echo(f"[.]   {f}")


@click.group()
def flow():
    """Flow DSL compiler for Asya."""


@flow.command("compile")
@click.argument("flow_file")
@click.option("--output-dir", "-o", required=True, help="Output directory for compiled files")
@click.option(
    "--manifests-dir",
    "-m",
    default=None,
    help="Output directory for kustomize manifests (default: from .asya/config.yaml)",
)
@click.option("--no-manifests", is_flag=True, help="Skip kustomize manifest stamping")
@click.option(
    "--max-iterations",
    type=int,
    default=DEFAULT_MAX_LOOP_ITERATIONS,
    help=f"Max iterations for while-True loops (default: {DEFAULT_MAX_LOOP_ITERATIONS})",
)
@click.option("--verbose", "-v", is_flag=True, help="Show verbose output")
@click.option("--plot", is_flag=True, help="Generate flow diagram (DOT + SVG or PNG)")
@click.option(
    "--plot-format",
    "plot_format",
    default="svg",
    type=click.Choice(["svg", "png"]),
    show_default=True,
    help="Output format for flow diagram",
)
@click.option("--plot-width", type=int, default=50, help="Max width for plot node labels (default: 50)")
@click.option("--overwrite", is_flag=True, help="Overwrite existing files in output directory")
def compile_cmd(
    flow_file,
    output_dir,
    manifests_dir,
    no_manifests,
    max_iterations,
    verbose,
    plot,
    plot_format,
    plot_width,
    overwrite,
):
    """Compile flow to routers and kustomize manifests."""
    try:
        compiler = FlowCompiler(verbose=verbose, max_iterations=max_iterations)

        compiled_file = compiler.compile_file(flow_file, output_dir, overwrite=overwrite)
        click.echo(f"[+] Successfully compiled flow to: {compiled_file}")

        actor = compiler.single_actor_name
        if actor is not None:
            # flow_name from compiler is the Python function name (underscores);
            # asya.sh/flow label uses the K8s name (hyphens)
            flow_label = compiler.flow_name.replace("_", "-") if compiler.flow_name else ""
            click.echo("[+] Single-actor flow detected: no router actor needed")
            click.echo(f"[+] Apply these labels to actor '{actor}':")
            click.echo(f"[+]   asya.sh/flow: {flow_label}")
            click.echo("[+]   asya.sh/flow-role: entrypoint")

        if plot:
            try:
                dot_file, plot_path = compiler.generate_plot(output_dir, plot_width=plot_width, plot_format=plot_format)
                click.echo(f"[+] Generated graphviz dot file: {dot_file}")
                if plot_path:
                    click.echo(f"[+] Generated graphviz {plot_format} plot: {plot_path}")
            except ImportError as e:
                click.echo(f"[!] Warning: {e}", err=True)
            except RuntimeError as e:
                click.echo(f"[!] Warning: {e}", err=True)
            except Exception as e:
                click.echo(f"[!] Warning: Failed to generate plot: {e}", err=True)

        if not no_manifests:
            try:
                _stamp_manifests(compiler, flow_file, output_dir, manifests_dir, verbose)
            except Exception as e:
                click.echo(f"[!] Warning: Manifest stamping failed: {e}", err=True)
                if verbose:
                    import traceback

                    traceback.print_exc()

        warnings = compiler.get_warnings()
        if warnings:
            click.echo("\nWarnings:", err=True)
            for warning in warnings:
                click.echo(f"\n{warning}", err=True)

    except FlowCompileError as e:
        click.echo(f"[-] Compilation failed for {flow_file}\n", err=True)
        click.echo(str(e), err=True)
        sys.exit(1)
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"[-] {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"[-] Unexpected error: {e}", err=True)
        if verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


@flow.command()
@click.argument("flow_file")
@click.option("--verbose", "-v", is_flag=True, help="Show verbose output")
def validate(flow_file, verbose):
    """Validate flow without compiling."""
    try:
        compiler = FlowCompiler(verbose=verbose)

        source_path = Path(flow_file)
        if not source_path.exists():
            click.echo(f"[-] Source file not found: {flow_file}", err=True)
            sys.exit(1)

        source_code = source_path.read_text()
        compiler.validate(source_code, str(source_path))

        click.echo(f"[+] Flow is valid: {flow_file}")

        warnings = compiler.get_warnings()
        if warnings:
            click.echo("\nWarnings:", err=True)
            for warning in warnings:
                click.echo(f"\n{warning}", err=True)

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


def main(argv=None):
    """Legacy entry point for argparse-based invocation."""
    flow(standalone_mode=True, args=argv)
