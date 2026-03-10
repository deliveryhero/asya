"""asya init: scaffold .asya/ project directory."""

from __future__ import annotations

import sys
from pathlib import Path


_ROOT_CONFIG = """\
var:
  project_root: "."
  image_registry: "{image_registry}"
  namespace: default
  transport: sqs
  router_image: "python:3.13-slim"

compiler:
  routers: "${{var.project_root}}/compiled/${{dynamic:flow_function}}"
  manifests: ".asya/manifests/${{dynamic:flow_name}}"
"""

_ACTOR_TEMPLATE = """\
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: "${dynamic:actor_name}"
  namespace: "${var.namespace}"
  labels:
    asya.sh/flow: "${dynamic:flow_name}"
    asya.sh/flow-role: "${dynamic:flow_role}"
spec:
  actor: "${dynamic:actor_name}"
  image: "${dynamic:image}"
  handler: "${dynamic:handler}"
  transport: "${var.transport}"
  env: "${dynamic:env}"
  scaling:
    enabled: true
    minReplicaCount: 0
    maxReplicaCount: "${arg:max_replicas,5}"
"""

_CONFIGMAP_TEMPLATE = """\
apiVersion: v1
kind: ConfigMap
metadata:
  name: "${dynamic:flow_name}-routers"
  namespace: "${var.namespace}"
  labels:
    asya.sh/flow: "${dynamic:flow_name}"
    asya.sh/managed-by: asya-compiler
data:
  routers.py: "${dynamic:router_code}"
"""

_KUSTOMIZATION_TEMPLATE = """\
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources: "${dynamic:resources}"
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

    # compiler/templates/ — directory-to-key convention:
    #   compiler/templates/actor.yaml              → compiler.templates.actor
    #   compiler/templates/configmap_routers.yaml  → compiler.templates.configmap_routers
    #   compiler/templates/kustomization.yaml      → compiler.templates.kustomization
    templates_dir = asya_dir / "compiler" / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)

    actor_template = templates_dir / "actor.yaml"
    if not actor_template.exists():
        actor_template.write_text(_ACTOR_TEMPLATE)

    configmap_template = templates_dir / "configmap_routers.yaml"
    if not configmap_template.exists():
        configmap_template.write_text(_CONFIGMAP_TEMPLATE)

    kustomization_template = templates_dir / "kustomization.yaml"
    if not kustomization_template.exists():
        kustomization_template.write_text(_KUSTOMIZATION_TEMPLATE)

    # compiler/rules.yaml
    rules_file = asya_dir / "compiler" / "rules.yaml"
    if not rules_file.exists():
        rules_file.write_text(_RULES_YAML)

    # manifests/
    manifests_dir = asya_dir / "manifests"
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
