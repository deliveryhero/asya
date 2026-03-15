"""asya init: scaffold .asya/ project directory."""

from __future__ import annotations

import subprocess  # nosec B404
from pathlib import Path


_KNOWN_TRANSPORTS = ("sqs", "rabbitmq", "pubsub")

_ROOT_CONFIG = """\
templates:
  namespace: default
  transport: {transport}
  router_image: "python:3.13-slim"
  max_replicas: 5

compiler:
  routers: "./compiled"
  manifests: ".asya/manifests"
  image_registry: "{image_registry}"

build:
  - module: "*"
    image: "{image_registry}/*:latest"
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
    transport: str = "sqs",
) -> Path:
    """Scaffold .asya/ project directory.

    Idempotent: re-running preserves existing files, adds missing ones.

    Args:
        target_dir: Directory to create .asya/ in.
        image_registry: Default image registry for var.image_registry.
        transport: Default message transport (sqs, rabbitmq, pubsub).

    Returns:
        Path to the created .asya/ directory.
    """
    asya_dir = target_dir / ".asya"
    asya_dir.mkdir(exist_ok=True)

    # config.yaml
    config_file = asya_dir / "config.yaml"
    if not config_file.exists():
        config_file.write_text(_ROOT_CONFIG.format(image_registry=image_registry, transport=transport))

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

    return asya_dir


def detect_transport() -> str | None:
    """Detect transport from Crossplane Compositions in the current cluster.

    Queries for Compositions labeled with asya.sh/transport.
    Returns the transport name if exactly one is found, or None
    if kubectl is unavailable, no compositions exist, or multiple
    transports are deployed.
    """
    try:
        result = subprocess.run(  # nosec B603, B607
            [
                "kubectl",
                "get",
                "compositions",
                "-l",
                "crossplane.io/xrd=xasyncactors.asya.sh",
                "-o",
                "jsonpath={.items[*].metadata.labels.asya\\.sh/transport}",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    transports = set(result.stdout.strip().split())
    transports.discard("")
    if len(transports) == 1:
        return transports.pop()
    return None
