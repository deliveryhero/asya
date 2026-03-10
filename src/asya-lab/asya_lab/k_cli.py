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

    def __init__(self, ctx: str | None = None) -> None:
        asya_dir = find_asya_dir(Path.cwd())
        if asya_dir is None:
            click.echo("[-] No .asya/ directory found. Run 'asya init' first.", err=True)
            sys.exit(1)

        self.project = AsyaProject.from_dir(asya_dir.parent)
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
        manifests_dir = self.project.resolve_path("compiler.manifests") / target
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
    def run_cmd(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        """Run a shell command, printing it first with + prefix."""
        click.echo(f"+ {' '.join(cmd)}", err=True)
        return subprocess.run(cmd, check=False, **kwargs)  # nosec B603

    def kubectl(self, *args: str, **kwargs) -> subprocess.CompletedProcess:
        """Run kubectl with automatic namespace injection."""
        cmd = ["kubectl", *args]
        if self.namespace:
            cmd.extend(["-n", self.namespace])
        return self.run_cmd(cmd, **kwargs)

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


@click.command()
@click.argument("target", type=ASYA_REF)
@click.option("--context", "ctx", default=None, help="K8s context from .asya/config.yaml")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def apply(target: AsyaRef, ctx: str, verbose: bool) -> None:
    """Apply compiled manifests to a Kubernetes cluster.

    TARGET is a flow name (kebab-case, snake_case, or path/to/flow.py).

    Uses kustomize build piped to kubectl apply --server-side with
    per-flow field manager for safe, idempotent deploys.
    """
    runner = KubeRunner(ctx)
    runner.check_readonly("apply")

    manifests_dir = runner.find_manifests(target.name)
    overlay = runner.resolve_overlay(manifests_dir)

    runner.kustomize_apply(overlay, field_manager=f"asya-flow-{target.name}")


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


@click.command()
@click.argument("target", type=ASYA_REF)
@click.option("--context", "ctx", default=None, help="K8s context from .asya/config.yaml")
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
@click.option("--tail", type=int, default=None, help="Number of lines to show from end")
@click.option("--container", "-c", default="asya-runtime", help="Container name (default: asya-runtime)")
def logs(target: AsyaRef, ctx: str, follow: bool, tail: int | None, container: str) -> None:
    """Stream logs for a deployed flow.

    TARGET is the flow name. Shows logs from all pods matching asya.sh/flow label.
    """
    runner = KubeRunner(ctx)

    extra_args: list[str] = []
    if follow:
        extra_args.append("-f")
    if tail is not None:
        extra_args.extend(["--tail", str(tail)])

    result = runner.kubectl(
        "logs",
        "-l",
        f"asya.sh/flow={target.name}",
        "-c",
        container,
        "--prefix",
        *extra_args,
    )
    if result.returncode != 0:
        sys.exit(result.returncode)


# ---------------------------------------------------------------------------
# asya k edit
# ---------------------------------------------------------------------------


_PATCH_TEMPLATE = """\
# Kustomize patch for {actor_name}
# Uncomment and modify fields you want to override.
#
# This file is applied on top of the compiler-generated base/ manifest.
# See base/asyncactor-{actor_name}.yaml for all available fields.
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
    """List configured contexts."""
    asya_dir = find_asya_dir(Path.cwd())
    if asya_dir is None:
        click.echo("[-] No .asya/ directory found. Run 'asya init' first.", err=True)
        sys.exit(1)

    try:
        project = AsyaProject.from_dir(asya_dir.parent)
    except (FileNotFoundError, KeyError) as e:
        click.echo(f"[-] Failed to load config: {e}", err=True)
        sys.exit(1)

    contexts = project.cfg.get("contexts")
    if not contexts:
        click.echo("No contexts configured in .asya/config.yaml")
        return

    default_ctx = project.cfg.get("default_context")

    for name in contexts:
        ctx = contexts[name]
        marker = "*" if name == default_ctx else " "
        kubecontext = ctx.get("kubecontext", "")
        namespace = ctx.get("namespace", "")
        readonly = " (readonly)" if ctx.get("readonly") else ""
        click.echo(f"  {marker} {name:<20} kubecontext={kubecontext:<30} namespace={namespace}{readonly}")


@context_group.command("use")
@click.argument("name")
def context_use(name: str) -> None:
    """Set the default context.

    Updates default_context in .asya/config.yaml.
    """
    asya_dir = find_asya_dir(Path.cwd())
    if asya_dir is None:
        click.echo("[-] No .asya/ directory found. Run 'asya init' first.", err=True)
        sys.exit(1)

    config_path = asya_dir / "config.yaml"
    if not config_path.exists():
        click.echo(f"[-] Config not found: {config_path}", err=True)
        sys.exit(1)

    text = config_path.read_text()
    config = yaml.safe_load(text) or {}

    contexts = config.get("contexts", {})
    if name not in contexts:
        click.echo(f"[-] Context '{name}' not found", err=True)
        available = list(contexts.keys())
        if available:
            click.echo(f"[-] Available: {', '.join(available)}", err=True)
        sys.exit(1)

    # Targeted replacement to preserve YAML comments and formatting
    pattern = re.compile(r"^(?!#)(\s*)default_context:.*$", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(rf"\1default_context: {name}", text)
    else:
        text = text.rstrip() + f"\ndefault_context: {name}\n"
    config_path.write_text(text)
    click.echo(f"[+] Default context set to '{name}'")


# ---------------------------------------------------------------------------
# asya k (group)
# ---------------------------------------------------------------------------


@click.group("k")
def k() -> None:
    """Kubernetes commands (apply, delete, status, logs, edit, context)."""


k.add_command(apply)
k.add_command(delete)
k.add_command(k_status)
k.add_command(logs)
k.add_command(edit)
k.add_command(context_group)
