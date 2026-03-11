"""Docker Compose commands (`asya d`).

Commands for local testing with Docker Compose and socket transport:
up, down, send, logs.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess  # nosec B404
import sys
import uuid
from pathlib import Path

import click

from asya_lab.compose import generate_compose, load_actors, write_compose
from asya_lab.config.discovery import find_asya_dir


# ---------------------------------------------------------------------------
# Docker Compose binary resolution
# ---------------------------------------------------------------------------

_COMPOSE_CMD: list[str] | None = None


def _get_compose_cmd() -> list[str]:
    """Return the docker compose command as a list of args.

    Resolution order:
    1. .asya/config.yaml -> docker.compose_command (string, e.g. "docker-compose")
    2. Auto-detect: try `docker compose` (v2 plugin), fall back to `docker-compose` (v1)
    """
    global _COMPOSE_CMD
    if _COMPOSE_CMD is not None:
        return list(_COMPOSE_CMD)

    # Try config
    asya_dir = find_asya_dir(Path.cwd())
    if asya_dir is not None:
        config_file = asya_dir / "config.yaml"
        if config_file.exists():
            import yaml

            try:
                cfg = yaml.safe_load(config_file.read_text()) or {}
                configured = cfg.get("docker", {}).get("compose_command")
                if configured:
                    _COMPOSE_CMD = configured.split()
                    return list(_COMPOSE_CMD)
            except yaml.YAMLError:
                pass

    # Auto-detect: try `docker compose version` (v2 plugin)
    try:
        subprocess.run(  # nosec B603, B607
            ["docker", "compose", "version"],
            check=True,
            capture_output=True,
        )
        _COMPOSE_CMD = ["docker", "compose"]
        return list(_COMPOSE_CMD)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Fall back to docker-compose (v1)
    if shutil.which("docker-compose"):
        _COMPOSE_CMD = ["docker-compose"]
        return list(_COMPOSE_CMD)

    # Nothing found — default to docker compose and let it fail with a clear error
    _COMPOSE_CMD = ["docker", "compose"]
    return list(_COMPOSE_CMD)


def _reset_compose_cmd() -> None:
    """Reset the cached compose command (for testing)."""
    global _COMPOSE_CMD
    _COMPOSE_CMD = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_target(target: str) -> tuple[str, Path | None]:
    """Resolve a CLI target to (flow_name, source_file_or_None).

    Returns:
        (flow_name, source_path) where source_path is set if target is a .py file.
    """
    if target.endswith(".py"):
        source = Path(target)
        if not source.exists():
            click.echo(f"[-] File not found: {target}", err=True)
            sys.exit(1)
        flow_name = source.stem.replace("_", "-")
        return flow_name, source

    flow_name = target.replace("_", "-")
    return flow_name, None


def _find_manifests_dir(flow_name: str) -> Path:
    """Locate the compiled manifests directory for a flow."""
    asya_dir = find_asya_dir(Path.cwd())
    if asya_dir is None:
        click.echo("[-] No .asya/ directory found. Run 'asya init' first.", err=True)
        sys.exit(1)

    manifests_dir = asya_dir / "manifests" / flow_name
    if not manifests_dir.is_dir():
        click.echo(f"[-] Manifests not found: {manifests_dir}", err=True)
        click.echo("[-] Run 'asya compile' first.", err=True)
        sys.exit(1)
    return manifests_dir


def _compose_file_path(flow_name: str) -> Path:
    """Return the path where the compose file should be written."""
    asya_dir = find_asya_dir(Path.cwd())
    if asya_dir is None:
        click.echo("[-] No .asya/ directory found. Run 'asya init' first.", err=True)
        sys.exit(1)
    return asya_dir / "compose" / f"{flow_name}.yaml"


def _run_cmd(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run a shell command, printing it first with + prefix."""
    click.echo(f"+ {' '.join(cmd)}", err=True)
    return subprocess.run(cmd, check=False)  # nosec B603


def _auto_compile(source_path: Path, flow_name: str) -> Path:
    """Auto-compile a .py flow file if needed. Returns manifests dir."""
    asya_dir = find_asya_dir(Path.cwd())
    if asya_dir is None:
        click.echo("[-] No .asya/ directory found. Run 'asya init' first.", err=True)
        sys.exit(1)

    output_dir = asya_dir / "manifests" / flow_name
    if output_dir.is_dir():
        click.echo(f"[.] Using existing manifests: {output_dir}", err=True)
        return output_dir

    click.echo(f"[.] Auto-compiling {source_path}...", err=True)
    from asya_lab.flow import FlowCompiler

    compiler = FlowCompiler()
    compiler.compile_file(str(source_path), str(output_dir), overwrite=True)
    click.echo(f"[+] Compiled to {output_dir}", err=True)
    return output_dir


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group("d")
def d():
    """Docker Compose commands for local testing."""


@d.command()
@click.argument("target")
@click.option("--build", is_flag=True, help="Build images before starting.")
def up(target: str, build: bool) -> None:
    """Start flow with Docker Compose.

    TARGET is a flow name or .py file. If a .py file is given, it is
    auto-compiled first.

    \b
    Examples:
        asya d up flows/order.py        # compile + compose + start
        asya d up order-processing      # start from existing manifests
    """
    flow_name, source_path = _resolve_target(target)

    if source_path is not None:
        manifests_dir = _auto_compile(source_path, flow_name)
    else:
        manifests_dir = _find_manifests_dir(flow_name)

    actors = load_actors(manifests_dir)
    if not actors:
        click.echo(f"[-] No AsyncActor manifests found in {manifests_dir}", err=True)
        sys.exit(1)

    compose = generate_compose(actors, flow_name)
    compose_path = _compose_file_path(flow_name)
    write_compose(compose, compose_path)
    click.echo(f"[+] Generated {compose_path}", err=True)

    cmd = [*_get_compose_cmd(), "-f", str(compose_path), "up", "-d"]
    if build:
        cmd.append("--build")
    result = _run_cmd(cmd)
    if result.returncode != 0:
        sys.exit(result.returncode)


@d.command()
@click.argument("target")
@click.option("-v", "--volumes", is_flag=True, help="Remove volumes too.")
def down(target: str, volumes: bool) -> None:
    """Stop flow containers.

    \b
    Examples:
        asya d down order-processing       # stop containers
        asya d down order-processing -v    # stop + remove volumes
    """
    flow_name, _ = _resolve_target(target)
    compose_path = _compose_file_path(flow_name)

    if not compose_path.exists():
        click.echo(f"[-] Compose file not found: {compose_path}", err=True)
        click.echo("[-] Run 'asya d up' first.", err=True)
        sys.exit(1)

    cmd = [*_get_compose_cmd(), "-f", str(compose_path), "down"]
    if volumes:
        cmd.append("-v")
    result = _run_cmd(cmd)
    if result.returncode != 0:
        sys.exit(result.returncode)


@d.command()
@click.argument("actor")
@click.argument("payload")
def send(actor: str, payload: str) -> None:
    """Send an envelope to an actor's Unix socket.

    \b
    Examples:
        asya d send echo '{"msg": "hello"}'
    """
    actor_name = actor.replace("_", "-")

    try:
        payload_data = json.loads(payload)
    except json.JSONDecodeError as e:
        click.echo(f"[-] Invalid JSON payload: {e}", err=True)
        sys.exit(1)

    envelope = {
        "id": str(uuid.uuid4()),
        "parent_id": None,
        "route": {
            "prev": [],
            "curr": actor_name,
            "next": [],
        },
        "headers": {},
        "payload": payload_data,
    }

    socket_path = Path(f"/var/run/asya/mesh/{actor_name}.sock")
    if not socket_path.exists():
        local_sock = Path(f".asya/mesh/{actor_name}.sock")
        if local_sock.exists():
            socket_path = local_sock
        else:
            click.echo(f"[-] Socket not found: {socket_path}", err=True)
            click.echo(
                f"[-] Is the actor '{actor_name}' running? Try 'asya d up' first.",
                err=True,
            )
            sys.exit(1)

    envelope_bytes = json.dumps(envelope).encode("utf-8")

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(str(socket_path))
        length = len(envelope_bytes)
        sock.sendall(length.to_bytes(4, byteorder="big"))
        sock.sendall(envelope_bytes)
        sock.close()
        click.echo(f"[+] Sent envelope {envelope['id']} to {actor_name}", err=True)
    except OSError as e:
        click.echo(f"[-] Failed to send to {actor_name}: {e}", err=True)
        sys.exit(1)


@d.command()
@click.argument("target")
@click.option("-f", "--follow", is_flag=True, help="Follow log output.")
@click.option("--tail", type=int, default=None, help="Number of lines from end.")
def logs(target: str, follow: bool, tail: int | None) -> None:
    """Stream logs for a flow's containers.

    \b
    Examples:
        asya d logs order-processing -f
        asya d logs order-processing --tail 50
    """
    flow_name, _ = _resolve_target(target)
    compose_path = _compose_file_path(flow_name)

    if not compose_path.exists():
        click.echo(f"[-] Compose file not found: {compose_path}", err=True)
        click.echo("[-] Run 'asya d up' first.", err=True)
        sys.exit(1)

    cmd = [*_get_compose_cmd(), "-f", str(compose_path), "logs"]
    if follow:
        cmd.append("-f")
    if tail is not None:
        cmd.extend(["--tail", str(tail)])
    result = _run_cmd(cmd)
    if result.returncode != 0:
        sys.exit(result.returncode)
