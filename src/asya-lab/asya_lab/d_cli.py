"""Docker Compose commands (`asya d`).

Commands for local testing with Docker Compose and socket transport:
up, down, send, logs.
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404
import sys
import uuid
from pathlib import Path

import click

from asya_lab.compose import generate_compose, load_actors, load_actors_from_yaml, write_compose
from asya_lab.config.discovery import BASE_DIR, COMMON_DIR, find_asya_dir, find_git_root


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


def _resolve_kustomize_path(manifests_dir: Path) -> Path:
    """Resolve the kustomize overlay path for local rendering.

    Prefers common/ (base + user patches), falls back to base/.
    If neither exists, returns manifests_dir itself (flat layout).
    """
    common = manifests_dir / COMMON_DIR
    if common.is_dir():
        return common
    base = manifests_dir / BASE_DIR
    if base.is_dir():
        return base
    return manifests_dir


def _render_kustomize(kustomize_path: Path) -> str | None:
    """Run kubectl kustomize to render merged manifests.

    Returns rendered YAML string, or None if kubectl is unavailable
    or the directory has no kustomization.yaml.
    """
    kustomization = kustomize_path / "kustomization.yaml"
    if not kustomization.exists():
        return None

    if not shutil.which("kubectl"):
        click.echo("[!] kubectl not found, skipping kustomize overlay merge", err=True)
        return None

    result = subprocess.run(  # nosec B603, B607
        ["kubectl", "kustomize", str(kustomize_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        click.echo(f"[!] kustomize build failed: {result.stderr.strip()}", err=True)
        return None

    return result.stdout


def _find_runtime_py() -> str | None:
    """Locate asya_runtime.py for bind-mounting into runtime containers.

    Search order:
    1. .asya/runtime/asya_runtime.py (project-local override)
    2. src/asya-runtime/asya_runtime.py from git root
    3. Relative to asya_lab package (monorepo layout)
    """
    asya_dir = find_asya_dir(Path.cwd())
    if asya_dir is not None:
        local = asya_dir / "runtime" / "asya_runtime.py"
        if local.exists():
            return str(local.resolve())

    git_root = find_git_root(Path.cwd())
    if git_root is not None:
        src = git_root / "src" / "asya-runtime" / "asya_runtime.py"
        if src.exists():
            return str(src.resolve())

    # Monorepo layout: asya_lab is at src/asya-lab/asya_lab/
    # asya_runtime.py is at src/asya-runtime/asya_runtime.py
    pkg_dir = Path(__file__).resolve().parent  # asya_lab/
    src_dir = pkg_dir.parent.parent  # src/
    monorepo = src_dir / "asya-runtime" / "asya_runtime.py"
    if monorepo.exists():
        return str(monorepo)

    return None


def _find_handler_dir(source_path: Path | None) -> str | None:
    """Locate handler modules directory for bind-mounting into runtime containers.

    When target is a .py file, uses its parent directory.
    Otherwise looks for .asya/handlers/.
    """
    if source_path is not None:
        return str(source_path.resolve().parent)

    asya_dir = find_asya_dir(Path.cwd())
    if asya_dir is not None:
        # .asya/handlers/
        handlers = asya_dir / "handlers"
        if handlers.is_dir():
            return str(handlers.resolve())

        # handlers/ in project root
        project_handlers = asya_dir.parent / "handlers"
        if project_handlers.is_dir():
            return str(project_handlers.resolve())

    return None


def _find_routers_dir(flow_name: str) -> str | None:
    """Locate compiled routers directory for bind-mounting into runtime containers.

    Checks compiler.routers config path, falls back to .asya/compiled/.
    """
    asya_dir = find_asya_dir(Path.cwd())
    if asya_dir is None:
        return None

    flow_function = flow_name.replace("-", "_")

    # Try config-driven path (compiler.routers)
    try:
        from asya_lab.config.project import AsyaProject

        project = AsyaProject.from_dir(asya_dir.parent)
        routers_dir = project.resolve_path("compiler.routers") / flow_function
        if routers_dir.is_dir() and (routers_dir / "routers.py").exists():
            return str(routers_dir.resolve())
    except (FileNotFoundError, KeyError):
        pass

    # Fallback: .asya/compiled/<flow>/
    compiled = asya_dir / "compiled" / flow_function
    if compiled.is_dir() and (compiled / "routers.py").exists():
        return str(compiled.resolve())

    return None


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
@click.option("-d", "--detach", is_flag=True, help="Run in background (default: foreground with logs).")
def up(target: str, build: bool, detach: bool) -> None:
    """Start flow with Docker Compose.

    TARGET is a flow name or .py file. If a .py file is given, it is
    auto-compiled first. Runs in foreground by default so you see logs.

    \b
    Examples:
        asya d up flows/order.py        # compile + compose + start
        asya d up order-processing      # start from existing manifests
        asya d up order-processing -d   # start detached
    """
    flow_name, source_path = _resolve_target(target)

    if source_path is not None:
        manifests_dir = _auto_compile(source_path, flow_name)
    else:
        manifests_dir = _find_manifests_dir(flow_name)

    # Resolve kustomize overlay and render merged manifests
    kustomize_path = _resolve_kustomize_path(manifests_dir)
    rendered = _render_kustomize(kustomize_path)
    if rendered is not None:
        click.echo(f"[.] Rendered kustomize from {kustomize_path}", err=True)
        actors = load_actors_from_yaml(rendered)
    else:
        actors = load_actors(manifests_dir)

    if not actors:
        click.echo(f"[-] No AsyncActor manifests found in {manifests_dir}", err=True)
        sys.exit(1)

    runtime_py = _find_runtime_py()
    if runtime_py is None:
        click.echo("[-] asya_runtime.py not found. Expected in:", err=True)
        click.echo("[-]   .asya/runtime/asya_runtime.py", err=True)
        click.echo("[-]   src/asya-runtime/asya_runtime.py (from git root)", err=True)
        sys.exit(1)
    click.echo(f"[.] Using runtime: {runtime_py}", err=True)

    handler_dir = _find_handler_dir(source_path)
    if handler_dir:
        click.echo(f"[.] Mounting handlers: {handler_dir}", err=True)

    routers_dir = _find_routers_dir(flow_name)
    if routers_dir:
        click.echo(f"[.] Mounting routers: {routers_dir}", err=True)

    compose = generate_compose(
        actors, flow_name, runtime_py=runtime_py, handler_dir=handler_dir, routers_dir=routers_dir
    )
    compose_path = _compose_file_path(flow_name)
    write_compose(compose, compose_path)
    click.echo(f"[+] Generated {compose_path}", err=True)

    cmd = [*_get_compose_cmd(), "-f", str(compose_path), "up"]
    if detach:
        cmd.append("-d")
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


def _find_compose_file(flow: str | None) -> tuple[str, Path]:
    """Find the compose file for a flow.

    If flow is given, looks for .asya/compose/<flow>.yaml.
    If flow is None, auto-detects when exactly one compose file exists.
    Returns (flow_name, compose_path).
    """
    asya_dir = find_asya_dir(Path.cwd())
    if asya_dir is None:
        click.echo("[-] No .asya/ directory found. Run 'asya init' first.", err=True)
        sys.exit(1)

    compose_dir = asya_dir / "compose"
    if not compose_dir.is_dir():
        click.echo("[-] No compose files found. Run 'asya d up' first.", err=True)
        sys.exit(1)

    if flow is not None:
        flow_name = flow.replace("_", "-")
        compose_path = compose_dir / f"{flow_name}.yaml"
        if not compose_path.exists():
            click.echo(f"[-] Compose file not found: {compose_path}", err=True)
            click.echo("[-] Run 'asya d up' first.", err=True)
            sys.exit(1)
        return flow_name, compose_path

    # Auto-detect: exactly one compose file
    compose_files = list(compose_dir.glob("*.yaml"))
    if len(compose_files) == 0:
        click.echo("[-] No compose files found. Run 'asya d up' first.", err=True)
        sys.exit(1)
    if len(compose_files) > 1:
        names = [f.stem for f in compose_files]
        click.echo("[-] Multiple flows found. Specify --flow:", err=True)
        for name in sorted(names):
            click.echo(f"    asya d send --flow {name} <actor> <payload>", err=True)
        sys.exit(1)

    compose_path = compose_files[0]
    return compose_path.stem, compose_path


# Inline Python script executed inside the asya-cli container to send
# an envelope over the mesh Unix socket. Receives actor name and
# envelope JSON as command-line arguments.
# Protocol: 4-byte big-endian length prefix + JSON payload.
_SEND_SCRIPT = """\
import socket,sys,os
actor=sys.argv[1]
data=sys.argv[2].encode()
mesh=os.environ["ASYA_SOCKET_MESH_DIR"]
path=f"{mesh}/{actor}.sock"
if not os.path.exists(path):
    print(f"[-] Socket not found: {path}",file=sys.stderr)
    print(f"[-] Is actor '{actor}' running? Try 'asya d up' first.",file=sys.stderr)
    sys.exit(1)
s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
s.connect(path)
s.sendall(len(data).to_bytes(4,"big"))
s.sendall(data)
ack=s.recv(1)
if ack!=b"\\x01":
    print(f"[-] Unexpected ack: {ack!r}",file=sys.stderr)
    sys.exit(1)
s.close()
"""


@d.command()
@click.argument("actor")
@click.argument("payload")
@click.option("--flow", default=None, help="Flow name (auto-detected if only one).")
def send(actor: str, payload: str, flow: str | None) -> None:
    """Send an envelope to an actor via Docker Compose.

    Executes inside the asya-cli container which has access to the
    mesh socket volume. Auto-detects flow if only one is running.

    \b
    Examples:
        asya d send echo '{"msg": "hello"}'
        asya d send --flow my-flow echo '{"msg": "hello"}'
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

    flow_name, compose_path = _find_compose_file(flow)
    envelope_json = json.dumps(envelope)

    cmd = [
        *_get_compose_cmd(),
        "-f",
        str(compose_path),
        "run",
        "--rm",
        "-T",
        "asya-cli",
        "python3",
        "-c",
        _SEND_SCRIPT,
        actor_name,
        envelope_json,
    ]
    click.echo(f"[.] Sending envelope {envelope['id']} to {actor_name}", err=True)
    result = _run_cmd(cmd)
    if result.returncode != 0:
        sys.exit(result.returncode)
    click.echo(f"[+] Sent to {actor_name} via {flow_name}", err=True)


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
