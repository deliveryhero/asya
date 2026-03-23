"""Stamp AsyncActor manifests from compiler template into kustomize structure.

Three-layer kustomize output:
  base/       — fully regenerated on every compile
  common/     — user customizations, created once, preserved across recompiles
  overlays/   — per-context overlays, created once, preserved across recompiles
"""

from __future__ import annotations

import dataclasses
import logging
import re
import shutil
from pathlib import Path

import yaml

from asya_lab.config.discovery import BASE_DIR, COMMON_DIR, OVERLAYS_DIR
from asya_lab.config.project import AsyaProject
from asya_lab.flow.codegen import ROUTER_PREFIXES, AdapterFile, CodegenMeta
from asya_lab.flow.result_types import ActorInfo


def _literal_representer(dumper: yaml.Dumper, data: str) -> yaml.ScalarNode:
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


class _Dumper(yaml.Dumper):
    pass


_Dumper.add_representer(str, _literal_representer)


log = logging.getLogger(__name__)

_ROUTER_PREFIXES = ROUTER_PREFIXES
_TEMPLATE_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


@dataclasses.dataclass(frozen=True)
class TemplateContext:
    """Compiler-output variables available in templates.

    These are the values the compiler always computes per actor.
    Config values from `templates:` and CLI args are merged separately.
    """

    actor_name: str  # used for both metadata.name and spec.actor (usually same value)
    flow_name: str
    flow_function: str
    role: str
    handler: str
    image: str


def _resolve_template_string(text: str, context: dict[str, str]) -> str:
    """Resolve {{ key }} placeholders in a template string."""

    def _replace(m: re.Match) -> str:
        key = m.group(1)
        if key not in context:
            raise KeyError(f"Unknown template variable '{{{{ {key} }}}}'. Available: {sorted(context)}")
        return str(context[key])

    return _TEMPLATE_RE.sub(_replace, text)


class ManifestTemplater:
    """Stamps AsyncActor manifests into a kustomize directory structure.

    Naming convention (see rfc.md section 7.4):
      flow_function / actor_function: Python function name, underscores (my_flow)
      flow_name / actor name:         K8s/Asya name, hyphens (my-flow)

    The compiler (parser, grouper, codegen) works with function names.
    The templater converts to K8s names for all output: filenames, metadata,
    labels, ConfigMap names. Handler references (spec.handler) keep the
    Python form since they reference Python functions.

    Templates use {{ key }} placeholders for variable substitution.
    Context is built from:
      1. Config `templates:` section (user-defined values)
      2. TemplateContext fields (compiler-computed values, override config if collision)
    """

    def __init__(
        self,
        *,
        flow_name: str,
        flow_function: str,
        codegen_meta: CodegenMeta,
        router_code: str,
        project: AsyaProject,
        actor_template_path: Path,
        router_template_path: Path | None = None,
        configmap_routers_template_path: Path | None = None,
        kustomization_template_path: Path | None = None,
        import_map: dict[str, str] | None = None,
        handler_source_files: dict[str, Path] | None = None,
        flow_roles: dict[str, str] | None = None,
    ) -> None:
        self.flow_name = flow_name
        self.flow_function = flow_function
        self.codegen_meta = codegen_meta
        self.router_code = router_code
        self.project = project
        self.actor_template_path = actor_template_path
        self.router_template_path = router_template_path
        self.configmap_routers_template_path = configmap_routers_template_path
        self.kustomization_template_path = kustomization_template_path
        self.import_map: dict[str, str] = import_map or {}
        self.handler_source_files: dict[str, Path] = handler_source_files or {}
        self.flow_roles: dict[str, str] = flow_roles or {}

    def stamp(self, output_dir: Path) -> list[str]:
        """Generate kustomize-structured manifests.

        Returns list of generated file paths (relative to output_dir).
        """
        base_dir = output_dir / BASE_DIR
        common_dir = output_dir / COMMON_DIR
        overlays_dir = output_dir / OVERLAYS_DIR

        generated = []

        self._stamp_readme(output_dir)
        generated.extend(self._stamp_base(base_dir))
        generated.extend(self._stamp_common(common_dir))
        generated.extend(self._stamp_overlays(overlays_dir))

        return generated

    # -- base/ layer (fully regenerated) ------------------------------------

    def _stamp_base(self, base_dir: Path) -> list[str]:
        if base_dir.exists():
            shutil.rmtree(base_dir)
        base_dir.mkdir(parents=True)

        (base_dir / "AUTO-GENERATED.md").write_text(
            "This directory is fully regenerated on every `asya compile`.\n"
            "Any manual changes will be lost.\n\n"
            "Put your customizations in `../common/` as kustomize patches.\n"
        )

        resources: list[str] = []
        generated: list[str] = []

        actors = self._collect_actors()
        for actor in actors:
            filename = f"asya-{actor.name}.yaml"
            self._stamp_actor(base_dir / filename, actor)
            resources.append(filename)
            generated.append(f"base/{filename}")

        cm_filename = "configmap-routers.yaml"
        self._stamp_configmap(base_dir / cm_filename)
        resources.append(cm_filename)
        generated.append(f"base/{cm_filename}")

        # Generate ConfigMaps for adapter files
        if self.codegen_meta.adapter_files:
            for af in self.codegen_meta.adapter_files:
                adapter_cm_filename = f"configmap-{self._to_k8s_name(af.actor_name)}-adapter.yaml"
                self._stamp_adapter_configmap(base_dir / adapter_cm_filename, af)
                resources.append(adapter_cm_filename)
                generated.append(f"base/{adapter_cm_filename}")

        kust_filename = "kustomization.yaml"
        self._write_kustomization(base_dir / kust_filename, resources)
        generated.append(f"base/{kust_filename}")

        return generated

    def _stamp_actor(self, path: Path, actor: ActorInfo) -> None:
        """Stamp a single actor manifest from the template."""
        manifest = self._resolve_template(actor)

        # Add two orthogonal labels:
        #   asya.sh/role: start|end (only for start/end actors)
        #   asya.sh/generated: "true" (only for generated routers)
        labels = manifest.get("metadata", {}).get("labels", {})
        if actor.role in ("start", "end"):
            labels["asya.sh/role"] = actor.role
        if actor.generated:
            labels["asya.sh/generated"] = "true"

        template_env = manifest["spec"].get("env") or []
        manifest["spec"]["env"] = template_env + actor.env

        # Mount routers ConfigMap for generated router actors
        if actor.generated:
            self._inject_router_configmap_mount(manifest)
            # Hash of routers.py triggers rolling update on code change
            self._inject_configmap_hash(manifest, self.router_code)

        # Mount adapter ConfigMap for adapter actors
        if not actor.generated and self.codegen_meta.adapter_files:
            for af in self.codegen_meta.adapter_files:
                if af.actor_name == actor.name.replace("actor-", "").replace("-", "_"):
                    self._inject_adapter_configmap_mount(manifest, af)
                    self._inject_configmap_hash(manifest, af.code)
                    break

        # Inject compiler-generated resiliency config
        if not actor.generated:
            self._inject_retry_rules(manifest, actor)
            self._inject_extracted_configs(manifest, actor)

        path.write_text(yaml.dump(manifest, Dumper=_Dumper, default_flow_style=False, sort_keys=False))

    def _resolve_template(self, actor: ActorInfo) -> dict:
        """Load actor template and resolve {{ key }} placeholders."""
        if actor.generated and self.router_template_path and self.router_template_path.exists():
            template_path = self.router_template_path
        else:
            template_path = self.actor_template_path

        text = template_path.read_text()

        tc = TemplateContext(
            actor_name=actor.name,
            flow_name=self.flow_name,
            flow_function=self.flow_function,
            role=actor.role,
            handler=actor.handler,
            image=actor.image,
        )

        context = self.project.build_template_context()
        # TemplateContext values (override config if collision — reserved names)
        context.update({k: str(v) for k, v in dataclasses.asdict(tc).items()})

        resolved_text = _resolve_template_string(text, context)
        return yaml.safe_load(resolved_text)

    def _stamp_configmap(self, path: Path) -> None:
        """Generate ConfigMap containing router code from template."""
        if self.configmap_routers_template_path and self.configmap_routers_template_path.exists():
            cm = self._resolve_configmap_template()
        else:
            cm = {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {
                    "name": f"{self.flow_name}-routers",
                    "labels": {
                        "asya.sh/flow": self.flow_name,
                        "asya.sh/managed-by": "asya-compiler",
                    },
                },
                "data": {},
            }
        cm.setdefault("data", {})
        cm["data"]["routers.py"] = self.router_code
        path.write_text(yaml.dump(cm, Dumper=_Dumper, default_flow_style=False, sort_keys=False))

    def _stamp_adapter_configmap(self, path: Path, af: AdapterFile) -> None:
        """Generate a ConfigMap containing adapter code for a non-standard actor."""
        k8s_name = self._to_k8s_name(af.actor_name)
        cm = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": f"{self.flow_name}-{k8s_name}-adapter",
                "labels": {
                    "asya.sh/flow": self.flow_name,
                    "asya.sh/managed-by": "asya-compiler",
                    "asya.sh/adapter-for": k8s_name,
                },
            },
            "data": {
                af.filename: af.code,
            },
        }
        path.write_text(yaml.dump(cm, Dumper=_Dumper, default_flow_style=False, sort_keys=False))

    def _resolve_configmap_template(self) -> dict:
        """Load configmap template and resolve {{ key }} placeholders."""
        assert self.configmap_routers_template_path is not None
        text = self.configmap_routers_template_path.read_text()
        context = self.project.build_template_context()
        context["flow_name"] = self.flow_name
        context["flow_function"] = self.flow_function
        resolved_text = _resolve_template_string(text, context)
        return yaml.safe_load(resolved_text)

    def _write_kustomization(self, path: Path, resources: list[str]) -> None:
        if self.kustomization_template_path and self.kustomization_template_path.exists():
            kust = self._resolve_kustomization_template(resources)
        else:
            kust = {
                "apiVersion": "kustomize.config.k8s.io/v1beta1",
                "kind": "Kustomization",
            }
        kust["resources"] = sorted(resources)
        path.write_text(yaml.dump(kust, Dumper=_Dumper, default_flow_style=False, sort_keys=False))

    def _resolve_kustomization_template(self, resources: list[str]) -> dict:
        """Load kustomization template and resolve {{ key }} placeholders."""
        assert self.kustomization_template_path is not None
        text = self.kustomization_template_path.read_text()
        context = self.project.build_template_context()
        context["flow_name"] = self.flow_name
        context["flow_function"] = self.flow_function
        resolved_text = _resolve_template_string(text, context)
        return yaml.safe_load(resolved_text)

    # -- README (created once) ----------------------------------------------

    _README = """\
# Kustomize Manifest Structure

This directory contains kustomize-structured manifests generated by the
Asya flow compiler. Three layers, from bottom to top:

## base/ — compiler-generated, DO NOT EDIT

Fully regenerated on every `asya compile`. Any manual changes will be
lost. To customize base resources, use patches in `common/`.

## common/ — your customizations

Add kustomize patches here. They apply on top of `base/` and are
preserved across recompiles. Example — scale a handler actor:

```yaml
# common/scale-handler-a.yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: handler-a
spec:
  scaling:
    maxReplicaCount: 20
```

Then add it to `common/kustomization.yaml`:

```yaml
resources:
  - ../base
patches:
  - path: scale-handler-a.yaml
```

## overlays/<env>/ — per-environment overrides

One directory per context defined in `.asya/config.yaml`. Same rules
as `common/` — add patches, they are preserved across recompiles.
Each overlay builds on top of `common/`.
"""

    def _stamp_readme(self, output_dir: Path) -> None:
        readme_path = output_dir / "README.md"
        if readme_path.exists():
            return
        output_dir.mkdir(parents=True, exist_ok=True)
        readme_path.write_text(self._README)

    # -- common/ layer (created once, never overwritten) --------------------

    _KUSTOMIZE_CONFIG = """\
images:
- path: spec/image
  kind: AsyncActor
"""

    def _stamp_common(self, common_dir: Path) -> list[str]:
        kust_path = common_dir / "kustomization.yaml"
        if kust_path.exists():
            return []

        common_dir.mkdir(parents=True, exist_ok=True)

        config_path = common_dir / "kustomizeconfig.yaml"
        config_path.write_text(self._KUSTOMIZE_CONFIG)

        # Resolve namespace from default context if configured
        default_ctx = self.project.cfg.get("default_context")
        ns = None
        if default_ctx:
            ctx_cfg = self.project.cfg.get("contexts", {})
            if isinstance(ctx_cfg, dict) and default_ctx in ctx_cfg:
                ns = ctx_cfg[default_ctx].get("namespace")

        kust: dict = {
            "apiVersion": "kustomize.config.k8s.io/v1beta1",
            "kind": "Kustomization",
        }
        if ns:
            kust["namespace"] = str(ns)
        kust["resources"] = ["../base"]
        kust["configurations"] = ["kustomizeconfig.yaml"]
        kust_path.write_text(yaml.dump(kust, default_flow_style=False, sort_keys=False))
        return ["common/kustomization.yaml", "common/kustomizeconfig.yaml"]

    # -- overlays/<context>/ layer (created once per context) ---------------

    def _stamp_overlays(self, overlays_dir: Path) -> list[str]:
        contexts = self.project.get_contexts()
        if not contexts:
            return []

        generated: list[str] = []
        resolved_overlays = overlays_dir.resolve()
        for ctx_name in contexts:
            ctx_dir = overlays_dir / ctx_name
            # Guard against path traversal in context names (e.g. "../../")
            if not ctx_dir.resolve().is_relative_to(resolved_overlays):
                log.warning("Skipping context '%s': path escapes output directory", ctx_name)
                continue
            kust_path = ctx_dir / "kustomization.yaml"
            if kust_path.exists():
                continue

            ctx_dir.mkdir(parents=True, exist_ok=True)
            self._write_kustomization(kust_path, ["../../common"])
            generated.append(f"overlays/{ctx_name}/kustomization.yaml")

        return generated

    # -- resiliency injection ------------------------------------------------

    def _inject_retry_rules(self, manifest: dict, actor: ActorInfo) -> None:
        """Inject compiler-generated resiliency rules from try/except blocks.

        Compiler-generated rules prepend before actor's own rules so that
        flow-level try/except semantics take precedence for matched error types.
        """
        if not self.codegen_meta.actor_retry_rules:
            return

        # Strip actor- prefix to get the Python function name (the key in actor_retry_rules)
        name = actor.name
        if name.startswith("actor-"):
            name = name[len("actor-") :]
        actor_python_name = name.replace("-", "_")
        rules = self.codegen_meta.actor_retry_rules.get(actor_python_name, [])
        if not rules:
            return

        spec = manifest.setdefault("spec", {})
        resiliency = spec.setdefault("resiliency", {})
        policies = resiliency.setdefault("policies", {})
        existing_rules = resiliency.get("rules", [])

        generated_rules: list[dict] = []
        for rule in rules:
            k8s_route = [self._to_k8s_name(r) for r in rule.then_route]

            if rule.error_types is None:
                # Bare except: set policies.default.thenRoute
                if "default" in policies:
                    raise ValueError(
                        f"Actor '{actor.name}' already has policies.default defined; "
                        f"cannot use bare 'except:' in a try/except block wrapping this actor."
                    )
                policies["default"] = {
                    "maxAttempts": 1,
                    "thenRoute": k8s_route,
                }
            else:
                policies[rule.policy_name] = {
                    "maxAttempts": 1,
                    "thenRoute": k8s_route,
                }
                generated_rules.append(
                    {
                        "errors": rule.error_types,
                        "policy": rule.policy_name,
                    }
                )

        # Prepend compiler-generated rules before actor's own rules
        resiliency["rules"] = generated_rules + existing_rules

    def _inject_extracted_configs(self, manifest: dict, actor: ActorInfo) -> None:
        """Inject config values extracted from decorators and context managers.

        Each extracted_config has spec_values: {spec_path: value} and
        scope_actors: [actor_names]. Config is injected into the manifest
        at the specified spec paths for actors within scope.

        Also injects ASYA_IGNORE_DECORATORS env var for decorator-scoped
        configs so the runtime strips extracted decorators at load time.
        """
        if not self.codegen_meta.extracted_configs:
            return

        name = actor.name
        if name.startswith("actor-"):
            name = name[len("actor-") :]
        actor_python_name = name.replace("-", "_")

        # Apply scope configs first (context managers), then decorator configs.
        # Decorator configs are more specific and override scope values.
        decorator_fqns: list[str] = []
        scope_configs = []
        decorator_configs = []
        for config in self.codegen_meta.extracted_configs:
            if actor_python_name not in config.get("scope_actors", []):
                continue
            if config.get("scope_type") == "decorator":
                decorator_configs.append(config)
                decorator_fqns.append(config["symbol"])
            else:
                scope_configs.append(config)

        for config in scope_configs + decorator_configs:
            for spec_path, value in config.get("spec_values", {}).items():
                self._set_nested(manifest, spec_path, value)

        if decorator_fqns:
            env_list = manifest.get("spec", {}).get("env", [])
            env_list.append({"name": "ASYA_IGNORE_DECORATORS", "value": ",".join(sorted(set(decorator_fqns)))})

    @staticmethod
    def _set_nested(d: dict, dotted_path: str, value: object) -> None:
        """Set a value at a dotted path in a nested dict, creating intermediates."""
        keys = dotted_path.split(".")
        for key in keys[:-1]:
            d = d.setdefault(key, {})
        d[keys[-1]] = value

    def _inject_router_configmap_mount(self, manifest: dict) -> None:
        """Mount the routers ConfigMap at /opt/asya/routers.py for generated router actors.

        The runtime starts as `python3 /opt/asya/asya_runtime.py`, so /opt/asya/
        is on sys.path — mounting routers.py there makes it directly importable.
        """
        cm_name = f"{self.flow_name}-routers"
        spec = manifest.setdefault("spec", {})

        volumes = spec.setdefault("volumes", [])
        volumes.append({"name": "routers", "configMap": {"name": cm_name}})

        mounts = spec.setdefault("volumeMounts", [])
        mounts.append(
            {
                "name": "routers",
                "mountPath": "/opt/asya/routers.py",
                "subPath": "routers.py",
                "readOnly": True,
            }
        )

    @staticmethod
    def _inject_configmap_hash(manifest: dict, code: str) -> None:
        """Add ASYA_CODE_HASH env var so Crossplane triggers rollout on code change."""
        import hashlib

        code_hash = hashlib.sha256(code.encode()).hexdigest()[:12]
        env = manifest["spec"].setdefault("env", [])
        env.append({"name": "ASYA_CODE_HASH", "value": code_hash})

    def _inject_adapter_configmap_mount(self, manifest: dict, af: "AdapterFile") -> None:
        """Mount an adapter ConfigMap at /opt/asya/<adapter>.py for adapter actors.

        The adapter wraps the original function to conform to dict-in/dict-out protocol.
        Mounted at /opt/asya/ which is on sys.path (runtime starts from /opt/asya/).
        """
        k8s_name = self._to_k8s_name(af.actor_name)
        cm_name = f"{self.flow_name}-{k8s_name}-adapter"
        spec = manifest.setdefault("spec", {})

        volumes = spec.setdefault("volumes", [])
        volumes.append({"name": "adapter", "configMap": {"name": cm_name}})

        mounts = spec.setdefault("volumeMounts", [])
        mounts.append(
            {
                "name": "adapter",
                "mountPath": f"/opt/asya/{af.filename}",
                "subPath": af.filename,
                "readOnly": True,
            }
        )

    # -- actor collection ---------------------------------------------------

    def _collect_actors(self) -> list[ActorInfo]:
        """Collect all actors from the compiled flow."""
        context = self.project.build_template_context()
        router_image = context.get("router_image", "python:3.13-slim")
        handler_actors: dict[str, ActorInfo] = {}
        router_actors: list[ActorInfo] = []

        for router_name in self.codegen_meta.router_names:
            refs = self.codegen_meta.router_refs.get(router_name, [])
            handler_env = self._build_handler_env_from_refs(refs)

            # Graph-derived role overrides the naming-convention-based role
            role = self.flow_roles.get(router_name, self._router_flow_role(router_name))

            router_actors.append(
                ActorInfo(
                    name=self._to_k8s_name(router_name),
                    handler=f"routers.{router_name}",
                    image=router_image,
                    role=role,
                    env=handler_env,
                    generated=True,
                )
            )

            for actor_name in refs:
                if self._is_router_name(actor_name):
                    continue
                if actor_name not in handler_actors:
                    handler_fqn = self.import_map.get(actor_name, actor_name)
                    handler_source = self.handler_source_files.get(actor_name)
                    image = self.project.resolve_image(
                        actor_name, handler_fqn=handler_fqn, handler_source=handler_source
                    )
                    k8s_name = f"actor-{self._to_k8s_name(actor_name)}"
                    handler = handler_fqn
                    # Use adapter handler if an adapter was generated
                    if self.codegen_meta.adapter_files:
                        for af in self.codegen_meta.adapter_files:
                            if af.actor_name == actor_name:
                                adapter_fn = f"adapter_{actor_name}"
                                handler = f"{adapter_fn}.{adapter_fn}"
                                break
                    # Graph-derived role overrides the default "actor" role
                    role = self.flow_roles.get(actor_name, "actor")
                    handler_actors[actor_name] = ActorInfo(
                        name=k8s_name,
                        handler=handler,
                        image=image,
                        role=role,
                    )

        return router_actors + list(handler_actors.values())

    @staticmethod
    def _to_k8s_name(name: str) -> str:
        """Convert Python name (underscores) to K8s name (hyphens)."""
        return name.replace("_", "-")

    def _build_handler_env_from_refs(self, refs: list[str]) -> list[dict[str, str]]:
        """Build ASYA_HANDLER_* env vars for a router actor.

        All referenced actors — including other routers — get an env var so the
        generated resolve() function can map names to actor queue identifiers.
        Router handlers use the "routers.<name>" dotted form so that the suffix
        index in resolve() can match on the bare function name.
        """
        seen: set[str] = set()
        env: list[dict[str, str]] = []
        for actor_name in refs:
            if actor_name in seen:
                continue
            seen.add(actor_name)
            if self._is_router_name(actor_name):
                k8s_name = self._to_k8s_name(actor_name)
                handler = f"routers.{actor_name}"
            else:
                k8s_name = f"actor-{self._to_k8s_name(actor_name)}"
                handler = self.import_map.get(actor_name, actor_name)
            env_var_name = f"ASYA_HANDLER_{k8s_name.upper().replace('-', '_')}"
            env.append({"name": env_var_name, "value": handler})
        return env

    def _is_router_name(self, name: str) -> bool:
        return any(name.startswith(p) for p in _ROUTER_PREFIXES)

    def _router_flow_role(self, name: str) -> str:
        if name.startswith("start_"):
            return "start"
        return "router"
