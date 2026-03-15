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
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from asya_lab.config.discovery import BASE_DIR, COMMON_DIR, OVERLAYS_DIR
from asya_lab.config.project import AsyaProject
from asya_lab.flow.grouper import Router


def _literal_representer(dumper: yaml.Dumper, data: str) -> yaml.ScalarNode:
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


class _Dumper(yaml.Dumper):
    pass


_Dumper.add_representer(str, _literal_representer)


log = logging.getLogger(__name__)

_ROUTER_PREFIXES = ("start_", "end_", "router_", "except_", "loop_", "fanout_")
_TEMPLATE_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


@dataclass
class ActorInfo:
    """Collected metadata for a single actor manifest.

    Naming convention:
      name:    K8s name with hyphens (e.g. "handler-a", "start-my-flow")
      handler: Python function reference with underscores (e.g. "handler_a", "routers.start_my_flow")
    """

    name: str
    handler: str
    image: str
    flow_role: str
    env: list[dict[str, str]] = field(default_factory=list)
    is_router: bool = False


@dataclasses.dataclass(frozen=True)
class TemplateContext:
    """Compiler-output variables available in templates.

    These are the values the compiler always computes per actor.
    Config values from `templates:` and CLI args are merged separately.
    """

    actor_name: str
    flow_name: str
    flow_function: str
    flow_role: str
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
        routers: list[Router],
        router_code: str,
        project: AsyaProject,
        actor_template_path: Path,
        router_template_path: Path | None = None,
        configmap_routers_template_path: Path | None = None,
        kustomization_template_path: Path | None = None,
    ) -> None:
        self.flow_name = flow_name
        self.flow_function = flow_function
        self.routers = routers
        self.router_code = router_code
        self.project = project
        self.actor_template_path = actor_template_path
        self.router_template_path = router_template_path
        self.configmap_routers_template_path = configmap_routers_template_path
        self.kustomization_template_path = kustomization_template_path

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
            filename = f"asyncactor-{actor.name}.yaml"
            self._stamp_actor(base_dir / filename, actor)
            resources.append(filename)
            generated.append(f"base/{filename}")

        cm_filename = "configmap-routers.yaml"
        self._stamp_configmap(base_dir / cm_filename)
        resources.append(cm_filename)
        generated.append(f"base/{cm_filename}")

        kust_filename = "kustomization.yaml"
        self._write_kustomization(base_dir / kust_filename, resources)
        generated.append(f"base/{kust_filename}")

        return generated

    def _stamp_actor(self, path: Path, actor: ActorInfo) -> None:
        """Stamp a single actor manifest from the template."""
        manifest = self._resolve_template(actor)
        manifest["spec"]["env"] = actor.env
        path.write_text(yaml.dump(manifest, Dumper=_Dumper, default_flow_style=False, sort_keys=False))

    def _resolve_template(self, actor: ActorInfo) -> dict:
        """Load actor template and resolve {{ key }} placeholders."""
        if actor.is_router and self.router_template_path and self.router_template_path.exists():
            template_path = self.router_template_path
        else:
            template_path = self.actor_template_path

        text = template_path.read_text()

        tc = TemplateContext(
            actor_name=actor.name,
            flow_name=self.flow_name,
            flow_function=self.flow_function,
            flow_role=actor.flow_role,
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
            context = self.project.build_template_context()
            namespace = context.get("namespace", "default")
            cm = {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {
                    "name": f"{self.flow_name}-routers",
                    "namespace": namespace,
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

    def _stamp_common(self, common_dir: Path) -> list[str]:
        kust_path = common_dir / "kustomization.yaml"
        if kust_path.exists():
            return []

        common_dir.mkdir(parents=True, exist_ok=True)
        self._write_kustomization(kust_path, ["../base"])
        return ["common/kustomization.yaml"]

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

    # -- actor collection ---------------------------------------------------

    def _collect_actors(self) -> list[ActorInfo]:
        """Collect all actors from the compiled flow."""
        context = self.project.build_template_context()
        router_image = context.get("router_image", "python:3.13-slim")
        handler_actors: dict[str, ActorInfo] = {}
        router_actors: list[ActorInfo] = []

        for router in self.routers:
            handler_env = self._build_handler_env(router)

            router_actors.append(
                ActorInfo(
                    name=self._to_k8s_name(router.name),
                    handler=f"routers.{router.name}",
                    image=router_image,
                    flow_role=self._router_flow_role(router.name),
                    env=handler_env,
                    is_router=True,
                )
            )

            for actor_name in self._get_referenced_actors(router):
                if self._is_router_name(actor_name):
                    continue
                if actor_name not in handler_actors:
                    image = self.project.resolve_image(actor_name)
                    k8s_name = self._to_k8s_name(actor_name)
                    handler_actors[actor_name] = ActorInfo(
                        name=k8s_name,
                        handler=actor_name,
                        image=image,
                        flow_role="handler",
                    )

        return router_actors + list(handler_actors.values())

    @staticmethod
    def _to_k8s_name(name: str) -> str:
        """Convert Python name (underscores) to K8s name (hyphens)."""
        return name.replace("_", "-")

    def _get_referenced_actors(self, router: Router) -> list[str]:
        """Get all actor names referenced by a router."""
        actors = []
        actors.extend(router.true_branch_actors)
        actors.extend(router.false_branch_actors)
        actors.extend(router.finally_actors)
        actors.extend(router.continuation_actors)
        if router.exception_handlers:
            for handler in router.exception_handlers:
                actors.extend(handler.actors)
        if router.is_fan_out and router.fan_out_op:
            for actor_name, _payload_expr in router.fan_out_op.actor_calls:
                actors.append(actor_name)
        return actors

    def _build_handler_env(self, router: Router) -> list[dict[str, str]]:
        """Build ASYA_HANDLER_* env vars for a router actor."""
        env: list[dict[str, str]] = []
        for actor_name in self._get_referenced_actors(router):
            if self._is_router_name(actor_name):
                continue
            k8s_name = self._to_k8s_name(actor_name)
            env_var_name = f"ASYA_HANDLER_{actor_name.upper().replace('-', '_')}"
            env.append({"name": env_var_name, "value": k8s_name})
        return env

    def _is_router_name(self, name: str) -> bool:
        return any(name.startswith(p) for p in _ROUTER_PREFIXES)

    def _router_flow_role(self, name: str) -> str:
        if name.startswith("start_"):
            return "entrypoint"
        if name.startswith("end_"):
            return "exitpoint"
        return "router"
