"""asya init: scaffold .asya/ project directory."""

from __future__ import annotations

from pathlib import Path


_ROOT_CONFIG = """\
templates:
  namespace: default
  router_image: "python:3.13-slim"
  max_replicas: 5

compiler:
  routers: "./compiled"
  manifests: ".asya/manifests"

build:
  - module: "*"
    image: "{registry}/*:latest"
"""

_ACTOR_TEMPLATE = """\
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: "{{ actor_name }}"
  namespace: "{{ namespace }}"
  labels:
    asya.sh/flow: "{{ flow_name }}"
    asya.sh/role: "{{ role }}"
spec:
  actor: "{{ actor_name }}"
  image: "{{ image }}"
  handler: "{{ handler }}"
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
    asya.sh/role: "{{ role }}"
spec:
  actor: "{{ actor_name }}"
  image: "{{ router_image }}"
  handler: "{{ handler }}"
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
# Compiler rules: classify Python symbols during flow compilation.
# Most specific match wins (exact > prefix.* > . > *).
#
# Classification (treat-as):
#   actor  - message boundary, separate K8s deployment
#   inline - run code inside router verbatim
#   unfold - expand function body into current flow
#   flow   - sub-flow, compile recursively
#   config - infrastructure metadata, strip and extract
#
# Extraction rules (where: + assign-to:):
#   Navigate decorator AST, map values to XR spec paths.

# --- Default classification rules ---
- match: "."
  treat-as: unfold

- match: "*"
  treat-as: inline

# --- User rules below ---
# - match: "my_lib.helper"
#   treat-as: inline
"""


def init_project(
    target_dir: Path,
    *,
    registry: str,
) -> Path:
    """Scaffold .asya/ project directory.

    Idempotent: re-running preserves existing files, adds missing ones.

    Args:
        target_dir: Directory to create .asya/ in.
        registry: Container image registry (e.g. ghcr.io/my-org).

    Returns:
        Path to the created .asya/ directory.
    """
    asya_dir = target_dir / ".asya"
    asya_dir.mkdir(exist_ok=True)

    # config.yaml
    config_file = asya_dir / "config.yaml"
    if not config_file.exists():
        config_file.write_text(_ROOT_CONFIG.format(registry=registry))

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

    configmap_template = templates_dir / "configmap-routers.yaml"
    if not configmap_template.exists():
        configmap_template.write_text(_CONFIGMAP_TEMPLATE)

    kustomization_template = templates_dir / "kustomization.yaml"
    if not kustomization_template.exists():
        kustomization_template.write_text(_KUSTOMIZATION_TEMPLATE)

    # config.compiler.rules.yaml (filename-to-key convention)
    rules_file = asya_dir / "config.compiler.rules.yaml"
    if not rules_file.exists():
        rules_file.write_text(_RULES_YAML)

    return asya_dir
