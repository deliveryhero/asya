# Phase 2 Core Pipeline: Manifests + CLI + SDK

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the Phase 1 pipeline modules into a complete end-to-end compiler: 5-step orchestrator with manifest generation, FlowInfo/ActorInfo interfaces, smart entrypoint/exitpoint detection, and SDK `compile()` function.

**Architecture:** The compiler pipeline grows from 4 steps (Parse → CodeGen → Analyze → GraphGen) to 5 steps (Parse → CodeGen → **Manifests** → Analyze → GraphGen). The CodeGenerator exposes metadata (router names + referenced handlers per router) that the templater uses instead of the deleted `Router` class. The compiler returns a `FlowInfo` dataclass that both CLI and SDK consume.

**Tech Stack:** Python 3.13, Click CLI, OmegaConf, PyYAML, kustomize manifests

**Spec:** `.aint/aints/compiler-simplify/active.gml9.phase-2-orchestrator-interfaces-manifests-cli.md`

**RFC:** `.aint/aints/compiler-simplify/rfc.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `src/asya-lab/asya_lab/flow/types.py` | FlowInfo + ActorInfo dataclasses |
| Modify | `src/asya-lab/asya_lab/flow/codegen.py` | Expose `CodegenMeta` (router names, handler refs per router) |
| Modify | `src/asya-lab/asya_lab/compiler/templater.py` | Remove Router dependency, accept CodegenMeta |
| Modify | `src/asya-lab/asya_lab/flow/compiler.py` | 5-step pipeline, return FlowInfo, AsyaProject integration |
| Modify | `src/asya-lab/asya_lab/flow/__init__.py` | Export FlowInfo, ActorInfo, compile() SDK function |
| Modify | `src/asya-lab/asya_lab/compile_cli.py` | Use FlowInfo, remove _stamp_manifests call |
| Modify | `src/asya-lab/asya_lab/flow_cli.py` | Remove broken _stamp_manifests() |
| Modify | `src/asya-lab/asya_lab/compiler/__init__.py` | Update exports |
| Rewrite | `src/asya-lab/tests/test_stamper.py` | Remove Router dependency, test with CodegenMeta |
| Modify | `src/asya-lab/tests/test_compile_cli.py` | Update for new output format |
| Create | `src/asya-lab/tests/test_flow_types.py` | Unit tests for FlowInfo/ActorInfo |
| Modify | `testing/component/flow-compiler/tests/test_compiler_api.py` | Update for FlowInfo return type |
| Modify | `examples/demo-kubecon/.asya/config.yaml` | Add `compiler.templates` config key |

**Config key addition:** Add `compiler.templates: ".asya/compiler/templates"` to all example `.asya/config.yaml` files. This replaces the hard-coded convention of `<asya_dir>/compiler/templates/`.

---

## Task 1: Define FlowInfo + ActorInfo dataclasses

**Files:**
- Create: `src/asya-lab/asya_lab/flow/types.py`
- Create: `src/asya-lab/tests/test_flow_types.py`

- [ ] **Step 1: Write tests for FlowInfo and ActorInfo**

```python
# src/asya-lab/tests/test_flow_types.py
"""Tests for flow compiler type definitions."""

from pathlib import Path

from asya_lab.flow.types import ActorInfo, FlowInfo


class TestActorInfo:
    def test_basic_fields(self):
        actor = ActorInfo(
            name="handler-a",
            handler="handler_a",
            image="ghcr.io/team/actors:latest",
            flow_role="actor",
        )
        assert actor.name == "handler-a"
        assert actor.is_generated is False
        assert actor.manifest_path is None

    def test_router_actor(self):
        actor = ActorInfo(
            name="start-my-flow",
            handler="routers.start_my_flow",
            image="python:3.13-slim",
            flow_role="entrypoint",
            is_generated=True,
        )
        assert actor.is_generated is True
        assert actor.flow_role == "entrypoint"

    def test_env_defaults_to_empty(self):
        actor = ActorInfo(name="a", handler="a", image="img", flow_role="actor")
        assert actor.env == []


class TestFlowInfo:
    def test_basic_fields(self):
        info = FlowInfo(
            flow_name="my-flow",
            flow_function="my_flow",
            routers_path=Path("/tmp/routers.py"),
            manifests_dir=Path("/tmp/manifests"),
            graph={"nodes": [], "edges": []},
            dot="digraph {}",
            mermaid="flowchart LR",
            svg=None,
            actors=[],
            warnings=[],
        )
        assert info.flow_name == "my-flow"
        assert info.svg is None
        assert info.actors == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/a.yushkovskiy/gh/dh/asya/.worktrees/.worktrees/compiler-simplify/gml9.phase-2-orchestrator-interfaces-manifests-cli && uv run --project src/asya-lab pytest src/asya-lab/tests/test_flow_types.py -v --no-cov`
Expected: FAIL (import error, module not found)

- [ ] **Step 3: Implement FlowInfo and ActorInfo**

```python
# src/asya-lab/asya_lab/flow/types.py
"""Flow compiler result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ActorInfo:
    """Metadata for a single actor in a compiled flow.

    Naming convention:
      name:    K8s name with hyphens (e.g. "handler-a", "start-my-flow")
      handler: Python function reference (e.g. "handler_a", "routers.start_my_flow")
    """

    name: str
    handler: str
    image: str
    flow_role: str  # "entry" | "exit" | "entryexit" | "router" | "actor"
    env: list[dict[str, str]] = field(default_factory=list)
    is_generated: bool = False
    manifest_path: Path | None = None
    source_file: str | None = None
    source_line: int | None = None


@dataclass
class FlowInfo:
    """Result of compiling a flow."""

    flow_name: str
    flow_function: str
    routers_path: Path
    manifests_dir: Path
    graph: dict
    dot: str
    mermaid: str
    svg: str | None
    actors: list[ActorInfo]
    warnings: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/a.yushkovskiy/gh/dh/asya/.worktrees/.worktrees/compiler-simplify/gml9.phase-2-orchestrator-interfaces-manifests-cli && uv run --project src/asya-lab pytest src/asya-lab/tests/test_flow_types.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/asya-lab/asya_lab/flow/types.py src/asya-lab/tests/test_flow_types.py
git commit -m "feat(compiler): add FlowInfo + ActorInfo dataclasses"
```

---

## Task 2: Expose CodegenMeta from CodeGenerator

**Files:**
- Modify: `src/asya-lab/asya_lab/flow/codegen.py`
- Create: `src/asya-lab/tests/test_codegen_meta.py`

The CodeGenerator already tracks `_functions` (router funcs) and `_all_handlers` (all handler names). We need to expose structured metadata so the templater can build manifests without Router objects.

- [ ] **Step 1: Write test for CodegenMeta**

```python
# src/asya-lab/tests/test_codegen_meta.py
"""Tests for CodeGenerator metadata output."""

from asya_lab.flow.codegen import CodeGenerator, CodegenMeta
from asya_lab.flow.parser import FlowParser


def _parse(source: str) -> "ParseResult":
    parser = FlowParser(source, "test.py", "test")
    return parser.parse()


class TestCodegenMeta:
    def test_sequential_flow_metadata(self):
        source = '''
from asya_lab.flow import flow

async def handler_a(p): return p
async def handler_b(p): return p

@flow
async def my_flow(p):
    p = await handler_a(p)
    p = await handler_b(p)
    return p
'''
        result = _parse(source)
        gen = CodeGenerator(result, "test.py")
        code = gen.generate()
        meta = gen.get_meta()

        assert isinstance(meta, CodegenMeta)
        # Should have start router
        assert any(n.startswith("start_") for n in meta.router_names)
        # Should reference both handlers
        assert "handler_a" in meta.all_handler_names
        assert "handler_b" in meta.all_handler_names
        # Router refs should map start router to its referenced actors
        for router_name in meta.router_names:
            refs = meta.router_refs.get(router_name, [])
            assert len(refs) > 0, f"Router {router_name} should reference actors"

    def test_conditional_flow_metadata(self):
        source = '''
from asya_lab.flow import flow

async def handler_a(p): return p
async def handler_b(p): return p
async def handler_c(p): return p

@flow
async def cond_flow(p):
    p = await handler_a(p)
    if p.get("flag"):
        p = await handler_b(p)
    else:
        p = await handler_c(p)
    return p
'''
        result = _parse(source)
        gen = CodeGenerator(result, "test.py")
        code = gen.generate()
        meta = gen.get_meta()

        # Should have start router + conditional router
        assert len(meta.router_names) >= 2
        # All three handlers should be referenced
        for name in ("handler_a", "handler_b", "handler_c"):
            assert name in meta.all_handler_names

    def test_single_actor_flow_has_no_routers(self):
        source = '''
from asya_lab.flow import flow

async def handler_a(p): return p

@flow
async def simple(p):
    p = await handler_a(p)
    return p
'''
        result = _parse(source)
        gen = CodeGenerator(result, "test.py")
        code = gen.generate()
        meta = gen.get_meta()

        assert meta.router_names == []
        assert meta.single_actor == "handler_a"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/a.yushkovskiy/gh/dh/asya/.worktrees/.worktrees/compiler-simplify/gml9.phase-2-orchestrator-interfaces-manifests-cli && uv run --project src/asya-lab pytest src/asya-lab/tests/test_codegen_meta.py -v --no-cov`
Expected: FAIL (CodegenMeta not defined)

- [ ] **Step 3: Implement CodegenMeta and get_meta()**

In `src/asya-lab/asya_lab/flow/codegen.py`, add after the `_RouterFunc` dataclass (around line 45):

```python
@dataclass
class CodegenMeta:
    """Metadata about generated code, used by manifest templater."""

    router_names: list[str]
    all_handler_names: set[str]
    router_refs: dict[str, list[str]]  # router_name -> list of referenced actor names
    single_actor: str | None  # set for single-actor flows
```

Add `get_meta()` method to `CodeGenerator` class (after `generate()`):

```python
    def get_meta(self) -> CodegenMeta:
        """Return metadata about the generated code."""
        router_names = []
        router_refs: dict[str, list[str]] = {}

        if self._is_single_actor_flow():
            actor = next(op for op in self.result.operations if isinstance(op, ActorCall))
            return CodegenMeta(
                router_names=[],
                all_handler_names=set(),
                router_refs={},
                single_actor=actor.name,
            )

        # Start router is always generated (not in _functions list)
        start_name = f"start_{self.flow_name}"
        router_names.append(start_name)

        for rf in self._functions:
            router_names.append(rf.name)

        # All handlers referenced anywhere in the flow
        all_handlers = set(self._all_handlers)
        # Each router gets refs to ALL handlers (conservative approach).
        # The resolve() function uses env-var lookup at runtime, so
        # each router pod needs all handler mappings available.
        for rname in router_names:
            router_refs[rname] = sorted(all_handlers)

        return CodegenMeta(
            router_names=router_names,
            all_handler_names=all_handlers,
            router_refs=router_refs,
            single_actor=None,
        )
```

Note: The conservative approach (each router references all handlers) is correct because `resolve()` uses env-var lookup — the router pod needs ALL handler env vars since any router could reference any handler. This matches the existing behavior where the templater sets all handler env vars on every router.

Also export `ROUTER_PREFIXES` as a module-level constant (shared with templater):

```python
# In codegen.py, at module level (after imports)
ROUTER_PREFIXES = ("start_", "router_", "fanin_")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/a.yushkovskiy/gh/dh/asya/.worktrees/.worktrees/compiler-simplify/gml9.phase-2-orchestrator-interfaces-manifests-cli && uv run --project src/asya-lab pytest src/asya-lab/tests/test_codegen_meta.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/asya-lab/asya_lab/flow/codegen.py src/asya-lab/tests/test_codegen_meta.py
git commit -m "feat(codegen): expose CodegenMeta for manifest generation"
```

---

## Task 3: Rewrite ManifestTemplater to use CodegenMeta

**Files:**
- Modify: `src/asya-lab/asya_lab/compiler/templater.py`
- Rewrite: `src/asya-lab/tests/test_stamper.py`

The templater currently imports `Router` from the deleted `grouper.py`. Replace `routers: list[Router]` with `CodegenMeta` and rewrite `_collect_actors()`.

- [ ] **Step 1: Rewrite test_stamper.py tests**

Remove the `Router` import and `sequential_routers` fixture. Replace with `CodegenMeta` fixtures.

```python
# src/asya-lab/tests/test_stamper.py
"""Tests for compiler manifest templating."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import yaml
from asya_lab.compiler.templater import ManifestTemplater
from asya_lab.config.project import AsyaProject
from asya_lab.config.store import ConfigStore
from asya_lab.flow.codegen import CodegenMeta
from omegaconf import OmegaConf


@pytest.fixture()
def template_dir(tmp_path):
    """Create a minimal .asya/ with actor template."""
    asya_dir = tmp_path / ".asya"
    templates_dir = asya_dir / "compiler" / "templates"
    templates_dir.mkdir(parents=True)

    template = {
        "apiVersion": "asya.sh/v1alpha1",
        "kind": "AsyncActor",
        "metadata": {
            "name": "{{ actor_name }}",
            "namespace": "{{ namespace }}",
            "labels": {
                "asya.sh/flow": "{{ flow_name }}",
                "asya.sh/flow-role": "{{ flow_role }}",
            },
        },
        "spec": {
            "actor": "{{ actor_name }}",
            "image": "{{ image }}",
            "handler": "{{ handler }}",
            "scaling": {
                "enabled": True,
                "minReplicaCount": 0,
                "maxReplicaCount": 5,
            },
        },
    }
    (templates_dir / "actor.yaml").write_text(yaml.dump(template, sort_keys=False))

    configmap_template = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": "{{ flow_name }}-routers",
            "namespace": "{{ namespace }}",
            "labels": {
                "asya.sh/flow": "{{ flow_name }}",
                "asya.sh/managed-by": "asya-compiler",
            },
        },
    }
    (templates_dir / "configmap_routers.yaml").write_text(
        yaml.dump(configmap_template, sort_keys=False)
    )

    kustomization_template = {
        "apiVersion": "kustomize.config.k8s.io/v1beta1",
        "kind": "Kustomization",
    }
    (templates_dir / "kustomization.yaml").write_text(
        yaml.dump(kustomization_template, sort_keys=False)
    )

    return templates_dir / "actor.yaml"


def _make_project(cfg_dict: dict) -> AsyaProject:
    """Create a mock AsyaProject from a config dict."""
    cfg = OmegaConf.create(cfg_dict)
    store = MagicMock(spec=ConfigStore)
    store.cfg = cfg
    store.asya_dirs = []
    return AsyaProject(store)


@pytest.fixture()
def project():
    return _make_project(
        {
            "templates": {
                "namespace": "test-ns",
                "router_image": "python:3.13-slim",
            },
            "build": [
                {"module": "*", "image": "ghcr.io/test-org/*:latest"},
            ],
        }
    )


@pytest.fixture()
def project_with_contexts():
    return _make_project(
        {
            "templates": {
                "namespace": "test-ns",
                "router_image": "python:3.13-slim",
            },
            "build": [
                {"module": "*", "image": "ghcr.io/test-org/*:latest"},
            ],
            "contexts": {
                "stg": {"kubecontext": "stg-cluster"},
                "prod": {"kubecontext": "prod-cluster"},
            },
        }
    )


@pytest.fixture()
def sequential_meta():
    """CodegenMeta for a simple sequential flow: start -> handler_a -> handler_b."""
    return CodegenMeta(
        router_names=["start_my_flow"],
        all_handler_names={"handler_a", "handler_b"},
        router_refs={"start_my_flow": ["handler_a", "handler_b"]},
        single_actor=None,
    )


@pytest.fixture()
def router_code():
    return "# Auto-generated\nasync def start_my_flow(payload):\n    yield payload\n"


def _make_templater(flow_name, meta, router_code, project, template_path, flow_function=None):
    templates_dir = template_path.parent
    router_template = templates_dir / "router.yaml"
    return ManifestTemplater(
        flow_name=flow_name,
        flow_function=flow_function or flow_name.replace("-", "_"),
        codegen_meta=meta,
        router_code=router_code,
        project=project,
        actor_template_path=template_path,
        router_template_path=router_template if router_template.exists() else None,
        configmap_routers_template_path=templates_dir / "configmap_routers.yaml",
        kustomization_template_path=templates_dir / "kustomization.yaml",
    )


class TestBaseLayer:
    def test_base_dir_created(self, tmp_path, sequential_meta, router_code, project, template_dir):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")
        assert (tmp_path / "manifests" / "base").is_dir()

    def test_base_contains_kustomization(
        self, tmp_path, sequential_meta, router_code, project, template_dir
    ):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")

        kust_path = tmp_path / "manifests" / "base" / "kustomization.yaml"
        assert kust_path.exists()

        kust = yaml.safe_load(kust_path.read_text())
        assert kust["kind"] == "Kustomization"
        assert "resources" in kust

    def test_base_contains_actor_manifests(
        self, tmp_path, sequential_meta, router_code, project, template_dir
    ):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")

        base = tmp_path / "manifests" / "base"
        assert (base / "asyncactor-start-my-flow.yaml").exists()
        assert (base / "asyncactor-handler-a.yaml").exists()
        assert (base / "asyncactor-handler-b.yaml").exists()

    def test_actor_manifest_has_correct_metadata(
        self, tmp_path, sequential_meta, router_code, project, template_dir
    ):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")

        actor = yaml.safe_load(
            (tmp_path / "manifests" / "base" / "asyncactor-handler-a.yaml").read_text()
        )
        assert actor["apiVersion"] == "asya.sh/v1alpha1"
        assert actor["kind"] == "AsyncActor"
        assert actor["metadata"]["name"] == "handler-a"
        assert actor["metadata"]["namespace"] == "test-ns"
        assert actor["metadata"]["labels"]["asya.sh/flow"] == "my-flow"

    def test_handler_image_is_fully_resolved(
        self, tmp_path, sequential_meta, router_code, project, template_dir
    ):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")

        actor = yaml.safe_load(
            (tmp_path / "manifests" / "base" / "asyncactor-handler-a.yaml").read_text()
        )
        assert actor["spec"]["image"] == "ghcr.io/test-org/handler-a:latest"

    def test_router_actor_uses_router_image(
        self, tmp_path, sequential_meta, router_code, project, template_dir
    ):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")

        actor = yaml.safe_load(
            (tmp_path / "manifests" / "base" / "asyncactor-start-my-flow.yaml").read_text()
        )
        assert actor["spec"]["image"] == "python:3.13-slim"
        assert actor["spec"]["handler"] == "routers.start_my_flow"
        assert actor["metadata"]["labels"]["asya.sh/flow-role"] == "entry"

    def test_router_actor_has_handler_env(
        self, tmp_path, sequential_meta, router_code, project, template_dir
    ):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")

        actor = yaml.safe_load(
            (tmp_path / "manifests" / "base" / "asyncactor-start-my-flow.yaml").read_text()
        )
        env = actor["spec"]["env"]
        env_names = {e["name"] for e in env}
        assert "ASYA_HANDLER_HANDLER_A" in env_names
        assert "ASYA_HANDLER_HANDLER_B" in env_names

    def test_configmap_contains_router_code(
        self, tmp_path, sequential_meta, router_code, project, template_dir
    ):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")

        cm = yaml.safe_load(
            (tmp_path / "manifests" / "base" / "configmap-routers.yaml").read_text()
        )
        assert cm["kind"] == "ConfigMap"
        assert cm["metadata"]["name"] == "my-flow-routers"
        assert "routers.py" in cm["data"]
        assert "start_my_flow" in cm["data"]["routers.py"]

    def test_recompile_regenerates_base(
        self, tmp_path, sequential_meta, router_code, project, template_dir
    ):
        out = tmp_path / "manifests"
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)

        templater.stamp(out)
        (out / "base" / "stale.yaml").write_text("stale")

        templater.stamp(out)
        assert not (out / "base" / "stale.yaml").exists()
        assert (out / "base" / "asyncactor-start-my-flow.yaml").exists()


class TestCommonLayer:
    def test_common_created_on_first_stamp(
        self, tmp_path, sequential_meta, router_code, project, template_dir
    ):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")

        kust = yaml.safe_load(
            (tmp_path / "manifests" / "common" / "kustomization.yaml").read_text()
        )
        assert kust["resources"] == ["../base"]

    def test_common_preserved_on_recompile(
        self, tmp_path, sequential_meta, router_code, project, template_dir
    ):
        out = tmp_path / "manifests"
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)

        templater.stamp(out)
        (out / "common" / "my-patch.yaml").write_text("user-patch")
        templater.stamp(out)
        assert (out / "common" / "my-patch.yaml").read_text() == "user-patch"


class TestOverlaysLayer:
    def test_no_overlays_without_contexts(
        self, tmp_path, sequential_meta, router_code, project, template_dir
    ):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")
        assert not (tmp_path / "manifests" / "overlays").exists()

    def test_overlays_created_from_contexts(
        self, tmp_path, sequential_meta, router_code, project_with_contexts, template_dir
    ):
        templater = _make_templater(
            "my-flow", sequential_meta, router_code, project_with_contexts, template_dir
        )
        templater.stamp(tmp_path / "manifests")

        for ctx in ("stg", "prod"):
            kust = yaml.safe_load(
                (tmp_path / "manifests" / "overlays" / ctx / "kustomization.yaml").read_text()
            )
            assert kust["resources"] == ["../../common"]


class TestIdempotency:
    def test_identical_output_on_repeated_compile(
        self, tmp_path, sequential_meta, router_code, project, template_dir
    ):
        out = tmp_path / "manifests"
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)

        templater.stamp(out)
        first_run = {}
        for f in (out / "base").iterdir():
            first_run[f.name] = f.read_text()

        templater.stamp(out)
        for f in (out / "base").iterdir():
            assert f.read_text() == first_run[f.name], f"Content changed for {f.name}"


class TestReturnedFiles:
    def test_stamp_returns_generated_paths(
        self, tmp_path, sequential_meta, router_code, project, template_dir
    ):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        generated = templater.stamp(tmp_path / "manifests")

        assert any("base/kustomization.yaml" in g for g in generated)
        assert any("base/configmap-routers.yaml" in g for g in generated)
        assert any("common/kustomization.yaml" in g for g in generated)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/a.yushkovskiy/gh/dh/asya/.worktrees/.worktrees/compiler-simplify/gml9.phase-2-orchestrator-interfaces-manifests-cli && uv run --project src/asya-lab pytest src/asya-lab/tests/test_stamper.py -v --no-cov`
Expected: FAIL (ManifestTemplater doesn't accept `codegen_meta`)

- [ ] **Step 3: Rewrite ManifestTemplater**

In `src/asya-lab/asya_lab/compiler/templater.py`:

1. Remove the `try/except` Router import (lines 24-27)
2. Remove the local `ActorInfo` dataclass — import from `asya_lab.flow.types` instead
3. Add imports: `from asya_lab.flow.codegen import CodegenMeta, ROUTER_PREFIXES` and `from asya_lab.flow.types import ActorInfo`
4. Replace `__init__` parameter `routers: list[Router]` with `codegen_meta: CodegenMeta`
5. Store `self.codegen_meta = codegen_meta` instead of `self.routers`
6. Update `_ROUTER_PREFIXES` to import from codegen: `_ROUTER_PREFIXES = ROUTER_PREFIXES`
7. Rewrite `_collect_actors()`:

```python
    def _collect_actors(self) -> list[ActorInfo]:
        """Collect all actors from the compiled flow."""
        context = self.project.build_template_context()
        router_image = context.get("router_image", "python:3.13-slim")
        handler_actors: dict[str, ActorInfo] = {}
        router_actors: list[ActorInfo] = []

        for router_name in self.codegen_meta.router_names:
            refs = self.codegen_meta.router_refs.get(router_name, [])
            handler_env = self._build_handler_env_from_refs(refs)

            router_actors.append(
                ActorInfo(
                    name=self._to_k8s_name(router_name),
                    handler=f"routers.{router_name}",
                    image=router_image,
                    flow_role=self._router_flow_role(router_name),
                    env=handler_env,
                    is_generated=True,
                )
            )

            for actor_name in refs:
                if self._is_router_name(actor_name):
                    continue
                if actor_name not in handler_actors:
                    image = self.project.resolve_image(actor_name)
                    k8s_name = self._to_k8s_name(actor_name)
                    handler = self.import_map.get(actor_name, actor_name)
                    handler_actors[actor_name] = ActorInfo(
                        name=k8s_name,
                        handler=handler,
                        image=image,
                        flow_role="actor",
                    )

        return router_actors + list(handler_actors.values())

    def _build_handler_env_from_refs(self, refs: list[str]) -> list[dict[str, str]]:
        """Build ASYA_HANDLER_* env vars from a list of referenced actor names."""
        seen: set[str] = set()
        env: list[dict[str, str]] = []
        for actor_name in refs:
            if actor_name in seen:
                continue
            seen.add(actor_name)
            env_var_name = f"ASYA_HANDLER_{actor_name.upper().replace('-', '_')}"
            if self._is_router_name(actor_name):
                handler = f"routers.{actor_name}"
            else:
                handler = self.import_map.get(actor_name, actor_name)
            env.append({"name": env_var_name, "value": handler})
        return env
```

8. Remove `_get_referenced_actors()` and `_build_handler_env()` methods (replaced by above)
9. Update `_router_flow_role()` to use spec vocabulary (`"entry"` not `"entrypoint"`):
```python
    def _router_flow_role(self, name: str) -> str:
        if name.startswith("start_"):
            return "entry"
        return "router"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/a.yushkovskiy/gh/dh/asya/.worktrees/.worktrees/compiler-simplify/gml9.phase-2-orchestrator-interfaces-manifests-cli && uv run --project src/asya-lab pytest src/asya-lab/tests/test_stamper.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/asya-lab/asya_lab/compiler/templater.py src/asya-lab/tests/test_stamper.py
git commit -m "refactor(templater): replace Router dependency with CodegenMeta"
```

---

## Task 4: Rewrite FlowCompiler for 5-step pipeline

**Files:**
- Modify: `src/asya-lab/asya_lab/flow/compiler.py`
- Modify: `testing/component/flow-compiler/tests/test_compiler_api.py`

The compiler gains step 3 (manifest generation) and returns FlowInfo. It accepts an optional `AsyaProject` for path resolution and manifest stamping.

- [ ] **Step 1: Write test for new compile_file returning FlowInfo**

Add to `testing/component/flow-compiler/tests/test_compiler_api.py`:

```python
class TestFlowInfo:
    """Tests for FlowInfo returned by compile_file."""

    def test_compile_file_returns_flow_info(self, tmp_path):
        from asya_lab.flow.types import FlowInfo

        source = tmp_path / "my_flow.py"
        source.write_text('''
from asya_lab.flow import flow

async def handler_a(p): return p
async def handler_b(p): return p

@flow
async def my_flow(p):
    p = await handler_a(p)
    p = await handler_b(p)
    return p
''')

        compiler = FlowCompiler(verbose=False)
        result = compiler.compile_file(str(source), str(tmp_path / "out"), overwrite=True)

        assert isinstance(result, FlowInfo)
        assert result.flow_name == "my-flow"
        assert result.flow_function == "my_flow"
        assert result.routers_path.exists()
        assert result.dot is not None
        assert result.mermaid is not None
        assert len(result.actors) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/a.yushkovskiy/gh/dh/asya/.worktrees/.worktrees/compiler-simplify/gml9.phase-2-orchestrator-interfaces-manifests-cli && uv run --project src/asya-lab pytest testing/component/flow-compiler/tests/test_compiler_api.py::TestFlowInfo -v --no-cov`
Expected: FAIL (compile_file returns str, not FlowInfo)

- [ ] **Step 3: Rewrite compiler.py**

Key changes to `src/asya-lab/asya_lab/flow/compiler.py`:

1. Add imports:
```python
from asya_lab.flow.types import ActorInfo, FlowInfo
from asya_lab.flow.codegen import CodegenMeta
```

2. Add `project` parameter to `__init__`:
```python
    def __init__(
        self,
        verbose: bool = False,
        max_iterations: int = 100,
        rule_engine: RuleEngine | None = None,
        project: AsyaProject | None = None,
    ):
        # ... existing init ...
        self._project = project
        self._codegen_meta: CodegenMeta | None = None
```

3. Update `compile()` to also store CodegenMeta:
```python
    def compile(self, source_code: str, filename: str, output_file: str | None = None) -> str:
        # Step 1: Parse
        result = self._parse(source_code, filename)
        self._parse_result = result

        # Step 2: CodeGen
        codegen = CodeGenerator(result, filename, output_file)
        code = codegen.generate()
        self._generated_code = code
        self._codegen_meta = codegen.get_meta()

        # Step 3: Analyze
        handler_sources = self._extract_handler_sources(source_code, result.actors)
        self._graph_data = analyze(code, handler_sources)
        self.warnings.extend(self._graph_data.warnings)

        self.flow_name = result.flow_name
        return code
```

4. Update `compile_file()` to return `FlowInfo`:
```python
    def compile_file(self, source_file: str, output_dir: str, overwrite: bool = False) -> FlowInfo:
        source_path = Path(source_file)
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_file}")

        output_path = Path(output_dir)
        if output_path.exists():
            if not output_path.is_dir():
                raise ValueError(f"Output path exists and is not a directory: {output_dir}")
            if not overwrite and any(output_path.iterdir()):
                raise ValueError(f"Output directory is not empty: {output_dir}")

        output_path.mkdir(parents=True, exist_ok=True)

        source_code = source_path.read_text()
        compiled_file = output_path / "routers.py"
        compiled_code = self.compile(source_code, str(source_path), str(compiled_file))

        # Step 2b: Write compiled code
        compiled_file.write_text(compiled_code)

        # Step 3: Generate manifests (if project available)
        manifests_dir = self._stamp_manifests(output_path)

        # Step 4: Generate graph outputs
        dot, mermaid, json_content, svg = self._generate_outputs(output_path)

        # Build FlowInfo
        flow_function = self.flow_name or source_path.stem
        flow_name = flow_function.replace("_", "-")

        actors = self._build_actor_infos()

        return FlowInfo(
            flow_name=flow_name,
            flow_function=flow_function,
            routers_path=compiled_file,
            manifests_dir=manifests_dir or output_path,
            graph=to_json(self._graph_data, flow_function) if self._graph_data else {},
            dot=dot,
            mermaid=mermaid,
            svg=svg,
            actors=actors,
            warnings=list(self.warnings),
        )

    def _generate_outputs(self, output_path: Path) -> tuple[str, str, str, str | None]:
        """Generate DOT, Mermaid, JSON, and optionally SVG."""
        if not self.flow_name or self._graph_data is None:
            return "", "", "", None

        dot_content = to_dot(self._graph_data, self.flow_name)
        mmd_content = to_mermaid(self._graph_data, self.flow_name)
        json_content = to_json_string(self._graph_data, self.flow_name)

        (output_path / "flow.dot").write_text(dot_content)
        (output_path / "flow.mmd").write_text(mmd_content)
        (output_path / "graph.json").write_text(json_content)

        svg_content = self._try_render_svg(output_path)
        return dot_content, mmd_content, json_content, svg_content

    def _try_render_svg(self, output_path: Path) -> str | None:
        """Try to render SVG from DOT file. Returns SVG content or None."""
        dot_file = output_path / "flow.dot"
        svg_file = output_path / "flow.svg"
        try:
            import re
            import subprocess  # nosec B404

            subprocess.run(["dot", "-V"], capture_output=True, check=True)  # nosec B603, B607
            subprocess.run(  # nosec B603, B607
                ["dot", "-Tsvg", str(dot_file), "-o", str(svg_file)],
                capture_output=True, text=True, check=True,
            )
            # Strip graphviz version comment to avoid SVG oscillation across versions
            content = svg_file.read_text()
            content = re.sub(
                r"<!-- Generated by graphviz version .+?\n -->",
                "<!-- Generated by graphviz\n -->",
                content,
            )
            svg_file.write_text(content)
            return content
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass
        return None

    def _stamp_manifests(self, compiled_dir: Path) -> Path | None:
        """Step 3: Generate kustomize manifests if project is available.

        All paths come from AsyaProject config — no hard-coded paths.
        """
        if self._project is None or self._codegen_meta is None:
            return None
        if self._codegen_meta.single_actor is not None:
            return None  # Single-actor flows don't need manifests

        from asya_lab.compiler.templater import ManifestTemplater

        flow_function = self.flow_name
        if not flow_function:
            return None

        flow_name = flow_function.replace("_", "-")

        # All paths resolved from project config, not hard-coded.
        # NOTE: compiler.templates is a new config key added in this PR.
        # Default value in example configs: ".asya/compiler/templates"
        manifests_dir = self._project.resolve_path("compiler.manifests") / flow_name
        templates_dir = self._project.resolve_path("compiler.templates")
        router_code = self._generated_code or ""

        actor_template = templates_dir / "actor.yaml"
        if not actor_template.exists():
            return None

        def _opt(name: str) -> Path | None:
            p = templates_dir / name
            return p if p.exists() else None

        templater = ManifestTemplater(
            flow_name=flow_name,
            flow_function=flow_function,
            codegen_meta=self._codegen_meta,
            router_code=router_code,
            project=self._project,
            actor_template_path=actor_template,
            router_template_path=_opt("router.yaml"),
            configmap_routers_template_path=_opt("configmap_routers.yaml"),
            kustomization_template_path=_opt("kustomization.yaml"),
            import_map=self.import_map,
        )

        templater.stamp(manifests_dir)
        return manifests_dir

    def _build_actor_infos(self) -> list[ActorInfo]:
        """Build ActorInfo list from codegen metadata and graph data."""
        if self._codegen_meta is None:
            return []

        actors = []
        flow_roles = self._detect_flow_roles()

        for router_name in self._codegen_meta.router_names:
            k8s_name = router_name.replace("_", "-")
            actors.append(ActorInfo(
                name=k8s_name,
                handler=f"routers.{router_name}",
                image="",  # resolved by templater
                flow_role=flow_roles.get(router_name, "router"),
                is_generated=True,
            ))

        from asya_lab.flow.codegen import ROUTER_PREFIXES

        for handler_name in sorted(self._codegen_meta.all_handler_names):
            if any(handler_name.startswith(p) for p in ROUTER_PREFIXES):
                continue
            k8s_name = handler_name.replace("_", "-")
            actors.append(ActorInfo(
                name=k8s_name,
                handler=self.import_map.get(handler_name, handler_name),
                image="",  # resolved by templater
                flow_role=flow_roles.get(handler_name, "actor"),
            ))

        return actors

    def _detect_flow_roles(self) -> dict[str, str]:
        """Detect flow roles from graph data."""
        if self._graph_data is None:
            return {}
        roles: dict[str, str] = {}
        for node in self._graph_data.nodes:
            node_id = node.get("id", "")
            role = node.get("flow_role", "")
            if role:
                roles[node_id] = role
        return roles
```

5. Add `to_json` import at top:
```python
from asya_lab.flow.graphgen import to_dot, to_json, to_json_string, to_mermaid
```

- [ ] **Step 4: Update existing tests that expect str return from compile_file**

In `testing/component/flow-compiler/tests/test_compiler_api.py`, update both tests that use `compile_file`:

- `test_compile_file_success`: Change `result_path = compiler.compile_file(...)` and `Path(result_path)` assertions to use `result.routers_path`
- `test_compile_file_creates_output_directory`: Same pattern — `result.routers_path.parent.exists()` instead of checking the string path

```python
    def test_compile_file_success(self, simple_flow_file, tmp_path):
        compiler = FlowCompiler(verbose=False)
        result = compiler.compile_file(str(simple_flow_file), str(tmp_path / "output"), overwrite=True)
        assert result.routers_path.exists()
        assert result.routers_path.name == "routers.py"
        assert "def start_flow(" in result.routers_path.read_text()
```

- [ ] **Step 5: Run all tests**

Run: `cd /Users/a.yushkovskiy/gh/dh/asya/.worktrees/.worktrees/compiler-simplify/gml9.phase-2-orchestrator-interfaces-manifests-cli && uv run --project src/asya-lab pytest src/asya-lab/tests/ testing/component/flow-compiler/tests/ -v --no-cov -x`
Expected: PASS (fix any remaining failures)

- [ ] **Step 6: Commit**

```bash
git add src/asya-lab/asya_lab/flow/compiler.py testing/component/flow-compiler/tests/
git commit -m "feat(compiler): 5-step pipeline returning FlowInfo with manifest generation"
```

---

## Task 5: Update flow/__init__.py + SDK compile() function

**Files:**
- Modify: `src/asya-lab/asya_lab/flow/__init__.py`

- [ ] **Step 1: Write test for SDK compile()**

```python
# Add to src/asya-lab/tests/test_flow_types.py

def test_sdk_compile_function(tmp_path):
    """Test the top-level compile() SDK function."""
    from asya_lab.flow import compile as flow_compile
    from asya_lab.flow.types import FlowInfo

    source = tmp_path / "simple_flow.py"
    source.write_text('''
from asya_lab.flow import flow

async def step_a(p): return p

@flow
async def simple(p):
    p = await step_a(p)
    return p
''')

    result = flow_compile(str(source), output_dir=str(tmp_path / "out"))
    assert isinstance(result, FlowInfo)
    assert result.routers_path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/a.yushkovskiy/gh/dh/asya/.worktrees/.worktrees/compiler-simplify/gml9.phase-2-orchestrator-interfaces-manifests-cli && uv run --project src/asya-lab pytest src/asya-lab/tests/test_flow_types.py::test_sdk_compile_function -v --no-cov`
Expected: FAIL (compile not exported)

- [ ] **Step 3: Implement compile() and update exports**

```python
# src/asya-lab/asya_lab/flow/__init__.py
"""Flow DSL compiler for Asya framework."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from asya_lab.flow.compiler import FlowCompiler
from asya_lab.flow.errors import FlowCompileError
from asya_lab.flow.types import ActorInfo, FlowInfo


_F = TypeVar("_F", bound=Callable)


def flow(func: _F) -> _F:
    """Mark a function as the flow entry point for the Asya flow compiler.

    This decorator is a no-op at runtime -- it returns the function unchanged.
    The flow compiler uses it as an AST marker to identify the entry-point
    function when compiling a flow file.

    Usage::

        @flow
        def my_pipeline(p: dict) -> dict:
            p = step_one(p)
            p = step_two(p)
            return p
    """
    return func


def compile(
    source: str,
    *,
    output_dir: str | None = None,
    flow_name: str | None = None,
    plot: bool = True,
    verbose: bool = False,
) -> FlowInfo:
    """Compile a flow source file into routers + manifests + graph.

    Args:
        source: Path to the flow .py file.
        output_dir: Override output directory. Defaults to config-resolved path.
        flow_name: Override inferred flow name.
        plot: Generate SVG rendering (requires graphviz).
        verbose: Print progress messages.

    Returns:
        FlowInfo with all compilation artifacts.
    """
    source_path = Path(source).resolve()

    # Try to load project config
    project = None
    rule_engine = None
    try:
        from asya_lab.config.project import AsyaProject

        project = AsyaProject.from_dir(source_path.parent)
        rule_engine = project.load_rules()
    except FileNotFoundError:
        pass

    compiler = FlowCompiler(
        verbose=verbose,
        rule_engine=rule_engine,
        project=project,
    )

    if output_dir is None:
        # Resolve from config or use default
        if project:
            try:
                flow_function = _infer_flow_function(source_path)
                output_dir = str(project.resolve_path("compiler.routers") / (flow_function or source_path.stem))
            except Exception:
                output_dir = str(source_path.parent / "compiled" / source_path.stem)
        else:
            output_dir = str(source_path.parent / "compiled" / source_path.stem)

    return compiler.compile_file(str(source_path), output_dir, overwrite=True)


def _infer_flow_function(source_path: Path) -> str | None:
    """Quick scan for @flow decorator to get function name before full compile."""
    import ast

    try:
        tree = ast.parse(source_path.read_text())
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Name) and dec.id == "flow":
                    return node.name
    return None


__all__ = ["ActorInfo", "FlowCompileError", "FlowCompiler", "FlowInfo", "compile", "flow"]
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/a.yushkovskiy/gh/dh/asya/.worktrees/.worktrees/compiler-simplify/gml9.phase-2-orchestrator-interfaces-manifests-cli && uv run --project src/asya-lab pytest src/asya-lab/tests/test_flow_types.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/asya-lab/asya_lab/flow/__init__.py src/asya-lab/tests/test_flow_types.py
git commit -m "feat(sdk): add compile() function and export FlowInfo/ActorInfo"
```

---

## Task 6: Update compile_cli.py and clean up flow_cli.py

**Files:**
- Modify: `src/asya-lab/asya_lab/compile_cli.py`
- Modify: `src/asya-lab/asya_lab/flow_cli.py`
- Modify: `src/asya-lab/tests/test_compile_cli.py`

The CLI now uses FlowCompiler.compile_file() which handles manifests internally.

- [ ] **Step 1: Simplify compile_cli.py**

Rewrite `_compile_flow_file()` to use `compile_file()` directly — single compile path, no double-compile:

```python
def _compile_flow_file(
    target: str,
    flow_name_override: str | None,
    output_dir: str | None,
    plot: bool,
    plot_format: str,
    verbose: bool,
    force: bool,
    strict: bool = False,
) -> None:
    """Compile a flow from a .py source file."""
    from asya_lab.flow import _infer_flow_function

    source_path = Path(target).resolve()

    # Load project config (if .asya/ exists)
    project = None
    rule_engine = None
    try:
        project = AsyaProject.from_dir(source_path.parent)
        rule_engine = project.load_rules()
    except FileNotFoundError:
        pass

    # Infer flow function name via lightweight AST scan (no full compile)
    flow_function = _infer_flow_function(source_path) or source_path.stem

    if flow_name_override:
        flow_name = flow_name_override
    else:
        flow_name = flow_function.replace("_", "-")

    # Resolve compiled output dir from config or CLI override
    if output_dir:
        compiled_dir = Path(output_dir).resolve()
    else:
        compiled_dir = _resolve_compiled_dir(source_path, flow_function)

    # Single compile call — handles code + manifests + graph outputs
    compiler = FlowCompiler(verbose=verbose, rule_engine=rule_engine, project=project)
    result = compiler.compile_file(str(source_path), str(compiled_dir), overwrite=True)

    if verbose:
        click.echo(f"[+] Compiled flow to: {result.routers_path}")
        click.echo(f"[+] Flow name: '{flow_name}'")

        actor = compiler.single_actor_name
        if actor is not None:
            click.echo("[+] Single-actor flow: no router actor needed")

        if result.manifests_dir and result.manifests_dir != compiled_dir:
            click.echo(f"[+] Stamped manifests to: {result.manifests_dir}")

    warnings = result.warnings
    if warnings:
        for w in warnings:
            click.echo(f"[!] {w}", err=True)
        if strict:
            click.echo(f"[-] {len(warnings)} warning(s) in --strict mode", err=True)
            sys.exit(1)
```

- [ ] **Step 2: Remove _stamp_manifests from flow_cli.py**

Remove `_stamp_manifests()` function (lines 13-83) and its import in compile_cli.py. Keep only `validate()` command.

```python
# src/asya-lab/asya_lab/flow_cli.py
"""CLI commands for the flow compiler."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from asya_lab.flow import FlowCompileError, FlowCompiler


@click.command("validate")
@click.argument("flow_file")
@click.option("--verbose", "-v", is_flag=True, help="Show verbose output")
@click.option("--strict", is_flag=True, help="Treat warnings as errors")
def validate(flow_file, verbose, strict):
    """Validate flow by compiling and checking graph invariants."""
    try:
        compiler = FlowCompiler(verbose=verbose)

        source_path = Path(flow_file)
        if not source_path.exists():
            click.echo(f"[-] Source file not found: {flow_file}", err=True)
            sys.exit(1)

        source_code = source_path.read_text()
        compiler.compile(source_code, str(source_path))

        click.echo(f"[+] Flow is valid: {flow_file}")

        warnings = compiler.get_warnings()
        if warnings:
            for w in warnings:
                click.echo(f"[!] {w}", err=True)
            if strict:
                click.echo(f"[-] {len(warnings)} warning(s) in --strict mode", err=True)
                sys.exit(1)

    except FlowCompileError as e:
        click.echo("[-] Validation failed:\n", err=True)
        click.echo(str(e), err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"[-] Unexpected error: {e}", err=True)
        if verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)
```

- [ ] **Step 3: Remove _stamp_manifests import from compile_cli.py**

Remove `from asya_lab.flow_cli import _stamp_manifests` (line 45 of current compile_cli.py).

- [ ] **Step 4: Run CLI tests**

Run: `cd /Users/a.yushkovskiy/gh/dh/asya/.worktrees/.worktrees/compiler-simplify/gml9.phase-2-orchestrator-interfaces-manifests-cli && uv run --project src/asya-lab pytest src/asya-lab/tests/test_compile_cli.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/asya-lab/asya_lab/compile_cli.py src/asya-lab/asya_lab/flow_cli.py src/asya-lab/tests/test_compile_cli.py
git commit -m "refactor(cli): integrate manifest stamping into compiler pipeline, remove broken _stamp_manifests"
```

---

## Task 7: Run full test suite + fix failures

**Files:**
- Various test files

- [ ] **Step 1: Run unit tests**

Run: `cd /Users/a.yushkovskiy/gh/dh/asya/.worktrees/.worktrees/compiler-simplify/gml9.phase-2-orchestrator-interfaces-manifests-cli && uv run --project src/asya-lab pytest src/asya-lab/tests/ --no-cov -v -x`

- [ ] **Step 2: Run component tests**

Run: `cd /Users/a.yushkovskiy/gh/dh/asya/.worktrees/.worktrees/compiler-simplify/gml9.phase-2-orchestrator-interfaces-manifests-cli && uv run --project src/asya-lab pytest testing/component/flow-compiler/tests/ --no-cov -v -x`

- [ ] **Step 3: Fix any failures**

Address test failures one by one. Common expected issues:
- `test_compiler_api.py`: `compile_file` return type changed to FlowInfo
- `test_compilation_e2e.py`: May need updates for new return type
- Import changes from removed `_stamp_manifests`

- [ ] **Step 4: Run lint**

Run: `cd /Users/a.yushkovskiy/gh/dh/asya/.worktrees/.worktrees/compiler-simplify/gml9.phase-2-orchestrator-interfaces-manifests-cli && make lint 2>&1 | head -50`

- [ ] **Step 5: Commit fixes**

```bash
git add -A
git commit -m "fix(tests): update tests for Phase 2 pipeline changes"
```

---

## Task 8: Recompile example flows

**Files:**
- `examples/flows/compiled/*/` — regenerated output files

- [ ] **Step 1: Run pre-commit compile-flows hook**

Run: `cd /Users/a.yushkovskiy/gh/dh/asya/.worktrees/.worktrees/compiler-simplify/gml9.phase-2-orchestrator-interfaces-manifests-cli && bash .pre-commit-hooks/compile-flows.sh`

This recompiles all example flows and shows if any output changed.

- [ ] **Step 2: Review changes**

Run: `cd /Users/a.yushkovskiy/gh/dh/asya/.worktrees/.worktrees/compiler-simplify/gml9.phase-2-orchestrator-interfaces-manifests-cli && git diff --stat examples/flows/compiled/`

Verify changes are expected (no regressions in generated code).

- [ ] **Step 3: Commit**

```bash
git add examples/flows/compiled/
git commit -m "chore: recompile example flows with Phase 2 pipeline"
```

---

## Task 9: Push and create PR

- [ ] **Step 1: Final test run**

Run: `cd /Users/a.yushkovskiy/gh/dh/asya/.worktrees/.worktrees/compiler-simplify/gml9.phase-2-orchestrator-interfaces-manifests-cli && uv run --project src/asya-lab pytest src/asya-lab/tests/ testing/component/flow-compiler/tests/ --no-cov -v`

- [ ] **Step 2: Push**

```bash
cd /Users/a.yushkovskiy/gh/dh/asya/.worktrees/.worktrees/compiler-simplify/gml9.phase-2-orchestrator-interfaces-manifests-cli
git pull --rebase origin main
git aint sync
git push -u origin compiler-simplify/gml9.phase-2-orchestrator-interfaces-manifests-cli
```

- [ ] **Step 3: Create PR**

```bash
gh pr create --title "feat(compiler): Phase 2 — 5-step pipeline with manifest generation and FlowInfo" --body "$(cat <<'EOF'
## Summary
- 5-step compiler pipeline: Parse → CodeGen → Manifests → Analyze → GraphGen
- FlowInfo + ActorInfo dataclasses for structured compiler output
- ManifestTemplater rewritten to use CodegenMeta (removes deleted Router dependency)
- SDK `compile()` function mirroring CLI
- Broken `_stamp_manifests()` removed, manifest generation integrated into compiler

## Test plan
- [ ] Unit tests pass (`make test-unit`)
- [ ] Component tests pass (flow-compiler suite)
- [ ] Example flows recompile without regression
- [ ] E2E tests pass in CI
EOF
)"
```

- [ ] **Step 4: Tag aint with PR number**

```bash
git aint update gml9 --add-tag "pr:<PR_NUMBER>"
```

---

## Task 10: Code review

After all code is pushed, dispatch an Opus subagent to review the complete diff against the spec.

- [ ] **Step 1: Run code review**

Dispatch a `superpowers:code-reviewer` subagent to review all changes on the branch against:
- Spec: `.aint/aints/compiler-simplify/active.gml9.phase-2-orchestrator-interfaces-manifests-cli.md`
- RFC: `.aint/aints/compiler-simplify/rfc.md`

Review should check:
- All paths come from `AsyaProject` config (no hard-coded paths)
- `flow_role` vocabulary matches spec (`entry`/`exit`/`entryexit`/`router`/`actor`)
- Unified `ActorInfo` (no duplicate class)
- `ROUTER_PREFIXES` shared constant
- No double compile in CLI
- Tests adequate for new interfaces

Write findings to `/tmp/phase2-code-review.md`.

- [ ] **Step 2: Address review findings**

Fix any issues found. Commit and push fixes.
