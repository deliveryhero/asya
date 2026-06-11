"""CLI command for patching compiled flow manifests.

Writes kustomize strategic merge patches to common/ or overlays/<ctx>/,
then validates the result with kubectl kustomize.

Three scopes:
    asya patch text-flow --actor analyze scaling.min=1
    asya patch text-flow --actor analyze env.LOG_LEVEL=DEBUG
    asya patch text-flow --gateway expose=true description="Analyze text" mcp=true
"""

from __future__ import annotations

import dataclasses
import json
import subprocess  # nosec B404
import sys
from pathlib import Path

import click
import yaml

from asya_lab.cli_types import ASYA_REF, AsyaRef
from asya_lab.config.discovery import BASE_DIR, COMMON_DIR, OVERLAYS_DIR, find_asya_dir
from asya_lab.config.project import AsyaProject
from asya_lab.gateway_register import EXPOSE_FILENAME, build_flow_expose


# -- Shorthand key mapping --------------------------------------------------

_SCALING_SHORTCUTS = {
    "scaling.min": "minReplicaCount",
    "scaling.max": "maxReplicaCount",
    "scaling.cooldown": "cooldownPeriod",
    "scaling.polling": "pollingInterval",
}


def _parse_env_entry(raw: str) -> dict | None:
    """Parse env shorthand: NAME=value | NAME=secret:name:key."""
    if "=" not in raw:
        raise click.BadParameter(f"Invalid env format: {raw!r} (expected NAME=value)")

    name, value = raw.split("=", 1)

    if value.startswith("secret:"):
        parts = value.split(":")
        if len(parts) != 3:
            raise click.BadParameter(f"Secret ref format: secret:name:key (got {value!r})")
        return {
            "name": name,
            "valueFrom": {"secretKeyRef": {"name": parts[1], "key": parts[2]}},
        }

    if value.startswith("configmap:"):
        parts = value.split(":")
        if len(parts) != 3:
            raise click.BadParameter(f"ConfigMap ref format: configmap:name:key (got {value!r})")
        return {
            "name": name,
            "valueFrom": {"configMapKeyRef": {"name": parts[1], "key": parts[2]}},
        }

    return {"name": name, "value": value}


def _parse_key_value(kv: str) -> tuple[str, str | int]:
    """Parse key=value, returning (dotted_key, value)."""
    if "=" not in kv:
        raise click.BadParameter(f"Expected key=value, got: {kv!r}")
    key, val = kv.split("=", 1)
    try:
        return key, int(val)
    except ValueError:
        return key, val


# -- Actor patch building ---------------------------------------------------


@dataclasses.dataclass
class PatchSpec:
    """Parsed patch intent from CLI arguments."""

    actor_name: str
    spec: dict = dataclasses.field(default_factory=dict)
    env_remove: list[str] = dataclasses.field(default_factory=list)

    def to_manifest(self) -> dict:
        return {
            "apiVersion": "asya.sh/v1alpha1",
            "kind": "AsyncActor",
            "metadata": {"name": self.actor_name},
            "spec": self.spec,
        }


def _build_actor_patch(actor_name: str, key_values: tuple[str, ...], raw_patch: str | None) -> PatchSpec:
    """Build a PatchSpec from CLI arguments."""
    if raw_patch:
        return PatchSpec(actor_name=actor_name, spec=json.loads(raw_patch))

    spec: dict = {}
    env_add: list[dict] = []

    for kv in key_values:
        if kv.startswith("env."):
            entry = _parse_env_entry(kv[4:])
            if entry is not None:
                env_add.append(entry)
            continue

        matched = False
        for shortcut, real_key in _SCALING_SHORTCUTS.items():
            if kv.startswith(f"{shortcut}="):
                _, val = _parse_key_value(kv)
                spec.setdefault("scaling", {})[real_key] = val
                matched = True
                break
        if matched:
            continue

        key, val = _parse_key_value(kv)
        parts = key.split(".")
        target = spec
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = val

    if env_add:
        spec["env"] = env_add

    return PatchSpec(actor_name=actor_name, spec=spec)


# -- Gateway config building ------------------------------------------------


def _build_gateway_config(
    flow_name: str,
    entrypoint: str,
    key_values: tuple[str, ...],
) -> dict | None:
    """Build the flow-exposure intent from key=value pairs.

    Returns None if expose=false (removal).
    """
    kv_dict: dict[str, str | int] = {}
    for kv in key_values:
        k, v = _parse_key_value(kv)
        kv_dict[k] = v

    # Check expose flag
    expose_val = kv_dict.pop("expose", "true")
    if str(expose_val).lower() in ("false", "0", "no"):
        return None

    description = str(kv_dict.pop("description", ""))
    has_mcp = kv_dict.pop("mcp", None) is not None
    has_a2a = kv_dict.pop("a2a", None) is not None

    if not description:
        raise click.UsageError('--gateway requires description=... (e.g. description="Analyze text")')
    if not has_mcp and not has_a2a:
        raise click.UsageError("--gateway requires at least one protocol: mcp=true and/or a2a=true")

    timeout = kv_dict.pop("timeout", None)
    tags = kv_dict.pop("tags", None)
    input_modes = kv_dict.pop("input_modes", None) or kv_dict.pop("inputModes", None)
    output_modes = kv_dict.pop("output_modes", None) or kv_dict.pop("outputModes", None)

    return build_flow_expose(
        flow_name,
        entrypoint,
        description,
        int(timeout) if timeout is not None else None,
        mcp=has_mcp,
        a2a=has_a2a,
        tags=str(tags) if tags is not None else None,
        input_modes=str(input_modes) if input_modes is not None else None,
        output_modes=str(output_modes) if output_modes is not None else None,
    )


def _find_entrypoint(base_dir: Path) -> str:
    """Scan base/ YAML files for the actor with label asya.sh/role: start."""
    for yaml_file in sorted(base_dir.glob("*.yaml")):
        if yaml_file.name == "kustomization.yaml":
            continue
        try:
            for doc in yaml.safe_load_all(yaml_file.read_text()):
                if not isinstance(doc, dict):
                    continue
                labels = doc.get("metadata", {}).get("labels", {})
                if labels.get("asya.sh/role") == "start":
                    return doc["metadata"]["name"]
        except (yaml.YAMLError, KeyError):
            continue
    click.echo("[-] No actor with label asya.sh/role=start found in base/", err=True)
    sys.exit(1)


# -- File operations ---------------------------------------------------------


def _resolve_actors(base_dir: Path) -> list[str]:
    """List all actor names from compiled base manifests."""
    actors = []
    for f in sorted(base_dir.glob("asya-*.yaml")):
        try:
            doc = yaml.safe_load(f.read_text())
            if isinstance(doc, dict) and doc.get("kind") == "AsyncActor":
                actors.append(doc["metadata"]["name"])
        except (yaml.YAMLError, KeyError):
            continue
    return actors


def _resolve_actor_name(actor_ref: str, base_dir: Path) -> str:
    """Resolve user-provided actor ref to the manifest name."""
    actors = _resolve_actors(base_dir)
    k8s_name = actor_ref.replace("_", "-")
    if k8s_name in actors:
        return k8s_name
    prefixed = f"actor-{k8s_name}"
    if prefixed in actors:
        return prefixed
    start_prefixed = f"start-{k8s_name}"
    if start_prefixed in actors:
        return start_prefixed

    raise click.BadParameter(f"Actor '{actor_ref}' not found. Available: {', '.join(actors)}")


def _write_actor_patch(ps: PatchSpec, patch_dir: Path) -> Path:
    """Write or merge an actor patch into the target directory."""
    patch_dir.mkdir(parents=True, exist_ok=True)
    patch_file = patch_dir / f"patch-{ps.actor_name}.yaml"

    if patch_file.exists():
        existing = yaml.safe_load(patch_file.read_text()) or {}
        existing_spec = existing.get("spec", {})
        new_spec = ps.spec.copy()

        if ps.env_remove and "env" in existing_spec:
            existing_spec["env"] = [e for e in existing_spec["env"] if e.get("name") not in ps.env_remove]
            if not existing_spec["env"]:
                del existing_spec["env"]

        if "env" in new_spec and "env" in existing_spec:
            existing_names = {e["name"] for e in existing_spec["env"]}
            for entry in new_spec["env"]:
                if entry["name"] in existing_names:
                    existing_spec["env"] = [entry if e["name"] == entry["name"] else e for e in existing_spec["env"]]
                else:
                    existing_spec["env"].append(entry)
            del new_spec["env"]

        _deep_merge(existing_spec, new_spec)
        existing["spec"] = existing_spec
        manifest = existing
    else:
        manifest = ps.to_manifest()

    if not manifest.get("spec"):
        if patch_file.exists():
            patch_file.unlink()
        _update_kustomization(patch_dir / "kustomization.yaml", patch_file.name, add=False)
        return patch_file

    patch_file.write_text(yaml.dump(manifest, default_flow_style=False, sort_keys=False))
    return patch_file


def _deep_merge(base: dict, override: dict) -> None:
    for key, val in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            _deep_merge(base[key], val)
        else:
            base[key] = val


def _update_kustomization(kust_path: Path, entry: str, *, add: bool, field: str = "patches") -> bool:
    """Add or remove an entry from kustomization.yaml. Returns True if changed."""
    if not kust_path.exists():
        return False

    kust = yaml.safe_load(kust_path.read_text()) or {}
    items = kust.get(field, [])

    ref = {"path": entry} if field == "patches" else entry

    if add:
        if ref in items:
            return False
        items.append(ref)
    else:
        if ref not in items:
            return False
        items.remove(ref)

    if items:
        kust[field] = items
    elif field in kust:
        del kust[field]

    kust_path.write_text(yaml.dump(kust, default_flow_style=False, sort_keys=False))
    return True


def _validate_kustomize(overlay: Path, show_actors: list[str] | None = None) -> bool:
    """Run kubectl kustomize and report validation results."""
    result = subprocess.run(  # nosec B603, B607
        ["kubectl", "kustomize", str(overlay)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        click.echo(f"[!] Kustomize validation failed:\n{result.stderr}", err=True)
        return False

    for doc in yaml.safe_load_all(result.stdout):
        if not isinstance(doc, dict) or doc.get("kind") != "AsyncActor":
            continue
        name = doc["metadata"]["name"]
        if show_actors and name not in show_actors:
            continue
        spec = doc.get("spec", {})
        env_count = len(spec.get("env", []))
        image = spec.get("image", "?")
        scaling = spec.get("scaling", {})
        s_min = scaling.get("minReplicaCount", 0)
        s_max = scaling.get("maxReplicaCount", "?")
        click.echo(f"[.] {name}: image={image}, scaling={s_min}-{s_max}, env={env_count}")

    return True


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(Path.cwd()))
    except ValueError:
        return str(p)


# -- CLI command -------------------------------------------------------------


@click.command("patch")
@click.argument("flow_name", type=ASYA_REF)
@click.argument("key_values", nargs=-1)
@click.option("--actor", "-a", "actor_ref", default=None, help="Target a specific actor")
@click.option("--all-actors", "all_actors", is_flag=True, help="Apply patch to all actors in the flow")
@click.option("--gateway", is_flag=True, help="Target gateway flow registration")
@click.option("--context", "ctx", default=None, help="Write to overlay (default: common/)")
@click.option("-p", "raw_patch", default=None, help="Raw JSON patch (escape hatch, actors only)")
@click.option("--remove", "remove_keys", multiple=True, help="Remove a key (e.g. --remove env.FOO)")
def patch(
    flow_name: AsyaRef,
    key_values: tuple[str, ...],
    actor_ref: str | None,
    all_actors: bool,
    gateway: bool,
    ctx: str | None,
    raw_patch: str | None,
    remove_keys: tuple[str, ...],
) -> None:
    """Patch compiled flow manifests with kustomize overrides.

    Requires exactly one scope: --actor or --gateway.

    \b
    Actor patches:
      asya patch text-flow --actor analyze scaling.min=1
      asya patch text-flow --actor analyze env.MY_VAR=value
      asya patch text-flow --actor analyze env.API_KEY=secret:my-secret:key
      asya patch text-flow --actor analyze --remove env.OLD_VAR
      asya patch text-flow --actor analyze -p '{"scaling":{"minReplicaCount":1}}'

    \b
    Gateway patches:
      asya patch text-flow --gateway expose=true description="Analyze text" mcp=true a2a=true
      asya patch text-flow --gateway expose=false
      asya patch text-flow --gateway expose=true --context dev

    \b
    Env shorthand:
      env.NAME=value                    plain value
      env.NAME=secret:secret-name:key   secretKeyRef
      env.NAME=configmap:cm-name:key    configMapKeyRef

    \b
    Scaling shorthand:
      scaling.min=1     minReplicaCount
      scaling.max=20    maxReplicaCount
    """
    # Validate scope
    if not actor_ref and not all_actors and not gateway:
        raise click.UsageError("Specify a scope: --actor <name>, --all-actors, or --gateway")
    if sum(bool(x) for x in [actor_ref, all_actors, gateway]) > 1:
        raise click.UsageError("Specify only one scope: --actor, --all-actors, or --gateway")

    if not key_values and not raw_patch and not remove_keys:
        raise click.UsageError("Provide key=value pairs, --remove keys, or -p '{json}'")

    asya_dir = find_asya_dir(Path.cwd())
    if asya_dir is None:
        click.echo("[-] No .asya/ directory found. Run 'asya init' first.", err=True)
        sys.exit(1)

    # Try kebab→snake, then as-is, to match whatever the compiler used
    project = AsyaProject.from_dir(asya_dir.parent, arg_values={"flow_name": flow_name.name})
    manifests_dir = project.resolve_path("compiler.manifests")
    base_dir = manifests_dir / BASE_DIR

    if not base_dir.is_dir():
        click.echo("[-] No compiled manifests found. Run 'asya compile' first.", err=True)
        sys.exit(1)

    # Determine target directory
    if ctx:
        patch_dir = manifests_dir / OVERLAYS_DIR / ctx
        if not patch_dir.is_dir():
            click.echo(f"[-] Overlay '{ctx}' not found: {patch_dir}", err=True)
            sys.exit(1)
    else:
        patch_dir = manifests_dir / COMMON_DIR

    # -- Gateway scope -------------------------------------------------------
    if gateway:
        if raw_patch:
            raise click.UsageError("-p is not supported with --gateway")

        entrypoint = _find_entrypoint(base_dir)
        intent = _build_gateway_config(flow_name.name, entrypoint, key_values)

        # Intent is consumed by `asya k apply`; it is NOT a kustomize resource.
        intent_path = patch_dir / EXPOSE_FILENAME

        if intent is None:
            # expose=false: remove
            if intent_path.exists():
                intent_path.unlink()
            click.echo(f"[+] Gateway exposure removed for '{flow_name.name}'")
        else:
            patch_dir.mkdir(parents=True, exist_ok=True)
            intent_path.write_text(yaml.dump(intent, default_flow_style=False, sort_keys=False))
            click.echo(f"[+] {_rel(intent_path)}")
            click.echo(f"[.] Run 'asya k apply {flow_name.name}' to register with the gateway.")
        return

    # -- Actor scope ---------------------------------------------------------
    if all_actors:
        actor_names = _resolve_actors(base_dir)
    else:
        if actor_ref is None:
            raise RuntimeError("actor_ref must be set when all_actors is False")
        actor_names = [_resolve_actor_name(actor_ref, base_dir)]

    env_remove = [k[4:] for k in remove_keys if k.startswith("env.")]

    for actor_name in actor_names:
        ps = _build_actor_patch(actor_name, key_values, raw_patch)
        ps.env_remove.extend(env_remove)
        patch_file = _write_actor_patch(ps, patch_dir)

        kust_path = patch_dir / "kustomization.yaml"
        if patch_file.exists():
            added = _update_kustomization(kust_path, patch_file.name, add=True)
            click.echo(f"[+] {_rel(patch_file)}")
            if added:
                click.echo(f"[+] Registered in {_rel(kust_path)}")
        else:
            click.echo(f"[+] Removed patch for {actor_name}")

    # Validate
    overlay = patch_dir
    _validate_kustomize(overlay, show_actors=actor_names)
