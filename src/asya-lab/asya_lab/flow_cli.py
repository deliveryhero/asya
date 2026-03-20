"""CLI commands for the flow compiler."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from asya_lab.flow import FlowCompileError, FlowCompiler


def _stamp_manifests(
    compiler: FlowCompiler, flow_file: str, output_dir: str, manifests_dir: str | None, verbose: bool
) -> None:
    """Stamp kustomize-structured manifests after flow compilation."""
    try:
        from asya_lab.compiler.templater import ManifestTemplater
    except (ImportError, ModuleNotFoundError):
        click.echo("[!] Manifest stamping unavailable (grouper module removed in Phase 1)", err=True)
        return
    from asya_lab.config.discovery import find_asya_dir
    from asya_lab.config.project import AsyaProject

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
    # The compiler works with flow_function; the templater works with flow_name.
    flow_function = compiler.flow_name
    if not flow_function:
        click.echo("[!] No flow name available; skipping manifest stamping", err=True)
        return

    flow_name = flow_function.replace("_", "-")

    project = AsyaProject.from_dir(source_path.parent)

    # Determine manifest output directory
    if manifests_dir:
        resolved_dir = Path(manifests_dir)
    else:
        resolved_dir = project.resolve_path("compiler.manifests") / flow_name

    # Read the compiled router code
    router_code_path = Path(output_dir) / "routers.py"
    router_code = router_code_path.read_text()

    # Template files (NOT part of config tree — loaded by templater directly)
    templates_dir = template_path.parent
    configmap_template = templates_dir / "configmap_routers.yaml"
    kustomization_template = templates_dir / "kustomization.yaml"
    router_template = templates_dir / "router.yaml"

    templater = ManifestTemplater(
        flow_name=flow_name,
        flow_function=flow_function,
        routers=compiler.routers,  # type: ignore[attr-defined]
        router_code=router_code,
        project=project,
        actor_template_path=template_path,
        router_template_path=router_template if router_template.exists() else None,
        configmap_routers_template_path=configmap_template if configmap_template.exists() else None,
        kustomization_template_path=kustomization_template if kustomization_template.exists() else None,
        import_map=compiler.import_map,
    )

    generated = templater.stamp(resolved_dir)
    click.echo(f"[+] Stamped {len(generated)} manifest files to: {resolved_dir}")
    if verbose:
        for f in generated:
            click.echo(f"[.]   {f}")


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
