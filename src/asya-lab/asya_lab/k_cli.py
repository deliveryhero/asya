"""Kubernetes CLI commands (`asya k`).

Commands that interact with a Kubernetes cluster: apply, delete, status, logs,
edit, context, secret.
"""

from __future__ import annotations

import itertools
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
from asya_lab.gateway_register import register_flow_with_gateway


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
        self.kube_context: str | None = self._context_config.get("kubectl_context") if self._context_config else None

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
        """Run kubectl with automatic context and namespace injection."""
        cmd = ["kubectl"]
        if self.kube_context:
            cmd.extend(["--context", self.kube_context])
        cmd.extend(args)
        if self.namespace:
            cmd.extend(["-n", self.namespace])
        return self.run_cmd(cmd, quiet=quiet, **kwargs)

    def kustomize_apply(self, overlay: Path, field_manager: str) -> None:
        """Run kustomize build piped to kubectl apply --server-side."""
        kustomize_result = self.run_cmd(["kubectl", "kustomize", str(overlay)], capture_output=True, text=True)
        if kustomize_result.returncode != 0:
            click.echo(kustomize_result.stderr, err=True)
            sys.exit(kustomize_result.returncode)

        apply_cmd = ["kubectl"]
        if self.kube_context:
            apply_cmd.extend(["--context", self.kube_context])
        apply_cmd.extend(
            [
                "apply",
                "--server-side",
                "--force-conflicts",
                f"--field-manager={field_manager}",
                "-f",
                "-",
            ]
        )
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


@click.command()
@click.argument("target", type=ASYA_REF, required=False, default=None)
@click.option("--context", "ctx", default=None, help="K8s context from .asya/config.yaml")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def apply(target: AsyaRef | None, ctx: str, verbose: bool) -> None:
    """Apply compiled manifests to a Kubernetes cluster.

    TARGET is a flow name (kebab-case, snake_case, or path/to/flow.py).

    Uses kustomize build piped to kubectl apply --server-side with
    per-flow field manager for safe, idempotent deploys. If the flow was
    exposed (`asya expose` / `asya patch --gateway`), its A2A/MCP entry is
    upserted into the gateway's registry ConfigMaps, which hot-reload.
    """
    if target is None:
        raise click.MissingParameter(
            param_hint=f"'TARGET' (deployed flows: {_list_available_flows(ctx)})", param_type="argument"
        )
    runner = KubeRunner(ctx, arg_values={"flow_name": target.name})
    runner.check_readonly("apply")

    manifests_dir = runner.find_manifests(target.name)
    overlay = runner.resolve_overlay(manifests_dir)

    runner.kustomize_apply(overlay, field_manager=f"asya-flow-{target.name}")
    register_flow_with_gateway(runner, overlay, manifests_dir)

    # Rollout restart to pick up ConfigMap changes (routers, adapters)
    result = runner.kubectl(
        "rollout",
        "restart",
        "deployment",
        "-l",
        f"asya.sh/flow={target.name}",
        quiet=True,
    )
    if result.returncode == 0:
        click.echo(f"[.] Rolling restart: {target.name}")


# ---------------------------------------------------------------------------
# asya k delete
# ---------------------------------------------------------------------------


@click.command()
@click.argument("target", type=ASYA_REF, required=False, default=None)
@click.option("--context", "ctx", default=None, help="K8s context from .asya/config.yaml")
def delete(target: AsyaRef | None, ctx: str) -> None:
    """Delete a deployed flow from the cluster.

    TARGET is the flow name. Deletes all resources with label asya.sh/flow=<name>.
    """
    if target is None:
        raise click.MissingParameter(
            param_hint=f"'TARGET' (deployed flows: {_list_available_flows(ctx)})", param_type="argument"
        )
    runner = KubeRunner(ctx)
    runner.check_readonly("delete")

    result = runner.kubectl("delete", "asyncactor", "-l", f"asya.sh/flow={target.name}")
    if result.returncode != 0:
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


def _color_for(actor: str, actor_colors: dict[str, str]) -> str:
    """Get or assign a color for an actor name. Deterministic across runs."""
    if actor not in actor_colors:
        # FNV-1a hash for deterministic, stable color assignment
        h = 0x811C9DC5
        for b in actor.encode():
            h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
        actor_colors[actor] = _ACTOR_COLORS[h % len(_ACTOR_COLORS)]
    return actor_colors[actor]


def _pod_prefix_to_deploy(prefix: str) -> str:
    """Extract deployment name from kubectl --prefix pod name.

    kubectl --prefix outputs: [pod/start-text-flow-6f7f7f7579-lzlfw/asya-runtime]
    Deployment name is everything before the last two hash segments.
    """
    # Remove pod/ prefix and container suffix
    parts = prefix.strip("[]").split("/")
    if len(parts) >= 2:
        pod_name = parts[1]
    else:
        pod_name = parts[0]

    # Strip replicaset hash + pod hash (last two -segments)
    segments = pod_name.rsplit("-", 2)
    if len(segments) >= 3:
        return segments[0]
    return pod_name


def _format_log_line(
    line: str,
    actor_colors: dict[str, str],
    max_prefix_len: int,
    show_container: bool,
) -> str | None:
    """Parse kubectl --prefix log line, format docker-compose style with colored padded name."""
    if not line.startswith("["):
        return line

    try:
        bracket_end = line.index("]") + 1
    except ValueError:
        return line

    prefix_str = line[:bracket_end]
    text = line[bracket_end:].lstrip()
    deploy_name = _pod_prefix_to_deploy(prefix_str)
    color = _color_for(deploy_name, actor_colors)
    padded = deploy_name.ljust(max_prefix_len)  # pad short names, overfill long ones

    if show_container:
        container_name = prefix_str.strip("[]").split("/")[-1] if "/" in prefix_str else ""
        return f"{color}{padded}|{container_name}{_RESET} | {text}"
    return f"{color}{padded}{_RESET} | {text}"


def _list_available_flows(ctx: str | None) -> str:
    """Print available flow names from deployed AsyncActors."""
    runner = KubeRunner(ctx)
    result = runner.kubectl(
        "get",
        "asyncactor",
        "-o",
        "jsonpath={.items[*].metadata.labels.asya\\.sh/flow}",
        quiet=True,
        capture_output=True,
        text=True,
    )
    flows = sorted(set(result.stdout.split())) if result.returncode == 0 and result.stdout.strip() else []
    return repr(flows)


def _stream_colored_logs(
    runner: KubeRunner,
    flow_name: str,
    containers: list[str],
    follow: bool,
    tail: int | None,
    max_width: int = 20,
) -> None:
    """Stream logs with colored actor-name prefixes (docker-compose style).

    Uses single kubectl logs command with label selector and --all-pods.
    kubectl handles pod discovery, reconnection, and multiplexing.
    """
    import signal

    # Pre-discover actors to compute padding and assign colors
    result = runner.kubectl(
        "get",
        "asyncactor",
        "-l",
        f"asya.sh/flow={flow_name}",
        "-o",
        "jsonpath={.items[*].metadata.name}",
        quiet=True,
        capture_output=True,
        text=True,
    )
    actors = result.stdout.strip().split() if result.returncode == 0 and result.stdout.strip() else []
    actor_colors: dict[str, str] = {}
    max_name_len = max_width
    for a in sorted(actors):
        _color_for(a, actor_colors)

    show_container = len(containers) > 1
    ctx_args = ["--context", runner.kube_context] if runner.kube_context else []
    ns_args = ["-n", runner.namespace] if runner.namespace else []
    tail_arg = str(tail if tail is not None else 100)

    procs: list[subprocess.Popen] = []

    for container in containers:
        cmd = [
            "kubectl",
            *ctx_args,
            "logs",
            *ns_args,
            "-l",
            f"asya.sh/flow={flow_name}",
            "--all-pods",
            "--prefix",
            "--max-log-requests=20",
            "-c",
            container,
            "--tail",
            tail_arg,
        ]
        if follow:
            cmd.append("-f")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)  # nosec B603, B607  # nosemgrep
        procs.append(proc)

    def _cleanup(signum=None, frame=None):
        for p in procs:
            p.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    try:
        proc = procs[0]
        if proc.stdout is None:
            return
        first_line = proc.stdout.readline()
        if not first_line:
            # No stdout — check stderr for errors
            if proc.stderr is None:
                return
            err = proc.stderr.read().decode("utf-8", errors="replace").strip()
            if "unknown flag" in err and "--all-pods" in err:
                click.echo("[-] Your kubectl does not support --all-pods (requires >=1.28).", err=True)
                click.echo("[-] Upgrade kubectl: https://kubernetes.io/docs/tasks/tools/", err=True)
                sys.exit(1)
            if "too many open files" in err:
                click.echo("[-] Too many open files for kubectl -f. Fix with:", err=True)
                click.echo("    sudo sysctl fs.inotify.max_user_watches=524288", err=True)
                click.echo("    sudo sysctl fs.inotify.max_user_instances=1024", err=True)
            elif err:
                click.echo(f"[-] {err}", err=True)
            sys.exit(1)

        for raw_line in itertools.chain([first_line], proc.stdout):
            line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
            if "too many open files" in line:
                click.echo("[-] Too many open files for kubectl -f. Fix with:", err=True)
                click.echo("    sudo sysctl fs.inotify.max_user_watches=524288", err=True)
                click.echo("    sudo sysctl fs.inotify.max_user_instances=1024", err=True)
                break
            formatted = _format_log_line(line, actor_colors, max_name_len, show_container)
            if formatted is not None:
                click.echo(formatted)
    except KeyboardInterrupt:
        pass
    finally:
        _cleanup()


@click.command()
@click.argument("target", type=ASYA_REF, required=False, default=None)
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
@click.option("--width", "-w", type=int, default=20, help="Min actor name column width for padding (default: 20)")
def logs(
    target: AsyaRef | None, ctx: str, follow: bool, tail: int | None, containers: tuple[str, ...], width: int
) -> None:
    """Stream logs for a deployed flow with colored actor-name prefixes.

    TARGET is the flow name. Shows logs from all pods matching asya.sh/flow label.
    Output is styled like docker-compose, with each actor in a different color.

    \b
    Examples:
      asya k logs text-flow              # runtime logs from all actors
      asya k logs text-flow -f           # follow mode
      asya k logs text-flow -c asya-runtime -c asya-sidecar  # both containers
    """
    if target is None:
        raise click.MissingParameter(
            param_hint=f"'TARGET' (detected flows: {_list_available_flows(ctx)})", param_type="argument"
        )

    if not containers:
        containers = ("asya-runtime",)

    # Follow mode: show only new logs (no history dump)
    if follow and tail is None:
        tail = 0

    runner = KubeRunner(ctx)
    _stream_colored_logs(runner, target.name, list(containers), follow, tail, max_width=width)


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


def _fetch_api_key(runner: KubeRunner, key_name: str) -> str | None:
    """Fetch an API key from the asya-gateway-auth K8s secret."""
    import base64
    import json as _json

    result = runner.kubectl(
        "get",
        "secret",
        "asya-gateway-auth",
        "-o",
        "json",
        quiet=True,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        data = _json.loads(result.stdout).get("data", {})
        encoded = data.get(key_name)
        if not encoded:
            return None
        return base64.b64decode(encoded).decode()
    except Exception:
        return None


def _find_svc(label: str, namespaces: list[str]) -> tuple[str, str] | None:
    """Find a K8s service by label across namespaces. Returns (ns, svc_name)."""
    for ns in namespaces:
        result = subprocess.run(  # nosec B603, B607  # nosemgrep
            ["kubectl", "-n", ns, "get", "svc", "-l", label, "-o", "jsonpath={.items[0].metadata.name}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return (ns, result.stdout.strip())
    return None


def _print_port_forward_hint(url: str, ctx_config: dict | None) -> None:
    """Print kubectl port-forward commands discovered from cluster services."""
    from urllib.parse import urlparse

    cfg = ctx_config or {}
    actor_ns = cfg.get("namespace", "asya-demo")
    search_ns = list({actor_ns, "monitoring", "asya-system", "default"})
    gw_port = urlparse(url).port or 80

    click.echo("[.] Run in a separate terminal:", err=True)

    gw = _find_svc("app.kubernetes.io/name=asya-gateway,app.kubernetes.io/component=a2a", [actor_ns, "asya-system"])
    gw_svc = f"-n {gw[0]} svc/{gw[1]}" if gw else f"-n {actor_ns} svc/asya-gateway-a2a"
    click.echo(
        f"    kubectl port-forward {gw_svc} {gw_port}:8083  # required (A2A; use svc/asya-gateway-mcp {gw_port}:8082 for --mcp)",
        err=True,
    )

    for key, label, default_port, comment in [
        ("tempo_url", "app.kubernetes.io/name=tempo", 3200, "for --trace"),
        ("grafana_url", "app.kubernetes.io/name=grafana", 3000, "for dashboards"),
    ]:
        svc_url = cfg.get(key, "")
        if not svc_url:
            continue
        local_port = urlparse(str(svc_url)).port or default_port
        found = _find_svc(label, search_ns)
        if found:
            svc_port = 80 if "grafana" in label else default_port
            click.echo(
                f"    kubectl port-forward -n {found[0]} svc/{found[1]} {local_port}:{svc_port}  # optional, {comment}",
                err=True,
            )
        else:
            click.echo(f"    # {comment}: service with label '{label}' not found in {search_ns}", err=True)


def _fetch_artifacts(url: str, task_id: str, api_key: str | None) -> list:
    """Fetch the final task result via tasks/get and return its artifacts."""
    import json as _json
    import urllib.request

    base = url.rstrip("/").replace("/mcp", "").replace("/a2a", "")
    a2a_url = f"{base}/a2a/"
    req_body = {"jsonrpc": "2.0", "id": "fetch", "method": "tasks/get", "params": {"id": task_id}}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    try:
        req = urllib.request.Request(a2a_url, data=_json.dumps(req_body).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310  # nosemgrep
            body = _json.loads(resp.read())
        return body.get("result", {}).get("artifacts", [])
    except Exception:
        return []


def _colorize_json(obj: object, indent: int = 2) -> str:
    """Render JSON with ANSI-colored keys (cyan)."""
    import json as _json

    raw = _json.dumps(obj, indent=indent, ensure_ascii=False)
    cyan, reset = "\033[36m", "\033[0m"
    lines = []
    for line in raw.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith('"') and '":' in stripped:
            colon_pos = line.index('":')
            lines.append(f"{cyan}{line[: colon_pos + 1]}{reset}{line[colon_pos + 1 :]}")
        else:
            lines.append(line)
    return "\n".join(lines)


def _print_result(artifacts: list, fallback: dict | None = None) -> None:
    """Print task result JSON to stdout with colors. All status goes to stderr.

    Extracts text parts from A2A artifact and tries to parse as JSON for
    pretty output. Falls back to raw artifact if not JSON.
    """
    import json as _json

    if not artifacts:
        if fallback:
            click.echo(_colorize_json(fallback))
        return

    # Extract text content from artifact parts
    for artifact in artifacts:
        parts = artifact.get("parts", [])
        for part in parts:
            if part.get("kind") == "text":
                text = part["text"]
                # Try to parse as JSON for pretty printing
                try:
                    parsed = _json.loads(text)
                    click.echo(_colorize_json(parsed))
                except (_json.JSONDecodeError, ValueError):
                    click.echo(text)
                return
        # No text parts — print full artifact
        click.echo(_colorize_json(artifact))
        return


def _send_a2a(
    url: str,
    message: str,
    skill: str | None,
    api_key: str | None,
    stream: bool,
    verbose: bool = False,
    ctx_config: dict | None = None,
) -> str | None:
    """Send a message via A2A protocol."""
    import json as _json
    import urllib.request
    import uuid

    task_id = str(uuid.uuid4())
    msg_id = str(uuid.uuid4())

    params: dict[str, object] = {
        "message": {
            "messageId": msg_id,
            "role": "user",
            "parts": [{"kind": "text", "text": message}],
        },
    }
    if skill:
        params["metadata"] = {"skill": skill}

    request: dict[str, object] = {
        "jsonrpc": "2.0",
        "id": task_id,
        "method": "message/send",
        "params": params,
    }

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    if verbose:
        click.echo("  method: message/send", err=True)
        click.echo(f"  task_id: {task_id}", err=True)

    # message/send blocks until the task completes and returns the full result.
    # With --stream, show a spinner while waiting.
    import threading

    result_holder: list = []
    error_holder: list = []

    def _do_send() -> None:
        try:
            req = urllib.request.Request(
                f"{url}/a2a/",
                data=_json.dumps(request).encode(),
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=600) as resp:  # nosec B310  # nosemgrep
                result_holder.append(_json.loads(resp.read()))
        except Exception as exc:
            error_holder.append(exc)

    t = threading.Thread(target=_do_send, daemon=True)
    t.start()

    if stream:
        import itertools
        import time as _time

        spinner = itertools.cycle("|/-\\")
        while t.is_alive():
            click.echo(f"\r[{next(spinner)}] waiting for completion...", nl=False, err=True)
            _time.sleep(0.3)
        click.echo("\r" + " " * 40 + "\r", nl=False, err=True)
    else:
        click.echo("[.] waiting for response...", err=True)

    t.join()

    if error_holder:
        e = error_holder[0]
        click.echo(f"[-] Request failed: {e}", err=True)
        if "Connection refused" in str(e) or "Errno 111" in str(e):
            _print_port_forward_hint(url, ctx_config)
        sys.exit(1)

    body = result_holder[0] if result_holder else {}

    if "error" in body:
        err = body["error"]
        msg = err.get("message", str(err))
        detail = err.get("data", {}).get("error", "")
        click.echo(f"[-] {msg}: {detail}" if detail else f"[-] {msg}", err=True)
        sys.exit(1)

    result = body.get("result", {})
    state = result.get("status", {}).get("state", "unknown")
    result_id = result.get("id", "?")

    marker = "[+]" if state == "completed" else ("[-]" if state == "failed" else "[.]")
    click.echo(f"{marker} Task {result_id}: {state}", err=True)
    artifacts = result.get("artifacts", [])
    _print_result(artifacts, result)
    return result_id if result_id != "?" else None


def _truncate_actor(name: str, max_len: int = 32) -> str:
    """Truncate actor name to max_len, replacing middle with '...'."""
    if len(name) <= max_len:
        return name
    keep = (max_len - 3) // 2
    return name[:keep] + "..." + name[-(max_len - 3 - keep) :]


def _poll_task_status(api_url: str, task_id: str, api_key: str | None) -> None:
    """Poll A2A tasks/get until terminal state, showing tqdm progress bar."""
    import json as _json
    import time as _time
    import urllib.request

    try:
        from tqdm import tqdm
    except ImportError:
        tqdm = None

    base = api_url.rstrip("/").replace("/mcp", "").replace("/a2a", "")
    a2a_url = f"{base}/a2a/"

    def _a2a_get(tid: str) -> dict:
        req_body = {"jsonrpc": "2.0", "id": "poll", "method": "tasks/get", "params": {"id": tid}}
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key
        req = urllib.request.Request(a2a_url, data=_json.dumps(req_body).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310  # nosemgrep
            return _json.loads(resp.read())

    pbar = None
    if tqdm:
        pbar = tqdm(
            total=100,
            desc="Processing",
            unit="%",
            bar_format="{desc}: {percentage:3.0f}% |{bar}| {postfix}",
            file=sys.stderr,
        )
    else:
        click.echo(f"[.] waiting for {task_id}...", err=True)

    prev_msg = ""

    for poll_count in range(1, 601):
        _time.sleep(1)
        try:
            body = _a2a_get(task_id)
            task = body.get("result", {})
            state = task.get("status", {}).get("state", "")
            msg = ""
            parts = task.get("status", {}).get("message", {}).get("parts", [])
            for part in parts:
                if part.get("kind") == "text":
                    msg = part["text"]

            # Update progress bar
            if pbar:
                postfix = state
                if msg and msg != prev_msg and msg != "Task completed successfully":
                    actor = _truncate_actor(msg, 40)
                    postfix = actor
                    prev_msg = msg
                # Estimate progress: submitted=5%, working=10-90%, completed=100%
                if state == "submitted":
                    pbar.n = 5
                elif state == "working":
                    pbar.n = min(10 + poll_count * 5, 90)
                pbar.set_postfix_str(postfix)
                pbar.refresh()
            elif msg != prev_msg:
                click.echo(f"  [{_truncate_actor(msg, 40)}]", err=True)
                prev_msg = msg

            if state in ("completed", "failed"):
                if pbar:
                    pbar.n = 100
                    pbar.set_postfix_str(state)
                    pbar.refresh()
                    pbar.close()
                marker = "[+]" if state == "completed" else "[-]"
                click.echo(f"{marker} Task {task_id}: {state}", err=True)
                artifacts = task.get("artifacts", [])
                _print_result(artifacts, task)
                return
        except Exception:  # nosec B110 — polling loop, transient network errors expected
            pass

    if pbar:
        pbar.close()
    click.echo(f"[-] Timed out waiting for task {task_id}", err=True)


def _stream_task_sse(api_url: str, task_id: str, api_key: str | None) -> None:
    """Stream SSE events from GET /stream/{id}, falling back to A2A polling."""
    import json as _json
    import urllib.request

    # /stream/{id} endpoint on the API gateway
    base_url = api_url.rstrip("/").replace("/mcp", "").replace("/a2a", "")
    stream_url = f"{base_url}/stream/{task_id}"
    click.echo(f"[.] streaming {task_id}...", err=True)

    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(stream_url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=600) as resp:  # nosec B310  # nosemgrep
            for raw_line in resp:
                line = raw_line.decode("utf-8").rstrip("\n")
                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    if not data_str:
                        continue
                    try:
                        event = _json.loads(data_str)
                    except _json.JSONDecodeError:
                        click.echo(f"  {data_str}", err=True)
                        continue

                    phase = event.get("phase", event.get("status", ""))
                    actor = event.get("curr", event.get("actor", ""))
                    if actor:
                        click.echo(f"  [{actor}]", err=True)

                    if phase in ("completed", "succeeded", "failed"):
                        marker = "[+]" if phase in ("completed", "succeeded") else "[-]"
                        click.echo(f"{marker} Task {task_id}: {phase}")
                        payload = event.get("payload")
                        if payload:
                            click.echo(_json.dumps(payload, indent=2))
                        return
    except Exception:
        # SSE not available, fall back to A2A polling
        _poll_task_status(api_url, task_id, api_key)


def _send_mcp(
    url: str,
    tool_name: str,
    message: str,
    api_key: str | None,
    stream: bool,
) -> str | None:
    """Send a message via MCP protocol (initialize session + tools/call)."""
    import json as _json
    import urllib.request

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Try parsing message as JSON for tool arguments
    try:
        arguments = _json.loads(message)
        if not isinstance(arguments, dict):
            arguments = {"text": message}
    except _json.JSONDecodeError:
        arguments = {"text": message}

    # Use REST /tools/call endpoint (non-blocking, returns task_id immediately)
    click.echo(f"[.] MCP: calling tool '{tool_name}'...", err=True)
    req_body = {"name": tool_name, "arguments": arguments}
    req = urllib.request.Request(
        f"{url}/tools/call",
        data=_json.dumps(req_body).encode(),
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310  # nosemgrep
            result = _json.loads(resp.read())
    except Exception as e:
        click.echo(f"[-] MCP call failed: {e}", err=True)
        sys.exit(1)
    # Extract task_id from the tool call response for polling
    task_id = None
    for content in result.get("content", []):
        if content.get("type") == "text":
            try:
                info = _json.loads(content["text"])
                task_id = info.get("task_id")
            except (_json.JSONDecodeError, TypeError):
                pass

    if not task_id:
        click.echo("[+] MCP call completed")
        click.echo(_json.dumps(result, indent=2))
        return None

    if stream:
        _stream_task_sse(url, task_id, api_key)
    else:
        _poll_task_status(url, task_id, api_key)

    return task_id


def _show_trace(runner: KubeRunner, envelope_id: str) -> None:
    """Show trace URL and ASCII span diagram for an envelope."""
    import json as _json
    import time as _time
    import urllib.request

    ctx_cfg = runner._context_config or {}
    tempo_url = ctx_cfg.get("tempo_url")
    grafana_url = ctx_cfg.get("grafana_url")

    if grafana_url:
        traceql_query = f'{{span.asya.envelope_id="{envelope_id}"}}'
        click.echo(f"\n[.] TraceQL: {traceql_query}", err=True)

    if not tempo_url:
        if not grafana_url:
            click.echo("[.] No tempo_url or grafana_url in context config — skipping trace", err=True)
        return

    # Query Tempo via TraceQL for spans matching this envelope ID
    click.echo(f"[.] Querying traces for {envelope_id}...", err=True)

    import urllib.parse

    traceql = f'{{span.asya.envelope_id="{envelope_id}"}}'
    search_url = f"{tempo_url}/api/search?q={urllib.parse.quote(traceql)}&limit=10"

    data: dict = {"traces": []}
    for attempt in range(10):
        _time.sleep(3)  # wait for traces to flush to Tempo
        try:
            with urllib.request.urlopen(search_url, timeout=10) as resp:  # nosec B310  # nosemgrep
                data = _json.loads(resp.read())
            n = len(data.get("traces", []))
            if n:
                click.echo(f"[.] Found {n} trace(s)", err=True)
                break
            if attempt >= 3:
                click.echo(f"[.] No traces yet (attempt {attempt + 1}/10)...", err=True)
        except Exception as e:
            click.echo(f"[!] Tempo query failed: {e}", err=True)
            if attempt >= 5:
                click.echo("[!] Giving up. Try manually:", err=True)
                click.echo(f"    curl '{search_url}'", err=True)
                return

    if not data.get("traces"):
        click.echo("[.] No traces found. Try manually:", err=True)
        click.echo(f"    curl '{search_url}'", err=True)
        return

    for trace_info in data.get("traces", []):
        trace_id = trace_info.get("traceID", "")
        try:
            trace_url = f"{tempo_url}/api/traces/{trace_id}"
            with urllib.request.urlopen(trace_url, timeout=10) as resp:  # nosec B310  # nosemgrep
                trace_data = _json.loads(resp.read())
        except Exception:  # nosec B112 — skip traces that fail to fetch
            continue

        # Collect spans
        spans = []
        for batch in trace_data.get("batches", []):
            res_attrs = batch.get("resource", {}).get("attributes", [])
            svc = next((a["value"].get("stringValue", "") for a in res_attrs if a.get("key") == "service.name"), "?")
            for scope in batch.get("scopeSpans", []):
                for span in scope.get("spans", []):
                    attrs = {
                        a["key"]: a.get("value", {}).get("stringValue", a.get("value", {}).get("intValue", ""))
                        for a in span.get("attributes", [])
                    }
                    if attrs.get("asya.envelope_id") == envelope_id:
                        start_ns = int(span.get("startTimeUnixNano", 0))
                        end_ns = int(span.get("endTimeUnixNano", 0))
                        spans.append(
                            {
                                "service": svc,
                                "name": span.get("name", "?"),
                                "start": start_ns,
                                "end": end_ns,
                                "dur_ms": (end_ns - start_ns) / 1e6,
                            }
                        )

        if not spans:
            continue

        # Render ASCII timeline with colored actor names
        spans.sort(key=lambda s: s["start"])
        min_start = min(s["start"] for s in spans)
        max_end = max(s["end"] for s in spans)
        total_ns = max_end - min_start or 1

        # Compute column width from longest actor name
        actor_colors: dict[str, str] = {}
        max_actor_len = max(len(s["service"]) for s in spans)

        click.echo(f"\n  Trace: {trace_id}", err=True)
        if grafana_url:
            click.echo(
                f"  Grafana: {grafana_url}/explore?left=%5B%22now-1h%22,%22now%22,%22Tempo%22,%7B%22query%22:%22{trace_id}%22%7D%5D",
                err=True,
            )
        click.echo(f"  Total: {total_ns / 1e6:.0f}ms", err=True)
        click.echo(f"  {'Actor':<{max_actor_len}} {'Duration':>8}  Timeline", err=True)
        click.echo(f"  {'─' * max_actor_len} {'─' * 8}  {'─' * 40}", err=True)

        bar_width = 40
        for s in spans:
            offset = int((s["start"] - min_start) / total_ns * bar_width)
            width = max(1, int(s["dur_ms"] / (total_ns / 1e6) * bar_width))
            color = _color_for(s["service"], actor_colors)
            bar = " " * offset + "█" * width
            click.echo(
                f"  {color}{s['service']:<{max_actor_len}}{_RESET} {s['dur_ms']:>7.0f}ms  {color}{bar}{_RESET}",
                err=True,
            )

        click.echo("", err=True)
        return  # show first matching trace

    click.echo("[.] No traces found for this envelope (traces may take a few seconds to flush)", err=True)


@click.command()
@click.argument("target", type=ASYA_REF, required=False, default=None)
@click.argument("message", required=False, default=None)
@click.option("--context", "ctx", default=None, help="K8s context from .asya/config.yaml")
@click.option("--url", default=None, help="Gateway URL (default: auto-detect via port-forward)")
@click.option("--skill", default=None, help="Skill hint when multiple flows are registered")
@click.option("--a2a", "use_a2a", is_flag=True, default=False, help="Use A2A protocol (default)")
@click.option("--mcp", "use_mcp", is_flag=True, default=False, help="Use MCP protocol")
@click.option("--stream", is_flag=True, help="Stream events (A2A subscribe)")
@click.option("--show-traces", "trace", is_flag=True, help="Show Grafana trace link and ASCII spans after completion")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output (show method, task_id, raw events)")
@click.option("--api-key", default=None, help="API key (default: auto-fetch from asya-gateway-auth secret)")
def send(
    target: AsyaRef | None,
    message: str | None,
    ctx: str,
    url: str | None,
    skill: str | None,
    use_a2a: bool,
    use_mcp: bool,
    stream: bool,
    trace: bool,
    verbose: bool,
    api_key: str | None,
) -> None:
    """Send a message to a deployed flow.

    TARGET is the flow name. MESSAGE is the text payload.
    Auto-fetches API key from the asya-gateway-auth K8s secret.

    \b
    Examples:
      asya k send text-flow "Analyze this text"
      asya k send text-flow "Analyze this text" --mcp
      asya k send greet-flow "Hello" --skill greet-flow
      asya k send text-flow '{"key":"val"}' --mcp
    """
    if target is None:
        raise click.MissingParameter(
            param_hint=f"'TARGET' (deployed flows: {_list_available_flows(ctx)})", param_type="argument"
        )
    if message is None:
        raise click.MissingParameter(param_hint="'MESSAGE'", param_type="argument")

    runner = KubeRunner(ctx)
    url = _resolve_gateway_url(runner, url)

    # Auto-fetch API key from K8s secret
    if api_key is None:
        if use_mcp:
            api_key = _fetch_api_key(runner, "mcp-api-key")
        else:
            api_key = _fetch_api_key(runner, "a2a-api-key")

    # Default to A2A (--a2a is explicit but also the default when --mcp is not set)
    task_id = None
    if use_a2a or not use_mcp:
        click.echo(f"[.] {target.name} -> {url}/a2a/", err=True)
        task_id = _send_a2a(
            url, message, skill or target.name, api_key, stream, verbose=verbose, ctx_config=runner._context_config
        )
    else:
        click.echo(f"[.] {target.name} -> {url}/mcp", err=True)
        task_id = _send_mcp(url, target.name, message, api_key, stream)

    if trace and task_id:
        _show_trace(runner, task_id)


def _resolve_gateway_url(runner: KubeRunner, url_override: str | None) -> str:
    """Resolve gateway URL: --url > ASYA_GATEWAY_URL > config > auto-detect."""
    import os
    import socket

    # 1. Explicit --url flag
    if url_override:
        return url_override.rstrip("/")

    # 2. Environment variable
    env_url = os.environ.get("ASYA_GATEWAY_URL")
    if env_url:
        return env_url.rstrip("/")

    # 3. Context config (.asya/config.yaml contexts.<ctx>.gateway_url)
    if runner._context_config:
        config_url = runner._context_config.get("gateway_url")
        if config_url:
            return str(config_url).rstrip("/")

    # 4. Auto-detect from localhost
    for port in (18080, 8080, 8888, 80):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return f"http://127.0.0.1:{port}"
        except OSError:
            continue

    click.echo(
        "[-] No gateway URL configured. Options:\n"
        "    1. Set in .asya/config.yaml: contexts.dev.gateway_url: http://...\n"
        "    2. Set env: export ASYA_GATEWAY_URL=http://...\n"
        "    3. Use flag: --url http://...\n"
        "    4. Start port-forward: kubectl port-forward -n <ns> svc/asya-gateway-a2a 18080:8083",
        err=True,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# asya k (group)
# ---------------------------------------------------------------------------


@click.group("k")
def k() -> None:
    """Kubernetes commands (apply, delete, status, logs, send, edit, context)."""


_COLUMN_MAP = {
    "ACTOR": ".metadata.name",
    "FLOW": ".metadata.labels.asya\\.sh/flow",
    "STATUS": ".status.phase",
    "CURRENT": ".status.infrastructure.workload.readyReplicas",
    "DESIRED": ".status.infrastructure.workload.replicas",
    "MIN": ".spec.scaling.minReplicaCount",
    "MAX": ".spec.scaling.maxReplicaCount",
    "FLAVORS": ".spec.flavors[*]",
    "IMAGE": ".spec.image",
    "HANDLER": ".spec.handler",
}

_DEFAULT_COLUMNS = ["ACTOR", "FLOW", "STATUS", "CURRENT", "DESIRED", "MIN", "MAX", "FLAVORS"]


def _build_columns_spec(names: list[str]) -> str:
    """Build kubectl custom-columns spec from column names."""
    parts = []
    for name in names:
        key = name.upper()
        if key in _COLUMN_MAP:
            parts.append(f"{key}:{_COLUMN_MAP[key]}")
        elif ":" in name:
            parts.append(name)
        else:
            click.echo(f"[-] Unknown column '{name}'. Available: {', '.join(sorted(_COLUMN_MAP))}", err=True)
            sys.exit(1)
    return ",".join(parts)


@click.command("status")
@click.argument("target", type=ASYA_REF, required=False, default=None)
@click.option("--context", "ctx", default=None, help="K8s context from .asya/config.yaml")
@click.option("-o", "output", default=None, help="Output format (json, yaml, name, wide)")
@click.option("--columns", default=None, help="Column names to show (e.g. actor,min,max,status)")
@click.option("--no-headers", is_flag=True, help="Hide column headers")
def k_status(target: AsyaRef | None, ctx: str, output: str | None, columns: str | None, no_headers: bool) -> None:
    """Show status of deployed actors.

    \b
    Examples:
      asya k status                            # all flows
      asya k status text-improver              # one flow
      asya k status text-improver -o name      # pipeable names
      asya k status text-improver -o json      # full JSON
      asya k status text-improver -c actor,min,max
    """
    runner = KubeRunner(ctx)

    args = ["get", "asyncactor"]
    if target:
        args.extend(["-l", f"asya.sh/flow={target.name}"])

    if output:
        args.extend(["-o", output])
    else:
        col_names = [c.strip() for c in columns.split(",")] if columns else _DEFAULT_COLUMNS
        args.extend(["-o", f"custom-columns={_build_columns_spec(col_names)}"])

    if no_headers:
        args.append("--no-headers")

    result = runner.kubectl(*args)
    sys.exit(result.returncode)


k.add_command(apply)
k.add_command(delete)
k.add_command(k_status)
k.add_command(logs)
k.add_command(send)
k.add_command(edit)
k.add_command(context_group)
