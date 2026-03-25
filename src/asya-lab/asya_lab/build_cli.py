"""CLI command for building flow images via skaffold.

Finds skaffold.yaml files referenced by compiled actor manifests,
runs skaffold build, and optionally updates kustomize image tags.

    asya build text-flow
    asya build text-flow --push --tag
    asya build text-flow --actor analyze
    asya build text-flow --dir src/team-a/proper-package
"""

from __future__ import annotations

import json
import subprocess  # nosec B404
import sys
from pathlib import Path

import click
import yaml

from asya_lab.cli_types import ASYA_REF, AsyaRef
from asya_lab.config.discovery import BASE_DIR, COMMON_DIR, find_asya_dir
from asya_lab.config.project import AsyaProject


def _find_flow_images(manifests_base: Path) -> dict[str, str]:
    """Extract actor-name -> image-name mapping from compiled manifests."""
    actors: dict[str, str] = {}
    for f in sorted(manifests_base.glob("asya-*.yaml")):
        try:
            doc = yaml.safe_load(f.read_text())
            if not isinstance(doc, dict) or doc.get("kind") != "AsyncActor":
                continue
            name = doc["metadata"]["name"]
            image = doc.get("spec", {}).get("image", "")
            if image and not image.startswith("python:"):
                actors[name] = image
        except (yaml.YAMLError, KeyError):
            continue
    return actors


def _find_skaffold_for_image(project_root: Path, image_name: str) -> Path | None:
    """Find the skaffold.yaml directory that builds a given image."""
    skip = {".git", ".asya", ".venv", "node_modules", "__pycache__", "flows"}
    for skaffold_file in sorted(project_root.rglob("skaffold.yaml")):
        if any(part in skip for part in skaffold_file.relative_to(project_root).parts[:-1]):
            continue
        try:
            data = yaml.safe_load(skaffold_file.read_text())
            for artifact in data.get("build", {}).get("artifacts", []):
                if artifact.get("image") == image_name:
                    return skaffold_file.parent
        except yaml.YAMLError:
            continue
    return None


def _run_skaffold_build(
    skaffold_dir: Path,
    default_repo: str | None,
    push: bool,
) -> list[dict]:
    """Run skaffold build in a directory. Returns list of build results."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        output_path = Path(tmp.name)

    cmd = ["skaffold", "build", f"--file-output={output_path}"]
    if default_repo:
        cmd.extend(["--default-repo", default_repo])
    if not push:
        cmd.append("--push=false")

    result = subprocess.run(cmd, cwd=str(skaffold_dir), check=False)  # nosec B603, B607
    if result.returncode != 0:
        output_path.unlink(missing_ok=True)
        return []

    try:
        data = json.loads(output_path.read_text())
        return data.get("builds", [])
    except (json.JSONDecodeError, FileNotFoundError):
        return []
    finally:
        output_path.unlink(missing_ok=True)


def _update_kustomize_images(common_dir: Path, builds: list[dict]) -> None:
    """Update kustomize images: entries from skaffold build output."""
    kust_path = common_dir / "kustomization.yaml"
    if not kust_path.exists():
        return

    kust = yaml.safe_load(kust_path.read_text()) or {}

    new_images: dict[str, dict] = {}
    for b in builds:
        artifact_name = b["imageName"]
        tag = b["tag"]
        if "@" in tag:
            tag = tag.split("@")[0]
        if ":" in tag:
            new_name, new_tag = tag.rsplit(":", 1)
        else:
            new_name, new_tag = tag, "latest"
        new_images[artifact_name] = {"name": artifact_name, "newName": new_name, "newTag": new_tag}

    existing = {img["name"]: img for img in kust.get("images", [])}
    existing.update(new_images)
    kust["images"] = list(existing.values())

    kust_path.write_text(yaml.dump(kust, default_flow_style=False, sort_keys=False))


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(Path.cwd()))
    except ValueError:
        return str(p)


@click.command("build")
@click.argument("flow_name", type=ASYA_REF)
@click.option("--actor", "-a", "actor_ref", default=None, help="Build only this actor's image")
@click.option(
    "--dir", "build_dir", default=None, type=click.Path(exists=True), help="Build from this skaffold directory"
)
@click.option("--push/--no-push", default=True, help="Push to registry (default: true)")
@click.option("--tag/--no-tag", default=True, help="Auto-update kustomize image tags (default: true)")
@click.option("--default-repo", "default_repo", default=None, help="Registry prefix (skaffold --default-repo)")
def build(
    flow_name: AsyaRef,
    actor_ref: str | None,
    build_dir: str | None,
    push: bool,
    tag: bool,
    default_repo: str | None,
) -> None:
    """Build container images for a compiled flow via skaffold.

    Finds skaffold.yaml files referenced by the flow's actors and runs
    skaffold build. Use --tag to auto-update kustomize image entries.
    Registry is read from .asya/config.yaml `registry:` field.

    \b
    Examples:
      asya build text-flow                    # build locally
      asya build text-flow --push --tag       # build, push, update tags
      asya build text-flow --actor analyze    # one actor only
      asya build text-flow --dir src/team-a/proper-package
    """

    asya_dir = find_asya_dir(Path.cwd())
    if asya_dir is None:
        click.echo("[-] No .asya/ directory found. Run 'asya init' first.", err=True)
        sys.exit(1)

    project = AsyaProject.from_dir(asya_dir.parent, arg_values={"flow_name": flow_name.name})
    project_root = asya_dir.parent

    # Resolve registry: --default-repo > ASYA_REGISTRY > config.registry
    if default_repo is None:
        import os

        default_repo = os.environ.get("ASYA_REGISTRY") or project.cfg.get("registry")
        if default_repo:
            default_repo = str(default_repo)

    # Mode 1: explicit directory
    if build_dir:
        skaffold_path = Path(build_dir)
        if not (skaffold_path / "skaffold.yaml").exists():
            click.echo(f"[-] No skaffold.yaml in {build_dir}", err=True)
            sys.exit(1)
        click.echo(f"[.] Building from {_rel(skaffold_path)}")
        builds = _run_skaffold_build(skaffold_path, default_repo, push)
        if not builds:
            click.echo("[-] Build failed", err=True)
            sys.exit(1)
        for b in builds:
            built_tag = b["tag"].split("@")[0] if "@" in b["tag"] else b["tag"]
            click.echo(f"[+] {b['imageName']} -> {built_tag}")
        if tag:
            manifests_dir = project.resolve_path("compiler.manifests")
            common_dir = manifests_dir / COMMON_DIR
            if common_dir.is_dir():
                _update_kustomize_images(common_dir, builds)
                click.echo(f"[+] Updated image tags in {_rel(common_dir / 'kustomization.yaml')}")
        return

    # Mode 2/3: from compiled manifests
    manifests_dir = project.resolve_path("compiler.manifests")
    base_dir = manifests_dir / BASE_DIR
    if not base_dir.is_dir():
        click.echo("[-] No compiled manifests. Run 'asya compile' first.", err=True)
        sys.exit(1)

    actor_images = _find_flow_images(base_dir)
    if not actor_images:
        click.echo("[.] No buildable images (all actors use base images)")
        return

    # Filter by actor if specified
    if actor_ref:
        k8s_name = actor_ref.replace("_", "-")
        candidates = [k8s_name, f"actor-{k8s_name}", f"start-{k8s_name}"]
        matched = {k: v for k, v in actor_images.items() if k in candidates}
        if not matched:
            click.echo(f"[-] Actor '{actor_ref}' not found. Available: {', '.join(actor_images)}", err=True)
            sys.exit(1)
        actor_images = matched

    # Deduplicate by image name (multiple actors may share one image)
    image_to_dir: dict[str, Path] = {}
    for actor_name, image_name in actor_images.items():
        if image_name in image_to_dir:
            continue
        skaffold_dir_path = _find_skaffold_for_image(project_root, image_name)
        if skaffold_dir_path is None:
            click.echo(f"[!] No skaffold.yaml for image '{image_name}' (actor: {actor_name})", err=True)
            continue
        image_to_dir[image_name] = skaffold_dir_path

    if not image_to_dir:
        click.echo("[-] No skaffold artifacts found", err=True)
        sys.exit(1)

    all_builds: list[dict] = []
    for image_name, skaffold_dir_path in image_to_dir.items():
        click.echo(f"[.] Building {image_name} ({_rel(skaffold_dir_path)})")
        builds = _run_skaffold_build(skaffold_dir_path, default_repo, push)
        if not builds:
            click.echo(f"[-] Build failed for {image_name}", err=True)
            sys.exit(1)
        for b in builds:
            all_builds.append(b)
            built_tag = b["tag"].split("@")[0] if "@" in b["tag"] else b["tag"]
            click.echo(f"[+] {b['imageName']} -> {built_tag}")

    if tag and all_builds:
        common_dir = manifests_dir / COMMON_DIR
        if common_dir.is_dir():
            _update_kustomize_images(common_dir, all_builds)
            click.echo(f"[+] Updated image tags in {_rel(common_dir / 'kustomization.yaml')}")

    click.echo(f"[+] Built {len(all_builds)} image{'s' if len(all_builds) != 1 else ''}")
