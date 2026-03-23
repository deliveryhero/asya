"""Kubernetes CLI commands (`asya k`).

Commands that interact with a Kubernetes cluster: apply, delete, status, logs,
edit, context, secret.
"""

from __future__ import annotations

import re
import subprocess  # nosec B404
import sys
from pathlib import Path

import click
import yaml

from asya_lab.cli_types import ASYA_REF, AsyaRef
from asya_lab.config.discovery import (
    BASE_DIR,
    COMMON_DIR,
    OVERLAYS_DIR,
    find_asya_dir,
)
from asya_lab.config.project import AsyaProject


# ---------------------------------------------------------------------------
# KubeRunner — holds project context, exposes kubectl methods
# ---------------------------------------------------------------------------


class KubeRunner:
    """Project-aware kubectl command runner.

    Encapsulates .asya/ project loading, context/namespace resolution,
    manifest directory lookup, and kubectl execution.
    """

    def __init__(self, ctx: str | None = None, arg_values: dict[str, str] | None = None) -> None:
        asya_dir = find_asya_dir(Path.cwd())
        if asya_dir is None:
            click.echo("[-] No .asya/ directory found. Run 'asya init' first.", err=True)
            sys.exit(1)

        self.project = AsyaProject.from_dir(asya_dir.parent, arg_values=arg_values)
        self._ctx_name = ctx
        self._context_config = self._resolve_context(ctx)
        self.namespace: str | None = self._context_config.get("namespace") if self._context_config else None

    def _resolve_context(self, ctx: str | None) -> dict | None:
        """Resolve context configuration. Returns None only when contexts are not configured."""
        contexts = self.project.cfg.get("contexts")
        if not contexts:
            return None

        if ctx is None:
            ctx = self.project.cfg.get("default_context")
            if ctx is None:
                return None

        if ctx not in contexts:
            click.echo(f"[-] Context '{ctx}' not found in config", err=True)
            available = list(contexts.keys())
            click.echo(f"[-] Available contexts: {', '.join(available)}", err=True)
            sys.exit(1)

        return dict(contexts[ctx])

    def check_readonly(self, action: str) -> None:
        """Fail if the context is marked readonly."""
        if self._context_config and self._context_config.get("readonly"):
            click.echo(f"[-] Context is readonly: {action} is not allowed", err=True)
            click.echo("[-] Production writes should happen via GitOps (commit + PR)", err=True)
            sys.exit(1)

    def find_manifests(self, target: str) -> Path:
        """Locate the manifest directory for a compiled flow/actor."""
        manifests_dir = self.project.resolve_path("compiler.manifests")
        if not manifests_dir.is_dir():
            click.echo(f"[-] Manifests not found: {manifests_dir}", err=True)
            click.echo("[-] Run 'asya compile' first.", err=True)
            sys.exit(1)
        return manifests_dir

    def resolve_overlay(self, manifests_dir: Path) -> Path:
        """Resolve the kustomize overlay path for the current context."""
        if self._ctx_name:
            overlay = manifests_dir / OVERLAYS_DIR / self._ctx_name
        elif (manifests_dir / COMMON_DIR).is_dir():
            overlay = manifests_dir / COMMON_DIR
        else:
            overlay = manifests_dir / BASE_DIR

        if not overlay.is_dir():
            if self._ctx_name:
                click.echo(f"[-] Overlay not found: {overlay}", err=True)
                click.echo(f"[-] Create it with: mkdir -p {overlay}", err=True)
            else:
                click.echo(f"[-] Kustomize path not found: {overlay}", err=True)
            sys.exit(1)

        return overlay

    @staticmethod
    def run_cmd(cmd: list[str], quiet: bool = False, **kwargs) -> subprocess.CompletedProcess:
        """Run a shell command, printing it first with + prefix."""
        if not quiet:
            click.echo(f"+ {' '.join(cmd)}", err=True)
        return subprocess.run(cmd, check=False, **kwargs)  # nosec B603

    def kubectl(self, *args: str, quiet: bool = False, **kwargs) -> subprocess.CompletedProcess:
        """Run kubectl with automatic namespace injection."""
        cmd = ["kubectl", *args]
        if self.namespace:
            cmd.extend(["-n", self.namespace])
        return self.run_cmd(cmd, quiet=quiet, **kwargs)

    def kustomize_apply(self, overlay: Path, field_manager: str) -> None:
        """Run kustomize build piped to kubectl apply --server-side."""
        kustomize_result = self.run_cmd(["kubectl", "kustomize", str(overlay)], capture_output=True, text=True)
        if kustomize_result.returncode != 0:
            click.echo(kustomize_result.stderr, err=True)
            sys.exit(kustomize_result.returncode)

        apply_cmd = [
            "kubectl",
            "apply",
            "--server-side",
            "--force-conflicts",
            f"--field-manager={field_manager}",
            "-f",
            "-",
        ]
        if self.namespace:
            apply_cmd.extend(["-n", self.namespace])

        click.echo(f"+ {' '.join(apply_cmd)}", err=True)
        apply_result = subprocess.run(  # nosec B603, B607
            apply_cmd,
            input=kustomize_result.stdout,
            capture_output=True,
            text=True,
            check=False,
        )
        if apply_result.stdout:
            click.echo(apply_result.stdout, nl=False)
        if apply_result.returncode != 0:
            click.echo(apply_result.stderr, err=True)
            sys.exit(apply_result.returncode)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_flow_for_actor(manifests_dir: Path, actor_name: str) -> str | None:
    """Find which flow an actor belongs to by searching compiled manifests."""
    for flow_dir in manifests_dir.iterdir():
        if not flow_dir.is_dir():
            continue
        base_dir = flow_dir / BASE_DIR
        if not base_dir.is_dir():
            continue
        for yaml_file in base_dir.glob("*.yaml"):
            if yaml_file.name == "kustomization.yaml":
                continue
            try:
                for doc in yaml.safe_load_all(yaml_file.read_text()):
                    if isinstance(doc, dict) and doc.get("metadata", {}).get("name") == actor_name:
                        return flow_dir.name
            except yaml.YAMLError:
                continue
    return None


# ---------------------------------------------------------------------------
# asya k apply
# ---------------------------------------------------------------------------


def _register_flow_with_gateway(runner: KubeRunner, flow_name: str) -> None:
    """Patch the gateway deployment to mount the per-flow ConfigMap.

    After `asya k apply` deploys a flow-expose CM (asya-flow-<name>-config),
    this patches the gateway-api deployment's projected volume to include it.
    Idempotent — skips if the CM doesn't exist or is already mounted.
    """
    import json as _json

    cm_name = f"asya-flow-{flow_name}-config"

    # Check if the per-flow CM exists
    result = runner.kubectl(
        "get",
        "cm",
        cm_name,
        "-o",
        "name",
        quiet=True,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return

    # Check if already in the projected volume
    result = runner.kubectl(
        "get",
        "deployment",
        "asya-gateway-api",
        "-o",
        "jsonpath={.spec.template.spec.volumes[?(@.name=='gateway-flows')].projected.sources}",
        quiet=True,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return
    if cm_name in result.stdout:
        return

    # Find the volume index for gateway-flows
    vol_result = runner.kubectl(
        "get",
        "deployment",
        "asya-gateway-api",
        "-o",
        "jsonpath={.spec.template.spec.volumes}",
        quiet=True,
        capture_output=True,
        text=True,
    )
    if vol_result.returncode != 0:
        return

    volumes = _json.loads(vol_result.stdout)
    vol_idx = next((i for i, v in enumerate(volumes) if v.get("name") == "gateway-flows"), None)
    if vol_idx is None:
        return

    # Count existing sources to append at the end
    sources = volumes[vol_idx].get("projected", {}).get("sources", [])
    source_idx = len(sources)

    patch = [
        {
            "op": "add",
            "path": f"/spec/template/spec/volumes/{vol_idx}/projected/sources/{source_idx}",
            "value": {"configMap": {"name": cm_name, "optional": True}},
        }
    ]
    patch_result = runner.kubectl(
        "patch",
        "deployment",
        "asya-gateway-api",
        "--type=json",
        f"-p={_json.dumps(patch)}",
        quiet=True,
        capture_output=True,
        text=True,
    )
    if patch_result.returncode == 0:
        click.echo(f"[+] Registered flow '{flow_name}' with gateway (projected volume)")
    else:
        click.echo(f"[!] Could not register flow with gateway: {patch_result.stderr.strip()}", err=True)


@click.command()
@click.argument("target", type=ASYA_REF)
@click.option("--context", "ctx", default=None, help="K8s context from .asya/config.yaml")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def apply(target: AsyaRef, ctx: str, verbose: bool) -> None:
    """Apply compiled manifests to a Kubernetes cluster.

    TARGET is a flow name (kebab-case, snake_case, or path/to/flow.py).

    Uses kustomize build piped to kubectl apply --server-side with
    per-flow field manager for safe, idempotent deploys. If the flow
    includes a gateway-flows ConfigMap (from `asya expose`), the
    gateway deployment is automatically patched to mount it.
    """
    runner = KubeRunner(ctx, arg_values={"flow_name": target.name})
    runner.check_readonly("apply")

    manifests_dir = runner.find_manifests(target.name)
    overlay = runner.resolve_overlay(manifests_dir)

    runner.kustomize_apply(overlay, field_manager=f"asya-flow-{target.name}")
    _register_flow_with_gateway(runner, target.name)


# ---------------------------------------------------------------------------
# asya k delete
# ---------------------------------------------------------------------------


@click.command()
@click.argument("target", type=ASYA_REF)
@click.option("--context", "ctx", default=None, help="K8s context from .asya/config.yaml")
def delete(target: AsyaRef, ctx: str) -> None:
    """Delete a deployed flow from the cluster.

    TARGET is the flow name. Deletes all resources with label asya.sh/flow=<name>.
    """
    runner = KubeRunner(ctx)
    runner.check_readonly("delete")

    result = runner.kubectl("delete", "asyncactor", "-l", f"asya.sh/flow={target.name}")
    if result.returncode != 0:
        sys.exit(result.returncode)


# ---------------------------------------------------------------------------
# asya k status
# ---------------------------------------------------------------------------


@click.command("status")
@click.argument("target", type=ASYA_REF)
@click.option("--context", "ctx", default=None, help="K8s context from .asya/config.yaml")
def k_status(target: AsyaRef, ctx: str) -> None:
    """Show live cluster status for a deployed flow.

    TARGET is the flow name. Shows replicas, phase, and pod status.
    """
    runner = KubeRunner(ctx)

    result = runner.kubectl(
        "get",
        "asyncactor",
        "-l",
        f"asya.sh/flow={target.name}",
        "-o",
        "wide",
        capture_output=True,
        text=True,
    )
    if result.stdout:
        click.echo(result.stdout, nl=False)
    if result.returncode != 0:
        click.echo(result.stderr, err=True)
        sys.exit(result.returncode)


# ---------------------------------------------------------------------------
# asya k logs
# ---------------------------------------------------------------------------


_ACTOR_COLORS = [
    "\033[36m",  # cyan
    "\033[33m",  # yellow
    "\033[32m",  # green
    "\033[35m",  # magenta
    "\033[34m",  # blue
    "\033[91m",  # bright red
    "\033[92m",  # bright green
    "\033[93m",  # bright yellow
    "\033[94m",  # bright blue
    "\033[95m",  # bright magenta
]
_RESET = "\033[0m"


def _get_flow_pods(runner: KubeRunner, flow_name: str) -> dict[str, str]:
    """Get pod-name -> actor-name mapping for a flow.

    Returns dict mapping pod names to actor names extracted from the
    app.kubernetes.io/name label.
    """
    import json as _json

    result = runner.kubectl(
        "get",
        "pods",
        "-l",
        f"asya.sh/flow={flow_name}",
        "-o",
        "json",
        quiet=True,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {}

    data = _json.loads(result.stdout)
    pod_actor: dict[str, str] = {}
    for item in data.get("items", []):
        pod_name = item["metadata"]["name"]
        labels = item["metadata"].get("labels", {})
        actor_name = labels.get("app.kubernetes.io/name", pod_name)
        pod_actor[pod_name] = actor_name
    return pod_actor


def _color_for(actor: str, actor_colors: dict[str, str]) -> str:
    """Get or assign a color for an actor name."""
    if actor not in actor_colors:
        idx = len(actor_colors) % len(_ACTOR_COLORS)
        actor_colors[actor] = _ACTOR_COLORS[idx]
    return actor_colors[actor]


def _stream_colored_logs(
    runner: KubeRunner,
    flow_name: str,
    containers: list[str],
    follow: bool,
    tail: int | None,
) -> None:
    """Stream logs from all flow pods with colored actor-name prefixes.

    Spawns one kubectl logs process per (pod, container) pair and
    multiplexes output with colored actor-name prefixes, similar to
    docker-compose log output.
    """
    import selectors
    import signal

    pod_actor = _get_flow_pods(runner, flow_name)
    if not pod_actor:
        click.echo("[-] No pods found for flow", err=True)
        sys.exit(1)

    actor_colors: dict[str, str] = {}
    max_prefix_len = 0
    for actor in sorted(set(pod_actor.values())):
        _color_for(actor, actor_colors)
        max_prefix_len = max(max_prefix_len, len(actor))

    # Show multi-container suffix only when multiple containers requested
    show_container_suffix = len(containers) > 1

    procs: list[tuple[subprocess.Popen, str, str]] = []
    ns_args = ["-n", runner.namespace] if runner.namespace else []

    for pod_name, actor_name in sorted(pod_actor.items()):
        for container in containers:
            cmd = ["kubectl", "logs", *ns_args, pod_name, "-c", container]
            if follow:
                cmd.append("-f")
            if tail is not None:
                cmd.extend(["--tail", str(tail)])
            else:
                cmd.extend(["--tail", "100"])

            try:
                proc = subprocess.Popen(  # nosec B603, B607
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                procs.append((proc, actor_name, container))
            except FileNotFoundError:
                click.echo("[-] kubectl not found", err=True)
                sys.exit(1)

    if not procs:
        click.echo("[-] No log streams started", err=True)
        sys.exit(1)

    sel = selectors.DefaultSelector()
    for proc, actor_name, container in procs:
        assert proc.stdout is not None
        sel.register(proc.stdout, selectors.EVENT_READ, (actor_name, container))

    def _cleanup(signum=None, frame=None):
        for proc, _, _ in procs:
            proc.terminate()
        sel.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    try:
        active = len(procs)
        while active > 0:
            events = sel.select(timeout=1.0)
            for key, _mask in events:
                actor_name, container = key.data
                fobj = key.fileobj
                assert hasattr(fobj, "readline")
                line = fobj.readline()
                if not line:
                    sel.unregister(key.fileobj)
                    active -= 1
                    continue

                text = line.decode("utf-8", errors="replace").rstrip("\n")
                color = actor_colors[actor_name]
                padded = actor_name.ljust(max_prefix_len)
                if show_container_suffix:
                    prefix = f"{color}{padded}|{container}{_RESET}"
                else:
                    prefix = f"{color}{padded}{_RESET}"
                click.echo(f"{prefix} | {text}")
    finally:
        _cleanup()


@click.command()
@click.argument("target", type=ASYA_REF)
@click.option("--context", "ctx", default=None, help="K8s context from .asya/config.yaml")
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
@click.option("--tail", type=int, default=None, help="Number of lines to show from end")
@click.option(
    "--container",
    "-c",
    "containers",
    multiple=True,
    help="Container(s) to show (default: asya-runtime). Use -c asya-sidecar to add sidecar logs.",
)
def logs(target: AsyaRef, ctx: str, follow: bool, tail: int | None, containers: tuple[str, ...]) -> None:
    """Stream logs for a deployed flow with colored actor-name prefixes.

    TARGET is the flow name. Shows logs from all pods matching asya.sh/flow label.
    Output is styled like docker-compose, with each actor in a different color.

    \b
    Examples:
      asya k logs text-flow              # runtime logs from all actors
      asya k logs text-flow -f           # follow mode
      asya k logs text-flow -c asya-runtime -c asya-sidecar  # both containers
    """
    if not containers:
        containers = ("asya-runtime",)

    runner = KubeRunner(ctx)
    _stream_colored_logs(runner, target.name, list(containers), follow, tail)


# ---------------------------------------------------------------------------
# asya k edit
# ---------------------------------------------------------------------------


_PATCH_TEMPLATE = """\
# Kustomize patch for {actor_name}
# Uncomment and modify fields you want to override.
#
# This file is applied on top of the compiler-generated base/ manifest.
# See base/asya-{actor_name}.yaml for all available fields.
#
# apiVersion: asya.sh/v1alpha1
# kind: AsyncActor
# metadata:
#   name: {actor_name}
# spec:
#   scaling:
#     maxReplicaCount: 20
#   env:
#     - name: MY_VAR
#       value: "my-value"
"""


@click.command()
@click.argument("actor_name", type=ASYA_REF)
def edit(actor_name: AsyaRef) -> None:
    """Open a kustomize patch for an actor in common/.

    Creates the patch file if it doesn't exist, then opens it in $EDITOR.
    """
    import os

    runner = KubeRunner()
    manifests_dir = runner.project.resolve_path("compiler.manifests")
    if not manifests_dir.is_dir():
        click.echo("[-] No manifests directory found. Run 'asya compile' first.", err=True)
        sys.exit(1)

    name = actor_name.name
    target_flow = _find_flow_for_actor(manifests_dir, name)

    if not target_flow:
        click.echo(f"[-] Actor '{name}' not found in any compiled flow", err=True)
        sys.exit(1)

    common_dir = manifests_dir / target_flow / COMMON_DIR
    common_dir.mkdir(parents=True, exist_ok=True)

    patch_file = common_dir / f"patch-{name}.yaml"
    if not patch_file.exists():
        patch_file.write_text(_PATCH_TEMPLATE.format(actor_name=name))
        click.echo(f"[+] Created patch file: {patch_file}")

        # Ensure kustomization.yaml references this patch
        kust_path = common_dir / "kustomization.yaml"
        if kust_path.exists():
            kust = yaml.safe_load(kust_path.read_text()) or {}
        else:
            kust = {
                "apiVersion": "kustomize.config.k8s.io/v1beta1",
                "kind": "Kustomization",
                "resources": ["../base"],
            }

        patches = kust.get("patches", [])
        patch_ref = {"path": patch_file.name}
        if patch_ref not in patches:
            patches.append(patch_ref)
            kust["patches"] = patches
            kust_path.write_text(yaml.dump(kust, default_flow_style=False, sort_keys=False))
            click.echo(f"[+] Updated {kust_path}")

    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", "vi"))
    click.echo(f"[.] Opening {patch_file} in {editor}")

    os.execvp(editor, [editor, str(patch_file)])  # nosec B606


# ---------------------------------------------------------------------------
# asya k context
# ---------------------------------------------------------------------------


@click.group("context")
def context_group() -> None:
    """Manage Kubernetes contexts."""


@context_group.command("list")
def context_list() -> None:
    """List configured contexts.

    Shows asya contexts from .asya/config.yaml if configured,
    otherwise falls through to kubectl config get-contexts.
    """
    asya_dir = find_asya_dir(Path.cwd())
    if asya_dir is not None:
        try:
            project = AsyaProject.from_dir(asya_dir.parent)
        except (FileNotFoundError, KeyError):
            project = None

        if project is not None:
            contexts = project.cfg.get("contexts")
            if contexts:
                default_ctx = project.cfg.get("default_context")
                for name in contexts:
                    ctx = contexts[name]
                    marker = "*" if name == default_ctx else " "
                    kubecontext = ctx.get("kubecontext", "")
                    namespace = ctx.get("namespace", "")
                    readonly = " (readonly)" if ctx.get("readonly") else ""
                    click.echo(f"  {marker} {name:<20} kubecontext={kubecontext:<30} namespace={namespace}{readonly}")
                return

    result = subprocess.run(  # nosec B603, B607
        ["kubectl", "config", "get-contexts"],
        check=False,
    )
    sys.exit(result.returncode)


@context_group.command("use")
@click.argument("name")
def context_use(name: str) -> None:
    """Set the default context.

    If asya contexts are configured in .asya/config.yaml, updates
    default_context there. Otherwise falls through to kubectl config use-context.
    """
    asya_dir = find_asya_dir(Path.cwd())

    if asya_dir is not None:
        config_path = asya_dir / "config.yaml"
        if config_path.exists():
            text = config_path.read_text()
            config = yaml.safe_load(text) or {}
            contexts = config.get("contexts", {})

            if contexts:
                if name not in contexts:
                    click.echo(f"[-] Context '{name}' not found", err=True)
                    available = list(contexts.keys())
                    if available:
                        click.echo(f"[-] Available: {', '.join(available)}", err=True)
                    sys.exit(1)

                pattern = re.compile(r"^(?!#)(\s*)default_context:.*$", re.MULTILINE)
                if pattern.search(text):
                    text = pattern.sub(rf"\1default_context: {name}", text)
                else:
                    text = text.rstrip() + f"\ndefault_context: {name}\n"
                config_path.write_text(text)
                click.echo(f"[+] Default context set to '{name}'")
                return

    result = subprocess.run(  # nosec B603, B607
        ["kubectl", "config", "use-context", name],
        check=False,
    )
    sys.exit(result.returncode)


# ---------------------------------------------------------------------------
# asya k send
# ---------------------------------------------------------------------------


@click.command()
@click.argument("target", type=ASYA_REF)
@click.argument("message", required=True)
@click.option("--context", "ctx", default=None, help="K8s context from .asya/config.yaml")
@click.option("--url", default=None, help="Gateway URL (default: auto-detect via port-forward)")
@click.option("--skill", default=None, help="Skill hint when multiple flows are registered")
@click.option("--follow", "-f", is_flag=True, help="Stream FLY events (not yet implemented)")
def send(target: AsyaRef, message: str, ctx: str, url: str | None, skill: str | None, follow: bool) -> None:
    """Send a message to a deployed flow via A2A.

    TARGET is the flow name. MESSAGE is the text payload.

    \b
    Examples:
      asya k send text-flow "Analyze this text"
      asya k send text-flow '{"key": "value"}'
      asya k send greet-flow "Hello" --skill greet-flow
    """
    import json as _json
    import uuid

    if url is None:
        runner = KubeRunner(ctx)
        # Try to detect gateway URL from port-forward or service
        url = _detect_gateway_url(runner)

    task_id = str(uuid.uuid4())
    msg_id = str(uuid.uuid4())

    parts = [{"kind": "text", "text": message}]

    request = {
        "jsonrpc": "2.0",
        "id": task_id,
        "method": "message/send",
        "params": {
            "message": {
                "messageId": msg_id,
                "role": "user",
                "parts": parts,
            },
        },
    }
    if skill:
        request["params"]["metadata"] = {"skill": skill}

    click.echo(f"[.] Sending to {target.name} via {url}/a2a/", err=True)

    try:
        import urllib.request

        req = urllib.request.Request(
            f"{url}/a2a/",
            data=_json.dumps(request).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:  # nosec B310
            body = _json.loads(resp.read())
    except Exception as e:
        click.echo(f"[-] Request failed: {e}", err=True)
        sys.exit(1)

    if "error" in body:
        click.echo(f"[-] {body['error'].get('message', body['error'])}", err=True)
        sys.exit(1)

    result = body.get("result", {})
    state = result.get("status", {}).get("state", "unknown")
    result_id = result.get("id", "?")

    if state == "completed":
        click.echo(f"[+] Task {result_id}: {state}")
    elif state == "failed":
        click.echo(f"[-] Task {result_id}: {state}", err=True)
    else:
        click.echo(f"[.] Task {result_id}: {state}")

    click.echo(_json.dumps(result, indent=2))


def _detect_gateway_url(runner: KubeRunner) -> str:
    """Detect gateway URL: check if port-forward is active, otherwise start one."""
    import socket

    # Check if localhost:8080 is already forwarded
    try:
        with socket.create_connection(("127.0.0.1", 8080), timeout=1):
            return "http://127.0.0.1:8080"
    except OSError:
        pass

    # Start port-forward in background
    click.echo("[.] Starting port-forward to asya-gateway-api...", err=True)
    proc = subprocess.Popen(  # nosec B603, B607
        ["kubectl", "port-forward", "svc/asya-gateway-api", "8080:80"]
        + (["-n", runner.namespace] if runner.namespace else []),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for port to open
    import time

    for _ in range(10):
        time.sleep(1)  # wait for port-forward to establish
        try:
            with socket.create_connection(("127.0.0.1", 8080), timeout=1):
                return "http://127.0.0.1:8080"
        except OSError:
            continue

    proc.terminate()
    click.echo("[-] Could not establish port-forward. Use --url to specify gateway URL.", err=True)
    sys.exit(1)


# ---------------------------------------------------------------------------
# asya k (group)
# ---------------------------------------------------------------------------


@click.group("k")
def k() -> None:
    """Kubernetes commands (apply, delete, status, logs, send, edit, context)."""


k.add_command(apply)
k.add_command(delete)
k.add_command(k_status)
k.add_command(logs)
k.add_command(send)
k.add_command(edit)
k.add_command(context_group)
