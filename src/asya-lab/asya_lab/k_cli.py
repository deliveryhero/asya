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

    # Only works with projected volumes (requires chart change)
    if "projected" not in volumes[vol_idx]:
        return

    sources = volumes[vol_idx]["projected"].get("sources", [])
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

    # Rollout restart to pick up ConfigMap changes (routers, adapters)
    result = runner.kubectl(
        "rollout", "restart", "deployment",
        "-l", f"asya.sh/flow={target.name}",
        quiet=True,
    )
    if result.returncode == 0:
        click.echo(f"[.] Rolling restart: {target.name}")


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
@click.argument("target", type=ASYA_REF, required=False, default=None)
@click.option("--context", "ctx", default=None, help="K8s context from .asya/config.yaml")
def k_status(target: AsyaRef | None, ctx: str) -> None:
    """Show live cluster status for deployed flows.

    TARGET is an optional flow name. Without it, shows all flows.

    \b
    Examples:
      asya k status                  # all flows
      asya k status text-flow        # one flow
    """
    import json as _json

    runner = KubeRunner(ctx)
    label = f"asya.sh/flow={target.name}" if target else "asya.sh/flow"

    # Get actors
    result = runner.kubectl(
        "get", "asyncactor", "-l", label, "-o", "json",
        quiet=True, capture_output=True, text=True,
    )
    if result.returncode != 0:
        if target:
            click.echo(f"[-] No actors found for flow '{target.name}'", err=True)
        else:
            click.echo("[-] No actors found", err=True)
        sys.exit(result.returncode)

    actors_data = _json.loads(result.stdout)
    actors = actors_data.get("items", [])
    if not actors:
        click.echo("[.] No actors deployed")
        return

    # Get pods
    pod_result = runner.kubectl(
        "get", "pods", "-l", label, "-o", "json",
        quiet=True, capture_output=True, text=True,
    )
    pods_by_actor: dict[str, list[dict]] = {}
    if pod_result.returncode == 0:
        for pod in _json.loads(pod_result.stdout).get("items", []):
            actor_name = pod["metadata"].get("labels", {}).get("app.kubernetes.io/name", "?")
            pods_by_actor.setdefault(actor_name, []).append(pod)

    # Group by flow
    flows: dict[str, list[dict]] = {}
    for actor in actors:
        flow = actor["metadata"].get("labels", {}).get("asya.sh/flow", "?")
        flows.setdefault(flow, []).append(actor)

    for flow_name, flow_actors in sorted(flows.items()):
        click.echo(f"Flow: {flow_name}")
        for actor in flow_actors:
            name = actor["metadata"]["name"]
            spec = actor.get("spec", {})
            status_phase = actor.get("status", {}).get("phase", "?")

            # Derive actual status from pods (XRD status is unreliable — debt/mqd9)
            actor_pods = pods_by_actor.get(name, [])
            if actor_pods:
                running = sum(1 for p in actor_pods if p["status"].get("phase") == "Running")
                ready = sum(
                    1 for p in actor_pods
                    if all(c.get("ready") for c in p["status"].get("containerStatuses", []))
                )
                total = len(actor_pods)
                pod_status = f"{ready}/{total} ready"
            else:
                running = ready = total = 0
                scaling = spec.get("scaling", {})
                if scaling.get("enabled") and scaling.get("minReplicaCount", 0) == 0:
                    pod_status = "scaled to 0 (KEDA)"
                else:
                    pod_status = "no pods"

            # Role indicator
            role = actor["metadata"].get("labels", {}).get("asya.sh/role", "")
            role_marker = f" ({role})" if role else ""

            # Handler
            handler = spec.get("handler", "?")

            click.echo(f"  {name}{role_marker}: {pod_status}, handler={handler}")

        click.echo()


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


def _get_flow_deployments(runner: KubeRunner, flow_name: str) -> list[str]:
    """Get actor names for a flow from AsyncActor CRDs.

    Queries AsyncActors (always have the flow label) rather than
    Deployments (Crossplane-created, may lack the label).
    """
    import json as _json

    result = runner.kubectl(
        "get", "asyncactor", "-l", f"asya.sh/flow={flow_name}",
        "-o", "jsonpath={.items[*].metadata.name}",
        quiet=True, capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    return result.stdout.strip().split()


def _color_for(actor: str, actor_colors: dict[str, str]) -> str:
    """Get or assign a color for an actor name."""
    if actor not in actor_colors:
        idx = len(actor_colors) % len(_ACTOR_COLORS)
        actor_colors[actor] = _ACTOR_COLORS[idx]
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
    """Parse kubectl --prefix log line and format with colored actor name."""
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
    padded = deploy_name.ljust(max_prefix_len)

    if show_container:
        container_name = prefix_str.strip("[]").split("/")[-1] if "/" in prefix_str else ""
        return f"{color}{padded}|{container_name}{_RESET} | {text}"
    return f"{color}{padded}{_RESET} | {text}"


def _stream_colored_logs(
    runner: KubeRunner,
    flow_name: str,
    containers: list[str],
    follow: bool,
    tail: int | None,
) -> None:
    """Stream logs with colored actor-name prefixes.

    In follow mode, watches for new pods and attaches log streams
    as actors scale up. Uses kubectl logs per-pod with --prefix.
    """
    import selectors
    import signal
    import threading
    import time

    actors = _get_flow_deployments(runner, flow_name)
    if not actors:
        click.echo("[-] No actors found for flow", err=True)
        sys.exit(1)

    actor_colors: dict[str, str] = {}
    max_prefix_len = max(len(a) for a in actors)
    for a in sorted(actors):
        _color_for(a, actor_colors)

    show_container = len(containers) > 1
    ns_args = ["-n", runner.namespace] if runner.namespace else []
    tail_arg = str(tail if tail is not None else 100)

    # Track attached pods to avoid duplicates
    attached_pods: set[str] = set()
    procs: list[subprocess.Popen] = []
    sel = selectors.DefaultSelector()
    lock = threading.Lock()

    def _attach_pod(pod_name: str) -> None:
        """Attach log streams for a pod."""
        with lock:
            if pod_name in attached_pods:
                return
            attached_pods.add(pod_name)

        for container in containers:
            cmd = ["kubectl", "logs", *ns_args, pod_name, "-c", container, "--prefix", "--tail", tail_arg]
            if follow:
                cmd.append("-f")
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)  # nosec B603, B607
            with lock:
                procs.append(proc)
                assert proc.stdout is not None
                sel.register(proc.stdout, selectors.EVENT_READ)

    def _discover_pods() -> None:
        """Discover and attach to existing pods."""
        import json as _json

        result = runner.kubectl(
            "get", "pods", "-l", f"asya.sh/flow={flow_name}",
            "--field-selector=status.phase=Running",
            "-o", "jsonpath={.items[*].metadata.name}",
            quiet=True, capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            for pod_name in result.stdout.strip().split():
                _attach_pod(pod_name)

    def _watch_pods() -> None:
        """Watch for new pods in background (follow mode only)."""
        import json as _json

        while True:
            time.sleep(3)  # poll for new pods
            _discover_pods()

    _discover_pods()

    if follow and not attached_pods:
        click.echo("[.] No running pods. Waiting for scale-up...", err=True)
        while not attached_pods:
            import time

            time.sleep(3)
            _discover_pods()
        click.echo(f"[+] Attached to {len(attached_pods)} pod(s)", err=True)

    if not attached_pods:
        click.echo("[-] No running pods found for flow", err=True)
        sys.exit(1)

    # Start pod watcher thread in follow mode
    if follow:
        watcher = threading.Thread(target=_watch_pods, daemon=True)
        watcher.start()

    def _cleanup(signum=None, frame=None):
        for p in procs:
            p.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    try:
        while True:
            with lock:
                events = sel.select(timeout=1.0)
            for key, _mask in events:
                fobj = key.fileobj
                assert hasattr(fobj, "readline")
                raw_line = fobj.readline()
                if not raw_line:
                    with lock:
                        sel.unregister(fobj)
                    if not follow:
                        continue
                    continue

                line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                formatted = _format_log_line(line, actor_colors, max_prefix_len, show_container)
                if formatted is not None:
                    click.echo(formatted)
    except KeyboardInterrupt:
        pass
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

    # Follow mode: show only new logs (no history dump)
    if follow and tail is None:
        tail = 0

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


def _fetch_api_key(runner: KubeRunner, key_name: str) -> str | None:
    """Fetch an API key from the asya-gateway-auth K8s secret."""
    import base64
    import json as _json

    result = runner.kubectl(
        "get", "secret", "asya-gateway-auth",
        "-o", "json",
        quiet=True, capture_output=True, text=True,
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


def _send_a2a(
    url: str,
    message: str,
    skill: str | None,
    api_key: str | None,
    stream: bool,
) -> None:
    """Send a message via A2A protocol."""
    import json as _json
    import uuid
    import urllib.request

    task_id = str(uuid.uuid4())
    msg_id = str(uuid.uuid4())

    request = {
        "jsonrpc": "2.0",
        "id": task_id,
        "method": "message/send",
        "params": {
            "message": {
                "messageId": msg_id,
                "role": "user",
                "parts": [{"kind": "text", "text": message}],
            },
        },
    }
    if skill:
        request["params"]["metadata"] = {"skill": skill}

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    try:
        req = urllib.request.Request(
            f"{url}/a2a/",
            data=_json.dumps(request).encode(),
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=600) as resp:  # nosec B310
            body = _json.loads(resp.read())
    except Exception as e:
        click.echo(f"[-] Request failed: {e}", err=True)
        sys.exit(1)

    if "error" in body:
        err = body["error"]
        msg = err.get("message", str(err))
        detail = err.get("data", {}).get("error", "")
        click.echo(f"[-] {msg}: {detail}" if detail else f"[-] {msg}", err=True)
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


def _truncate_actor(name: str, max_len: int = 32) -> str:
    """Truncate actor name to max_len, replacing middle with '...'."""
    if len(name) <= max_len:
        return name
    keep = (max_len - 3) // 2
    return name[:keep] + "..." + name[-(max_len - 3 - keep):]


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
        with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
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
        click.echo(f"[.] waiting for {task_id[:12]}...", err=True)

    prev_msg = ""
    poll_count = 0

    for _ in range(600):
        _time.sleep(1)
        poll_count += 1
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
                click.echo(f"{marker} Task {task_id[:12]}: {state}")
                for part in parts:
                    if part.get("kind") == "text" and part["text"] != "Task completed successfully":
                        click.echo(part["text"])
                for artifact in task.get("artifacts", []):
                    click.echo(_json.dumps(artifact, indent=2))
                return
        except Exception:
            pass

    if pbar:
        pbar.close()
    click.echo(f"[-] Timed out waiting for task {task_id[:12]}", err=True)


def _stream_task_sse(api_url: str, task_id: str, api_key: str | None) -> None:
    """Stream SSE events from GET /stream/{id}, falling back to A2A polling."""
    import json as _json
    import urllib.request

    # /stream/{id} endpoint on the API gateway
    base_url = api_url.rstrip("/").replace("/mcp", "").replace("/a2a", "")
    stream_url = f"{base_url}/stream/{task_id}"
    click.echo(f"[.] streaming {task_id[:12]}...", err=True)

    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(stream_url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=600) as resp:  # nosec B310
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
                        click.echo(f"{marker} Task {task_id[:12]}: {phase}")
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
) -> None:
    """Send a message via MCP protocol (initialize session + tools/call)."""
    import json as _json
    import uuid
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
        with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
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
        return

    if stream:
        _stream_task_sse(url, task_id, api_key)
    else:
        _poll_task_status(url, task_id, api_key)


@click.command()
@click.argument("target", type=ASYA_REF)
@click.argument("message", required=True)
@click.option("--context", "ctx", default=None, help="K8s context from .asya/config.yaml")
@click.option("--url", default=None, help="Gateway URL (default: auto-detect via port-forward)")
@click.option("--skill", default=None, help="Skill hint when multiple flows are registered")
@click.option("--a2a", "use_a2a", is_flag=True, default=False, help="Use A2A protocol (default)")
@click.option("--mcp", "use_mcp", is_flag=True, default=False, help="Use MCP protocol")
@click.option("--stream", is_flag=True, help="Stream events (A2A subscribe)")
@click.option("--api-key", default=None, help="API key (default: auto-fetch from asya-gateway-auth secret)")
def send(
    target: AsyaRef,
    message: str,
    ctx: str,
    url: str | None,
    skill: str | None,
    use_a2a: bool,
    use_mcp: bool,
    stream: bool,
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
    runner = KubeRunner(ctx)
    url = _resolve_gateway_url(runner, url)

    # Auto-fetch API key from K8s secret
    if api_key is None:
        if use_mcp:
            api_key = _fetch_api_key(runner, "mcp-api-key")
        else:
            api_key = _fetch_api_key(runner, "a2a-api-key")

    # Default to A2A
    if not use_mcp:
        click.echo(f"[.] {target.name} -> {url}/a2a/", err=True)
        _send_a2a(url, message, skill or target.name, api_key, stream)
    else:
        click.echo(f"[.] {target.name} -> {url}/mcp", err=True)
        _send_mcp(url, target.name, message, api_key, stream)


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
        "    1. Set in .asya/config.yaml: contexts.dev.gateway: http://...\n"
        "    2. Set env: export ASYA_GATEWAY_URL=http://...\n"
        "    3. Use flag: --url http://...\n"
        "    4. Start port-forward: kubectl port-forward -n <ns> svc/asya-gateway-api 18080:80",
        err=True,
    )
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
