"""Top-level `asya build` command.

Thin command runner for image building. Reads build entries from
.asya/config.yaml, resolves variables, and executes opaque shell commands.
No cluster needed -- builds run locally via Docker/Podman/etc.
"""

from __future__ import annotations

import re
import subprocess  # nosec B404
import sys
from pathlib import Path

import click
import yaml
from omegaconf import OmegaConf

from asya_lab.cli_types import ASYA_REF, AsyaRef
from asya_lab.config.discovery import BASE_DIR, find_asya_dir
from asya_lab.config.project import AsyaProject


def _load_build_entries(
    start_dir: Path,
    arg_values: dict[str, str],
) -> tuple[list[dict], AsyaProject]:
    """Load build entries from config, returning (build_list, project)."""
    project = AsyaProject.from_dir(start_dir, arg_values=arg_values)

    build_list = project.cfg.get("build")
    if not build_list:
        click.echo("[-] No build entries in config", err=True)
        click.echo("[-] Add a 'build:' section to .asya/config.yaml", err=True)
        sys.exit(1)

    resolved = [OmegaConf.to_container(entry, resolve=True) for entry in build_list]
    return resolved, project


def _find_flow_images(target: str, project: AsyaProject) -> set[str]:
    """Find unique image references from compiled manifests for a flow."""
    try:
        manifests_dir = project.resolve_path("compiler.manifests") / target / BASE_DIR
    except (KeyError, AttributeError):
        return set()
    if not manifests_dir.is_dir():
        return set()

    images: set[str] = set()
    for yaml_file in sorted(manifests_dir.glob("*.yaml")):
        if yaml_file.name in ("kustomization.yaml", "configmap-routers.yaml", "configmap-flows.yaml"):
            continue

        for doc in yaml.safe_load_all(yaml_file.read_text()):
            if not isinstance(doc, dict):
                continue
            image = _extract_image(doc)
            if image:
                images.add(image)

    return images


def _extract_image(doc: dict) -> str | None:
    """Extract container image from an AsyncActor manifest."""
    spec = doc.get("spec", {})
    # Direct image field
    image = spec.get("image")
    if image:
        return image
    # Nested under workload
    workload = spec.get("workload", {})
    image = workload.get("image")
    if image:
        return image
    return None


def _resolve_entries_for_target(
    target: AsyaRef,
    build_entries: list[dict],
    project: AsyaProject | None,
) -> list[dict]:
    """Resolve which build entries to execute for the given target.

    Resolution order:
    1. If target matches a build entry module name (kebab or snake) -> use that entry
    2. If target matches a flow name in manifests -> find all unique images,
       match each to a build entry
    3. Error if no matches
    """
    resolved = build_entries

    # Try matching by module name (both kebab and snake forms)
    for entry in resolved:
        module = entry.get("module", "")
        if module in (target.name, target.function):
            return [entry]

    # Try matching by flow name (from compiled manifests)
    if project:
        flow_images = _find_flow_images(target.name, project)
        if flow_images:
            matched = []
            for entry in resolved:
                entry_image = entry.get("image", "")
                if entry_image in flow_images:
                    matched.append(entry)
            if matched:
                return matched

    # Try matching by image name substring
    for entry in resolved:
        entry_image = entry.get("image", "")
        if target.name in entry_image:
            return [entry]

    click.echo(f"[-] No build entry found for target '{target.name}'", err=True)
    click.echo("[-] Available build entries:", err=True)
    for entry in resolved:
        click.echo(f"[-]   module: {entry.get('module', '?')}", err=True)
    sys.exit(1)


_ALLOWED_BUILD_CMD = re.compile(r"^(docker|podman|nerdctl|buildah|bazel|make|nix-build|ko|pack|earthly|kaniko)\b")

_PUSHABLE_TOOLS = {"docker", "podman", "nerdctl", "buildah"}


def _infer_build_tool(command: str) -> str:
    """Infer the container tool from a build command for push."""
    first_word = command.lstrip().split()[0] if command.strip() else ""
    if first_word in _PUSHABLE_TOOLS:
        return first_word
    if first_word:
        click.echo(
            f"[!] Build tool '{first_word}' has no native push; falling back to 'docker push'",
            err=True,
        )
    return "docker"


def _validate_build_command(command: str) -> None:
    """Validate that a build command starts with a known build tool.

    Build commands come from .asya/config.yaml which is a trusted local file
    written by the same developer who runs the CLI. This validation is a
    defense-in-depth check, not a security boundary.
    """
    stripped = command.lstrip()
    if not _ALLOWED_BUILD_CMD.match(stripped):
        click.echo(f"[-] Rejected build command: {command}", err=True)
        click.echo(
            "[-] Command must start with a known build tool "
            "(docker, podman, nerdctl, buildah, bazel, make, nix-build, ko, pack, earthly, kaniko)",
            err=True,
        )
        sys.exit(1)


def _run_build(entry: dict, push: bool, verbose: bool, index: int = 0, total: int = 1) -> None:
    """Execute a single build entry's command."""
    command = entry.get("command")
    if not command:
        click.echo(f"[!] Skipping {entry.get('module', '?')}: no command defined", err=True)
        return

    image = entry.get("image", "")
    build_path = entry.get("path", ".")
    prefix = f"[build {index + 1}/{total}] " if total > 1 else "[build] "

    if verbose:
        click.echo(f"{prefix}Module: {entry.get('module', '?')}", err=True)
        click.echo(f"{prefix}Image: {image}", err=True)
        click.echo(f"{prefix}Dir: {build_path}", err=True)
        click.echo(f"{prefix}Command: {command}", err=True)

    _validate_build_command(command)

    click.echo(f"{prefix}+ {command}", err=True)

    # shell=True is intentional: build commands are opaque shell strings
    # from .asya/config.yaml (may contain pipes, redirects, env expansion).
    # This is a local developer CLI — the user who writes config.yaml is
    # the same user who runs the command. See RFC §7.7 "Build commands
    # are opaque" and research-compiler-resolution.md §3.5.
    result = subprocess.run(  # nosec B602
        command,
        shell=True,
        cwd=build_path,
        check=False,
    )

    if result.returncode != 0:
        click.echo(f"\n[-] Build failed (exit code {result.returncode})", err=True)
        sys.exit(result.returncode)

    if push and image:
        push_prefix = f"[push  {index + 1}/{total}] " if total > 1 else "[push] "
        push_tool = _infer_build_tool(command)
        push_cmd = [push_tool, "push", image]
        click.echo(f"{push_prefix}+ {' '.join(push_cmd)}", err=True)

        result = subprocess.run(  # nosec B603
            push_cmd,
            cwd=build_path,
            check=False,
        )

        if result.returncode != 0:
            click.echo(f"\n[-] Push failed (exit code {result.returncode})", err=True)
            sys.exit(result.returncode)


def _parse_arg_values(args: tuple[str, ...]) -> dict[str, str]:
    """Parse --arg key=value pairs into a dict."""
    values: dict[str, str] = {}
    for arg in args:
        if "=" not in arg:
            click.echo(f"[-] Invalid --arg format: '{arg}' (expected key=value)", err=True)
            sys.exit(1)
        key, _, value = arg.partition("=")
        values[key] = value
    return values


@click.command("build")
@click.argument("target", type=ASYA_REF)
@click.option("--arg", "args", multiple=True, help="Build argument (key=value, repeatable)")
@click.option("--push", is_flag=True, help="Push image to registry after build")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def build(target: AsyaRef, args: tuple[str, ...], push: bool, verbose: bool) -> None:
    """Build images for a flow or actor.

    TARGET is a module name from build config or a compiled flow name.

    \b
    Examples:
      asya build order-processing --arg tag=v1.2
      asya build order-processing --arg tag=v1.2 --push
      asya build e_commerce --arg tag=latest
    """
    arg_values = _parse_arg_values(args)
    asya_dir = find_asya_dir(Path.cwd())

    if asya_dir is None:
        click.echo("[-] No .asya/ directory found. Run 'asya init' first.", err=True)
        sys.exit(1)

    build_entries, project = _load_build_entries(asya_dir.parent, arg_values)
    entries = _resolve_entries_for_target(target, build_entries, project)

    # Deduplicate by image (skip entries without an image)
    seen_images: set[str] = set()
    unique_entries: list[dict] = []
    for entry in entries:
        image = entry.get("image", "")
        if not image or image not in seen_images:
            if image:
                seen_images.add(image)
            unique_entries.append(entry)

    total = len(unique_entries)
    for i, entry in enumerate(unique_entries):
        _run_build(entry, push, verbose, index=i, total=total)

    click.echo(f"[+] Built {total} image{'s' if total != 1 else ''}")
