"""Docker Compose YAML generator from compiled AsyncActor manifests.

Reads multi-document AsyncActor YAML and produces a docker-compose.yaml
that mirrors the K8s architecture: sidecar + runtime per actor, connected
via Unix socket transport over shared Docker volumes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SIDECAR_IMAGE = "ghcr.io/deliveryhero/asya-sidecar:latest"
MESH_VOLUME = "asya-mesh"
MESH_DIR = "/var/run/asya/mesh"
RUNTIME_SOCKET_DIR = "/var/run/asya"


# ---------------------------------------------------------------------------
# Manifest parsing
# ---------------------------------------------------------------------------


def load_actors(manifests_dir: Path) -> list[dict]:
    """Load AsyncActor documents from all YAML files in a manifests directory.

    Skips kustomization.yaml and non-AsyncActor documents.
    """
    actors: list[dict] = []
    for yaml_file in sorted(manifests_dir.glob("*.yaml")):
        if yaml_file.name == "kustomization.yaml":
            continue
        try:
            for doc in yaml.safe_load_all(yaml_file.read_text()):
                if not isinstance(doc, dict):
                    continue
                if doc.get("kind") != "AsyncActor":
                    continue
                actors.append(doc)
        except yaml.YAMLError as e:
            print(f"[!] Skipping {yaml_file}: {e}", file=sys.stderr)
    return actors


def _extract_actor_info(doc: dict) -> dict:
    """Extract actor name, image, handler, and env vars from an AsyncActor doc.

    Reads from the flat XRD structure: spec.image, spec.handler, spec.env.
    """
    metadata = doc.get("metadata", {})
    spec = doc.get("spec", {})
    name = metadata.get("name", "unknown")

    image = spec.get("image", "")
    handler = spec.get("handler", "")

    env_vars: list[dict] = []
    for env in spec.get("env", []):
        env_name = env.get("name", "")
        if env_name == "ASYA_STATE_PROXY_MOUNTS":
            continue
        if "valueFrom" not in env:
            env_vars.append(env)

    return {
        "name": name,
        "actor": spec.get("actor", name),
        "image": image,
        "handler": handler,
        "env": env_vars,
    }


# ---------------------------------------------------------------------------
# Compose generation
# ---------------------------------------------------------------------------


def _sidecar_service(actor: dict, runtime_socket_volume: str) -> dict:
    """Generate a sidecar service definition for an actor."""
    name = actor["name"]
    return {
        "image": SIDECAR_IMAGE,
        "environment": {
            "ASYA_TRANSPORT": "socket",
            "ASYA_ACTOR_NAME": name,
            "ASYA_NAMESPACE": "local",
            "ASYA_SOCKET_DIR": MESH_DIR,
            "ASYA_ACTOR_SINK": "x-sink",
            "ASYA_ACTOR_SUMP": "x-sump",
            "ASYA_LOG_LEVEL": "INFO",
            "ASYA_METRICS_ENABLED": "false",
        },
        "volumes": [
            f"{MESH_VOLUME}:{MESH_DIR}",
            f"{runtime_socket_volume}:{RUNTIME_SOCKET_DIR}",
        ],
    }


def _runtime_service(actor: dict, sidecar_name: str, runtime_socket_volume: str) -> dict:
    """Generate a runtime service definition for an actor."""
    env: dict[str, str] = {
        "ASYA_HANDLER": actor["handler"],
        "ASYA_SOCKET_DIR": RUNTIME_SOCKET_DIR,
        "ASYA_LOG_LEVEL": "INFO",
    }
    # Add user-defined env vars
    for e in actor.get("env", []):
        env[e["name"]] = str(e.get("value", ""))

    service: dict = {
        "image": actor["image"],
        "environment": env,
        "depends_on": {sidecar_name: {"condition": "service_started"}},
        "volumes": [
            f"{runtime_socket_volume}:{RUNTIME_SOCKET_DIR}",
        ],
    }
    return service


def _sink_service() -> dict:
    """x-sink system actor — acks and logs final results."""
    return {
        "image": SIDECAR_IMAGE,
        "environment": {
            "ASYA_TRANSPORT": "socket",
            "ASYA_ACTOR_NAME": "x-sink",
            "ASYA_NAMESPACE": "local",
            "ASYA_SOCKET_DIR": MESH_DIR,
            "ASYA_IS_END_ACTOR": "true",
            "ASYA_LOG_LEVEL": "INFO",
            "ASYA_METRICS_ENABLED": "false",
        },
        "volumes": [
            f"{MESH_VOLUME}:{MESH_DIR}",
        ],
    }


def _sump_service() -> dict:
    """x-sump system actor — DLQ handler for local testing."""
    return {
        "image": SIDECAR_IMAGE,
        "environment": {
            "ASYA_TRANSPORT": "socket",
            "ASYA_ACTOR_NAME": "x-sump",
            "ASYA_NAMESPACE": "local",
            "ASYA_SOCKET_DIR": MESH_DIR,
            "ASYA_IS_END_ACTOR": "true",
            "ASYA_LOG_LEVEL": "INFO",
            "ASYA_METRICS_ENABLED": "false",
        },
        "volumes": [
            f"{MESH_VOLUME}:{MESH_DIR}",
        ],
    }


def generate_compose(actors: list[dict], flow_name: str) -> dict:
    """Generate a docker-compose.yaml structure from parsed actor info.

    Each actor gets a sidecar + runtime service pair. System actors
    x-sink and x-sump are added automatically.
    """
    services: dict = {}
    volumes: dict = {MESH_VOLUME: None}

    for actor_doc in actors:
        info = _extract_actor_info(actor_doc)
        name = info["name"]

        # Per-actor volume for sidecar↔runtime socket communication
        runtime_vol = f"rt-{name}"
        volumes[runtime_vol] = None

        sidecar_name = f"{name}-sidecar"
        runtime_name = f"{name}-runtime"

        services[sidecar_name] = _sidecar_service(info, runtime_vol)
        services[runtime_name] = _runtime_service(info, sidecar_name, runtime_vol)

    # System actors
    services["x-sink"] = _sink_service()
    services["x-sump"] = _sump_service()

    return {
        "name": f"asya-{flow_name}",
        "services": services,
        "volumes": volumes,
    }


def write_compose(compose: dict, output_path: Path) -> Path:
    """Write docker-compose.yaml to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.dump(compose, default_flow_style=False, sort_keys=False)
    output_path.write_text(content)
    return output_path
