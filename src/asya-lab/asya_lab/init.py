"""asya init: scaffold .asya/ project directory and scan for build artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


_ROOT_CONFIG = """\
templates:
  namespace: default
  router_image: "python:3.13-slim"
  max_replicas: 5

compiler:
  code: "./compiled/${arg:flow_name}/code"
  artifacts: "./compiled/${arg:flow_name}/artifacts"
  manifests: "./compiled/${arg:flow_name}/manifests"
  templates: ".asya/templates"
"""

_ACTOR_TEMPLATE = """\
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: "{{ actor_name }}"
  labels:
    asya.sh/flow: "{{ flow_name }}"

spec:
  actor: "{{ actor_name }}"
  image: "{{ image }}"
  handler: "{{ handler }}"
  scaling:
    enabled: true
    minReplicaCount: 0
    maxReplicaCount: {{ max_replicas }}
  env:
  - name: PYTHONUNBUFFERED
    value: "1"
"""

_ROUTER_TEMPLATE = """\
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: "{{ actor_name }}"
  labels:
    asya.sh/flow: "{{ flow_name }}"

spec:
  actor: "{{ actor_name }}"
  image: "{{ router_image }}"
  handler: "{{ handler }}"
  scaling:
    enabled: true
    minReplicaCount: 0
    maxReplicaCount: 2
  env:
  - name: PYTHONUNBUFFERED
    value: "1"
"""

_CONFIGMAP_TEMPLATE = """\
apiVersion: v1
kind: ConfigMap
metadata:
  name: "{{ flow_name }}-routers"
  labels:
    asya.sh/flow: "{{ flow_name }}"
    asya.sh/managed-by: asya-compiler
"""

_KUSTOMIZATION_TEMPLATE = """\
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
"""

_RULES_YAML = """\
# Compiler rules: map Python constructs to AsyncActor manifest fields.
#
# The parser auto-detects scope from Python syntax:
#   with foo():        -> context manager (applies to all actors in scope)
#   @foo(...)          -> decorator (applies to the decorated function)
#   p = foo(p)         -> call-site
#
# treat-as values:
#   actor  - separate K8s deployment (queue boundary)
#   flow   - sub-flow, compile recursively (creates visual group)
#   unfold - expand function body into current flow
#   inline - paste code into router body
#   config - extract values into manifest, strip at runtime
#
# where: navigates call arguments and nested calls.
# assign-to: terminal — extract value and write to this spec path.

# -- Context managers --

# asyncio.timeout(30) -> spec.resiliency.timeout.actor: 30
- match: "asyncio.timeout"
  treat-as: config
  where:
  - param: delay
    assign-to: spec.resiliency.timeout.actor

# -- Decorators --

# tenacity.retry — nested extraction via where: trees.
# @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=60))
# @retry(stop=stop_after_attempt(5) | stop_after_delay(30))
- match: "tenacity.retry"
  treat-as: config
  where:
  - param: stop
    flatten-on: "|"
    where:
    - match: "stop_after_attempt"
      where:
      - param: max_attempt_number
        assign-to: spec.resiliency.policies.default.maxAttempts
    - match: "stop_after_delay"
      where:
      - param: max_delay
        assign-to: spec.resiliency.policies.default.maxDuration
  - param: wait
    where:
    - match: "wait_exponential"
      where:
      - param: min
        assign-to: spec.resiliency.policies.default.initialDelay
      - param: max
        assign-to: spec.resiliency.policies.default.maxInterval
    - match: "wait_fixed"
      where:
      - param: wait
        assign-to: spec.resiliency.policies.default.initialDelay

# timeout_decorator.timeout — @timeout(30)
- match: "timeout_decorator.timeout"
  treat-as: config
  where:
  - param: seconds
    assign-to: spec.resiliency.timeout.actor

# stamina.retry — @stamina.retry(attempts=3, timeout=60)
- match: "stamina.retry"
  treat-as: config
  where:
  - param: attempts
    assign-to: spec.resiliency.policies.default.maxAttempts
  - param: timeout
    assign-to: spec.resiliency.policies.default.maxDuration

# -- Add your project-specific rules below --
"""


def init_project(
    target_dir: Path,
    *,
    registry: str | None = None,
) -> Path:
    """Scaffold .asya/ project directory.

    Idempotent: re-running preserves existing files, adds missing ones.

    Args:
        target_dir: Directory to create .asya/ in.
        registry: Container image registry. Only used for initial config generation.

    Returns:
        Path to the created .asya/ directory.
    """
    asya_dir = target_dir / ".asya"
    asya_dir.mkdir(exist_ok=True)

    config_file = asya_dir / "config.yaml"
    if not config_file.exists():
        content = _ROOT_CONFIG
        if registry:
            content = content.replace("router_image:", f'registry: "{registry}"\n  router_image:')
        config_file.write_text(content)

    templates_dir = asya_dir / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)

    _write_if_missing(templates_dir / "actor.yaml", _ACTOR_TEMPLATE)
    _write_if_missing(templates_dir / "router.yaml", _ROUTER_TEMPLATE)
    _write_if_missing(templates_dir / "configmap-routers.yaml", _CONFIGMAP_TEMPLATE)
    _write_if_missing(templates_dir / "kustomization.yaml", _KUSTOMIZATION_TEMPLATE)
    _write_if_missing(asya_dir / "config.compiler.rules.yaml", _RULES_YAML)

    return asya_dir


# ---------------------------------------------------------------------------
# Skaffold scan
# ---------------------------------------------------------------------------

_SKIP_DIRS = frozenset(
    {
        ".git",
        ".asya",
        ".venv",
        "node_modules",
        "__pycache__",
        "compiled",
        "build",
        "dist",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
    }
)


@dataclass
class ScaffoldedSkaffold:
    """Result of generating one skaffold.yaml."""

    path: Path
    image: str
    context: str
    created: bool  # False if skaffold.yaml already existed with this artifact


def scan_and_generate_skaffold(
    target_dir: Path,
    *,
    prompt_image_name: bool = True,
) -> list[ScaffoldedSkaffold]:
    """Scan directory tree for Dockerfiles, create skaffold.yaml per build context.

    Each Dockerfile gets its own skaffold.yaml in the same directory.
    Existing skaffold.yaml files are not overwritten.

    Args:
        target_dir: Root directory to scan.
        prompt_image_name: If True, ask the user for the image name
            (with the auto-derived name as the default).

    Returns list of results (created or skipped).
    """
    import click as _click

    results: list[ScaffoldedSkaffold] = []

    for context_dir in _discover_build_contexts(target_dir):
        skaffold_file = context_dir / "skaffold.yaml"
        default_name = _context_to_image_name(context_dir, target_dir)
        if prompt_image_name and not skaffold_file.exists():
            rel = context_dir.relative_to(target_dir) if context_dir != target_dir else Path(".")
            image_name = _click.prompt(
                f"  Image name for {rel}/Dockerfile",
                default=default_name,
            )
        else:
            image_name = default_name
        rel_context = "."

        if skaffold_file.exists():
            # Idempotent: skip if skaffold.yaml already exists in this directory
            existing = yaml.safe_load(skaffold_file.read_text()) or {}
            existing_artifacts = existing.get("build", {}).get("artifacts", [])
            existing_image = existing_artifacts[0].get("image") if existing_artifacts else image_name
            results.append(
                ScaffoldedSkaffold(
                    path=skaffold_file,
                    image=existing_image,
                    context=rel_context,
                    created=False,
                )
            )
            continue

        artifact = {
            "image": image_name,
            "context": rel_context,
            "docker": {"dockerfile": "Dockerfile"},
        }

        # Merge with existing or create new
        if skaffold_file.exists():
            config = yaml.safe_load(skaffold_file.read_text()) or {}
            config.setdefault("build", {}).setdefault("artifacts", []).append(artifact)
        else:
            config = {
                "apiVersion": "skaffold/v4beta13",
                "kind": "Config",
                "metadata": {"name": context_dir.name},
                "build": {"artifacts": [artifact]},
            }

        skaffold_file.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))
        results.append(
            ScaffoldedSkaffold(
                path=skaffold_file,
                image=image_name,
                context=rel_context,
                created=True,
            )
        )

    return results


def _discover_build_contexts(target_dir: Path) -> list[Path]:
    """Walk directory tree, return directories containing a Dockerfile."""
    results: list[Path] = []

    for path in sorted(target_dir.rglob("Dockerfile")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        results.append(path.parent)

    return results


def _context_to_image_name(context: Path, root: Path) -> str:
    """Derive an image name from the build context path."""
    rel = context.relative_to(root)
    if rel == Path("."):
        return root.name
    return str(rel).replace("/", "-").replace("_", "-").lower()


def _write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.write_text(content)
