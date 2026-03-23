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
  templates: ".asya/templates"

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
# extract: maps parameter names to spec paths (direct keyword args).
# where:   navigates nested calls (e.g. stop=stop_after_attempt(3)).

# -- Context managers --

- match: "asyncio.timeout"
  treat-as: config
  extract:
    delay: spec.resiliency.timeout.actor

- match: "contextlib.suppress"
  treat-as: inline
  imports:
  - "import contextlib"

# -- Decorators --

# tenacity.retry — nested extraction via where: trees.
# @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=60))
# @retry(stop=stop_after_attempt(5) | stop_after_delay(30))
- match: "tenacity.retry"
  treat-as: config
  where:
  - param: stop
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
  extract:
    seconds: spec.resiliency.timeout.actor

# stamina.retry — @stamina.retry(attempts=3, timeout=60)
- match: "stamina.retry"
  treat-as: config
  extract:
    attempts: spec.resiliency.policies.default.maxAttempts
    timeout: spec.resiliency.policies.default.maxDuration

# -- Add your project-specific rules below --
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

    # templates/ — templates are NOT part of the config tree,
    # they are stored as files and referenced by the stamper
    templates_dir = asya_dir / "templates"
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
