"""asya init: scaffold .asya/ project directory."""

from __future__ import annotations

import sys
from pathlib import Path

from asya_lab.config.discovery import MANIFESTS_DIR


_ROOT_CONFIG = """\
templates:
  namespace: default
  transport: sqs
  router_image: "python:3.13-slim"
  max_replicas: 5

compiler:
  routers: "./compiled"
  manifests: ".asya/manifests"
  image_registry: "{image_registry}"
"""

_ACTOR_TEMPLATE = """\
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: "{{ actor_name }}"
  namespace: "{{ namespace }}"
  labels:
    asya.sh/flow: "{{ flow_name }}"
    asya.sh/flow-role: "{{ flow_role }}"
spec:
  actor: "{{ actor_name }}"
  image: "{{ image }}"
  handler: "{{ handler }}"
  transport: "{{ transport }}"
  scaling:
    enabled: true
    minReplicaCount: 0
    maxReplicaCount: "{{ max_replicas }}"
"""

_ROUTER_TEMPLATE = """\
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: "{{ actor_name }}"
  namespace: "{{ namespace }}"
  labels:
    asya.sh/flow: "{{ flow_name }}"
    asya.sh/flow-role: "{{ flow_role }}"
spec:
  actor: "{{ actor_name }}"
  image: "{{ router_image }}"
  handler: "{{ handler }}"
  transport: "{{ transport }}"
  scaling:
    enabled: true
    minReplicaCount: 0
    maxReplicaCount: 2
"""

_CONFIGMAP_TEMPLATE = """\
apiVersion: v1
kind: ConfigMap
metadata:
  name: "{{ flow_name }}-routers"
  namespace: "{{ namespace }}"
  labels:
    asya.sh/flow: "{{ flow_name }}"
    asya.sh/managed-by: asya-compiler
"""

_KUSTOMIZATION_TEMPLATE = """\
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
"""

_RULES_YAML = """\
# Compiler rules for treat-as resolution.
# Each rule maps a Python construct to compiler behavior.
#
# Example:
# - match: "tenacity.retry(stop=stop_after_attempt(X))"
#   treat-as: config
#   assign-to: spec.resiliency.retry.maxAttempts
#
# - match: "my_lib.helper"
#   treat-as: inline
[]
"""


def init_project(
    target_dir: Path,
    *,
    image_registry: str = "ghcr.io/my-org",
) -> Path:
    """Scaffold .asya/ project directory.

    Idempotent: re-running preserves existing files, adds missing ones.

    Args:
        target_dir: Directory to create .asya/ in.
        image_registry: Default image registry for var.image_registry.

    Returns:
        Path to the created .asya/ directory.
    """
    asya_dir = target_dir / ".asya"
    asya_dir.mkdir(exist_ok=True)

    # config.yaml
    config_file = asya_dir / "config.yaml"
    if not config_file.exists():
        config_file.write_text(_ROOT_CONFIG.format(image_registry=image_registry))

    # compiler/templates/ — templates are NOT part of the config tree,
    # they are stored as files and referenced by the stamper
    templates_dir = asya_dir / "compiler" / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)

    actor_template = templates_dir / "actor.yaml"
    if not actor_template.exists():
        actor_template.write_text(_ACTOR_TEMPLATE)

    router_template = templates_dir / "router.yaml"
    if not router_template.exists():
        router_template.write_text(_ROUTER_TEMPLATE)

    configmap_template = templates_dir / "configmap_routers.yaml"
    if not configmap_template.exists():
        configmap_template.write_text(_CONFIGMAP_TEMPLATE)

    kustomization_template = templates_dir / "kustomization.yaml"
    if not kustomization_template.exists():
        kustomization_template.write_text(_KUSTOMIZATION_TEMPLATE)

    # config.compiler.rules.yaml (filename-to-key convention)
    rules_file = asya_dir / "config.compiler.rules.yaml"
    if not rules_file.exists():
        rules_file.write_text(_RULES_YAML)

    # manifests/
    manifests_dir = asya_dir / MANIFESTS_DIR
    manifests_dir.mkdir(exist_ok=True)

    # .gitignore: add .env.secret
    _update_gitignore(target_dir)

    return asya_dir


def _update_gitignore(target_dir: Path) -> None:
    """Add .env.secret to .gitignore if not already present."""
    gitignore = target_dir / ".gitignore"
    entry = ".env.secret"

    if gitignore.exists():
        content = gitignore.read_text()
        if entry in content.splitlines():
            return
        if not content.endswith("\n"):
            content += "\n"
        content += f"{entry}\n"
        gitignore.write_text(content)
    else:
        gitignore.write_text(f"{entry}\n")


def main_init(args: list[str]) -> None:
    """CLI entry point for 'asya init'."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="asya init",
        description="Scaffold .asya/ project directory",
    )
    parser.add_argument(
        "--image-registry",
        default=None,
        help="Default image registry (e.g. ghcr.io/my-org)",
    )
    parser.add_argument(
        "--dir",
        default=".",
        help="Target directory (default: current directory)",
    )
    parsed = parser.parse_args(args)

    target_dir = Path(parsed.dir).resolve()
    if not target_dir.is_dir():
        print(f"Error: {target_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    image_registry = parsed.image_registry
    if image_registry is None:
        image_registry = _prompt_image_registry()

    asya_dir = init_project(target_dir, image_registry=image_registry)
    print(f"[+] Initialized project at {asya_dir}")


def _prompt_image_registry() -> str:
    """Prompt user for image registry interactively."""
    try:
        value = input("Image registry (e.g. ghcr.io/my-org): ").strip()
        return value if value else "ghcr.io/my-org"
    except (EOFError, KeyboardInterrupt):
        return "ghcr.io/my-org"
