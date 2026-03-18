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

SIDECAR_IMAGE = "asya-sidecar:latest"
MESH_VOLUME = "asya-mesh"
MESH_DIR = "/var/run/asya/mesh"
RUNTIME_SOCKET_DIR = "/var/run/asya"
RUNTIME_MOUNT_PATH = "/opt/asya/asya_runtime.py"
HANDLERS_MOUNT_PATH = "/opt/asya/handlers"
ROUTERS_MOUNT_PATH = "/opt/asya/routers"


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


def load_actors_from_yaml(yaml_text: str) -> list[dict]:
    """Load AsyncActor documents from a rendered YAML string.

    Parses multi-document YAML and returns only AsyncActor documents.
    """
    actors: list[dict] = []
    for doc in yaml.safe_load_all(yaml_text):
        if not isinstance(doc, dict):
            continue
        if doc.get("kind") != "AsyncActor":
            continue
        actors.append(doc)
    return actors


def _extract_actor_info(doc: dict) -> dict:
    """Extract actor info from an AsyncActor doc.

    Reads from the flat XRD structure: spec.image, spec.handler,
    spec.pythonExecutable, spec.env, spec.sidecar.
    """
    metadata = doc.get("metadata", {})
    spec = doc.get("spec", {})
    sidecar_spec = spec.get("sidecar", {})
    name = metadata.get("name", "unknown")

    env_vars: list[dict] = []
    for env in spec.get("env", []):
        env_name = env.get("name", "")
        if env_name == "ASYA_STATE_PROXY_MOUNTS":
            continue
        if "valueFrom" not in env:
            env_vars.append(env)

    sidecar_env: list[dict] = []
    for env in sidecar_spec.get("env", []):
        if "valueFrom" not in env:
            sidecar_env.append(env)

    return {
        "name": name,
        "actor": spec.get("actor", name),
        "image": spec.get("image", ""),
        "handler": spec.get("handler", ""),
        "python_executable": spec.get("pythonExecutable", "python3"),
        "env": env_vars,
        "sidecar_image": sidecar_spec.get("image", SIDECAR_IMAGE),
        "sidecar_env": sidecar_env,
    }


# ---------------------------------------------------------------------------
# Compose generation
# ---------------------------------------------------------------------------


def _sidecar_service(actor: dict, runtime_socket_volume: str) -> dict:
    """Generate a sidecar service definition for an actor."""
    name = actor["name"]
    env: dict[str, str] = {
        "ASYA_TRANSPORT": "socket",
        "ASYA_ACTOR_NAME": name,
        "ASYA_NAMESPACE": "local",
        "ASYA_SOCKET_MESH_DIR": MESH_DIR,
        "ASYA_SOCKET_DIR": RUNTIME_SOCKET_DIR,
        "ASYA_ACTOR_SINK": "x-sink",
        "ASYA_ACTOR_SUMP": "x-sump",
        "ASYA_LOG_LEVEL": "INFO",
        "ASYA_METRICS_ENABLED": "false",
    }
    for e in actor.get("sidecar_env", []):
        env[e["name"]] = str(e.get("value", ""))

    return {
        "image": actor.get("sidecar_image", SIDECAR_IMAGE),
        "user": "root",
        "environment": env,
        "volumes": [
            f"{MESH_VOLUME}:{MESH_DIR}",
            f"{runtime_socket_volume}:{RUNTIME_SOCKET_DIR}",
        ],
    }


def _runtime_service(
    actor: dict,
    sidecar_name: str,
    runtime_socket_volume: str,
    runtime_py: str,
    handler_dir: str | None = None,
    routers_dir: str | None = None,
) -> dict:
    """Generate a runtime service definition for an actor."""
    env: dict[str, str] = {
        "ASYA_HANDLER": actor["handler"],
        "ASYA_SOCKET_DIR": RUNTIME_SOCKET_DIR,
        "ASYA_LOG_LEVEL": "INFO",
        "PYTHONUNBUFFERED": "1",
    }

    # Build PYTHONPATH from mounted directories
    python_paths: list[str] = []
    if handler_dir:
        python_paths.append(HANDLERS_MOUNT_PATH)
    if routers_dir:
        python_paths.append(ROUTERS_MOUNT_PATH)
    if python_paths:
        env["PYTHONPATH"] = ":".join(python_paths)

    # Add user-defined env vars
    for e in actor.get("env", []):
        env[e["name"]] = str(e.get("value", ""))

    volumes = [
        f"{runtime_socket_volume}:{RUNTIME_SOCKET_DIR}",
        f"{runtime_py}:{RUNTIME_MOUNT_PATH}:ro",
    ]
    if handler_dir:
        volumes.append(f"{handler_dir}:{HANDLERS_MOUNT_PATH}:ro")
    if routers_dir:
        volumes.append(f"{routers_dir}:{ROUTERS_MOUNT_PATH}:ro")

    service: dict = {
        "image": actor["image"],
        "command": [actor.get("python_executable", "python3"), RUNTIME_MOUNT_PATH],
        "environment": env,
        "depends_on": {sidecar_name: {"condition": "service_started"}},
        "volumes": volumes,
    }
    if handler_dir:
        service["working_dir"] = HANDLERS_MOUNT_PATH

    return service


def _sink_service() -> dict:
    """x-sink system actor — acks and logs final results."""
    return {
        "image": SIDECAR_IMAGE,
        "user": "root",
        "environment": {
            "ASYA_TRANSPORT": "socket",
            "ASYA_ACTOR_NAME": "x-sink",
            "ASYA_NAMESPACE": "local",
            "ASYA_SOCKET_MESH_DIR": MESH_DIR,
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
        "user": "root",
        "environment": {
            "ASYA_TRANSPORT": "socket",
            "ASYA_ACTOR_NAME": "x-sump",
            "ASYA_NAMESPACE": "local",
            "ASYA_SOCKET_MESH_DIR": MESH_DIR,
            "ASYA_IS_END_ACTOR": "true",
            "ASYA_LOG_LEVEL": "INFO",
            "ASYA_METRICS_ENABLED": "false",
        },
        "volumes": [
            f"{MESH_VOLUME}:{MESH_DIR}",
        ],
    }


def _cli_service() -> dict:
    """asya-cli helper — lightweight container for `asya d send`.

    Uses the 'cli' profile so it doesn't start with `docker compose up`.
    Started on-demand via `docker compose run --rm asya-cli`.
    """
    return {
        "image": "python:3-alpine",
        "environment": {
            "ASYA_SOCKET_MESH_DIR": MESH_DIR,
        },
        "volumes": [
            f"{MESH_VOLUME}:{MESH_DIR}",
        ],
        "profiles": ["cli"],
    }


def generate_compose(
    actors: list[dict],
    flow_name: str,
    runtime_py: str,
    handler_dir: str | None = None,
    routers_dir: str | None = None,
) -> dict:
    """Generate a docker-compose.yaml structure from parsed actor info.

    Each actor gets a sidecar + runtime service pair. System actors
    x-sink and x-sump are added automatically. An asya-cli helper
    service is included for `asya d send` (profiled, not started by default).

    Args:
        runtime_py: Absolute path to asya_runtime.py for bind-mounting
            into runtime containers.
        handler_dir: Optional path to a directory containing handler modules.
            Mounted at /opt/asya/handlers/ with PYTHONPATH set.
        routers_dir: Optional path to compiled routers directory.
            Mounted at /opt/asya/routers/ with PYTHONPATH set.
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
        services[runtime_name] = _runtime_service(info, sidecar_name, runtime_vol, runtime_py, handler_dir, routers_dir)

    # System actors
    services["x-sink"] = _sink_service()
    services["x-sump"] = _sump_service()

    # CLI helper for `asya d send`
    services["asya-cli"] = _cli_service()

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
