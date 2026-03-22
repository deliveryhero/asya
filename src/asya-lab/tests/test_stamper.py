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
    templates_dir = asya_dir / "templates"
    templates_dir.mkdir(parents=True)

    template = {
        "apiVersion": "asya.sh/v1alpha1",
        "kind": "AsyncActor",
        "metadata": {
            "name": "{{ actor_name }}",
            "namespace": "{{ namespace }}",
            "labels": {
                "asya.sh/flow": "{{ flow_name }}",
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
    (templates_dir / "configmap-routers.yaml").write_text(yaml.dump(configmap_template, sort_keys=False))

    kustomization_template = {
        "apiVersion": "kustomize.config.k8s.io/v1beta1",
        "kind": "Kustomization",
    }
    (templates_dir / "kustomization.yaml").write_text(yaml.dump(kustomization_template, sort_keys=False))

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
    return "# Auto-generated\ndef start_my_flow(payload):\n    yield payload\n"


def _make_templater(flow_name, codegen_meta, router_code, project, template_path, flow_function=None):
    templates_dir = template_path.parent
    router_template = templates_dir / "router.yaml"
    return ManifestTemplater(
        flow_name=flow_name,
        flow_function=flow_function or flow_name.replace("-", "_"),
        codegen_meta=codegen_meta,
        router_code=router_code,
        project=project,
        actor_template_path=template_path,
        router_template_path=router_template if router_template.exists() else None,
        configmap_routers_template_path=templates_dir / "configmap-routers.yaml",
        kustomization_template_path=templates_dir / "kustomization.yaml",
    )


class TestBaseLayer:
    def test_base_dir_created(self, tmp_path, sequential_meta, router_code, project, template_dir):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")
        assert (tmp_path / "manifests" / "base").is_dir()

    def test_base_contains_kustomization(self, tmp_path, sequential_meta, router_code, project, template_dir):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")

        kust_path = tmp_path / "manifests" / "base" / "kustomization.yaml"
        assert kust_path.exists()

        kust = yaml.safe_load(kust_path.read_text())
        assert kust["kind"] == "Kustomization"
        assert "resources" in kust

    def test_base_contains_actor_manifests(self, tmp_path, sequential_meta, router_code, project, template_dir):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")

        base = tmp_path / "manifests" / "base"
        # 1 router actor + 2 handler actors + configmap + kustomization
        assert (base / "asya-start-my-flow.yaml").exists()
        assert (base / "asya-actor-handler-a.yaml").exists()
        assert (base / "asya-actor-handler-b.yaml").exists()

    def test_actor_manifest_has_correct_metadata(self, tmp_path, sequential_meta, router_code, project, template_dir):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")

        actor = yaml.safe_load((tmp_path / "manifests" / "base" / "asya-actor-handler-a.yaml").read_text())
        assert actor["apiVersion"] == "asya.sh/v1alpha1"
        assert actor["kind"] == "AsyncActor"
        assert actor["metadata"]["name"] == "actor-handler-a"
        assert actor["metadata"]["namespace"] == "test-ns"
        assert actor["metadata"]["labels"]["asya.sh/flow"] == "my-flow"
        # Middle handler: no asya.sh/role, no asya.sh/generated
        assert "asya.sh/role" not in actor["metadata"]["labels"]
        assert "asya.sh/generated" not in actor["metadata"]["labels"]

    def test_handler_image_is_fully_resolved(self, tmp_path, sequential_meta, router_code, project, template_dir):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")

        actor = yaml.safe_load((tmp_path / "manifests" / "base" / "asya-actor-handler-a.yaml").read_text())
        image = actor["spec"]["image"]
        # Manifests are real K8s resources — no OmegaConf interpolations allowed
        assert "${" not in image
        assert image == "ghcr.io/test-org/handler-a:latest"

    def test_router_actor_uses_router_image(self, tmp_path, sequential_meta, router_code, project, template_dir):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")

        actor = yaml.safe_load((tmp_path / "manifests" / "base" / "asya-start-my-flow.yaml").read_text())
        assert actor["spec"]["image"] == "python:3.13-slim"
        assert actor["spec"]["handler"] == "routers.start_my_flow"
        # Start router: has both asya.sh/role and asya.sh/generated
        assert actor["metadata"]["labels"]["asya.sh/role"] == "start"
        assert actor["metadata"]["labels"]["asya.sh/generated"] == "true"

    def test_router_actor_has_handler_env(self, tmp_path, sequential_meta, router_code, project, template_dir):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")

        actor = yaml.safe_load((tmp_path / "manifests" / "base" / "asya-start-my-flow.yaml").read_text())
        env = actor["spec"]["env"]
        env_names = {e["name"] for e in env}
        assert "ASYA_HANDLER_ACTOR_HANDLER_A" in env_names
        assert "ASYA_HANDLER_ACTOR_HANDLER_B" in env_names

    def test_configmap_contains_router_code(self, tmp_path, sequential_meta, router_code, project, template_dir):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")

        cm = yaml.safe_load((tmp_path / "manifests" / "base" / "configmap-routers.yaml").read_text())
        assert cm["kind"] == "ConfigMap"
        assert cm["metadata"]["name"] == "my-flow-routers"
        assert "routers.py" in cm["data"]
        assert "start_my_flow" in cm["data"]["routers.py"]

    def test_kustomization_lists_all_resources(self, tmp_path, sequential_meta, router_code, project, template_dir):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")

        kust = yaml.safe_load((tmp_path / "manifests" / "base" / "kustomization.yaml").read_text())
        resources = kust["resources"]
        assert "configmap-routers.yaml" in resources
        assert "asya-start-my-flow.yaml" in resources
        assert "asya-actor-handler-a.yaml" in resources

    def test_recompile_regenerates_base(self, tmp_path, sequential_meta, router_code, project, template_dir):
        out = tmp_path / "manifests"
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)

        templater.stamp(out)
        # Add a stale file
        (out / "base" / "stale.yaml").write_text("stale")

        templater.stamp(out)
        assert not (out / "base" / "stale.yaml").exists()
        assert (out / "base" / "asya-start-my-flow.yaml").exists()


class TestCommonLayer:
    def test_common_created_on_first_stamp(self, tmp_path, sequential_meta, router_code, project, template_dir):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")

        kust = yaml.safe_load((tmp_path / "manifests" / "common" / "kustomization.yaml").read_text())
        assert kust["resources"] == ["../base"]

    def test_common_preserved_on_recompile(self, tmp_path, sequential_meta, router_code, project, template_dir):
        out = tmp_path / "manifests"
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)

        templater.stamp(out)
        # User adds a patch
        (out / "common" / "my-patch.yaml").write_text("user-patch")
        # Recompile
        templater.stamp(out)
        assert (out / "common" / "my-patch.yaml").exists()
        assert (out / "common" / "my-patch.yaml").read_text() == "user-patch"


class TestOverlaysLayer:
    def test_no_overlays_without_contexts(self, tmp_path, sequential_meta, router_code, project, template_dir):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")
        assert not (tmp_path / "manifests" / "overlays").exists()

    def test_overlays_created_from_contexts(
        self, tmp_path, sequential_meta, router_code, project_with_contexts, template_dir
    ):
        templater = _make_templater("my-flow", sequential_meta, router_code, project_with_contexts, template_dir)
        templater.stamp(tmp_path / "manifests")

        for ctx in ("stg", "prod"):
            kust = yaml.safe_load((tmp_path / "manifests" / "overlays" / ctx / "kustomization.yaml").read_text())
            assert kust["resources"] == ["../../common"]

    def test_overlays_preserved_on_recompile(
        self, tmp_path, sequential_meta, router_code, project_with_contexts, template_dir
    ):
        out = tmp_path / "manifests"
        templater = _make_templater("my-flow", sequential_meta, router_code, project_with_contexts, template_dir)

        templater.stamp(out)
        # User adds a patch to stg overlay
        (out / "overlays" / "stg" / "my-patch.yaml").write_text("stg-patch")
        # Recompile
        templater.stamp(out)
        assert (out / "overlays" / "stg" / "my-patch.yaml").read_text() == "stg-patch"


class TestIdempotency:
    def test_identical_output_on_repeated_compile(self, tmp_path, sequential_meta, router_code, project, template_dir):
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
    def test_stamp_returns_generated_paths(self, tmp_path, sequential_meta, router_code, project, template_dir):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        generated = templater.stamp(tmp_path / "manifests")

        assert any("base/kustomization.yaml" in g for g in generated)
        assert any("base/configmap-routers.yaml" in g for g in generated)
        assert any("common/kustomization.yaml" in g for g in generated)

    def test_second_stamp_skips_existing_common(self, tmp_path, sequential_meta, router_code, project, template_dir):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")
        generated = templater.stamp(tmp_path / "manifests")

        # common/ should not be in second run's generated list
        assert not any("common/" in g for g in generated)


class TestTwoLabelSystem:
    """Test the asya.sh/role + asya.sh/generated label system.

    Two orthogonal labels:
      asya.sh/role: start|end — only on start/end actors
      asya.sh/generated: "true" — only on generated routers
    """

    @pytest.fixture()
    def conditional_meta(self):
        """CodegenMeta for: start -> handler_a -> if_router -> handler_b (end) | handler_c (end)."""
        return CodegenMeta(
            router_names=["start_my_flow", "router_my_flow_line_5_if_1"],
            all_handler_names={"handler_a", "handler_b", "handler_c", "router_my_flow_line_5_if_1"},
            router_refs={
                "start_my_flow": ["handler_a", "handler_b", "handler_c", "router_my_flow_line_5_if_1"],
                "router_my_flow_line_5_if_1": ["handler_a", "handler_b", "handler_c"],
            },
            single_actor=None,
        )

    def _load_actor(self, tmp_path, name):
        return yaml.safe_load((tmp_path / "manifests" / "base" / f"asya-{name}.yaml").read_text())

    def test_start_router_has_role_and_generated(self, tmp_path, sequential_meta, router_code, project, template_dir):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")

        actor = self._load_actor(tmp_path, "start-my-flow")
        labels = actor["metadata"]["labels"]
        assert labels["asya.sh/role"] == "start"
        assert labels["asya.sh/generated"] == "true"

    def test_middle_handler_has_no_role_no_generated(
        self, tmp_path, sequential_meta, router_code, project, template_dir
    ):
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")

        actor = self._load_actor(tmp_path, "actor-handler-a")
        labels = actor["metadata"]["labels"]
        assert "asya.sh/role" not in labels
        assert "asya.sh/generated" not in labels

    def test_middle_router_has_generated_no_role(self, tmp_path, conditional_meta, router_code, project, template_dir):
        templater = _make_templater("my-flow", conditional_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")

        actor = self._load_actor(tmp_path, "router-my-flow-line-5-if-1")
        labels = actor["metadata"]["labels"]
        assert "asya.sh/role" not in labels
        assert labels["asya.sh/generated"] == "true"

    def test_end_handler_has_role_no_generated(self, tmp_path, sequential_meta, router_code, project, template_dir):
        """When flow_roles marks an actor as 'end', manifests get asya.sh/role: end."""
        flow_roles = {"start_my_flow": "start", "handler_a": "actor", "handler_b": "end"}
        templater = _make_templater("my-flow", sequential_meta, router_code, project, template_dir)
        templater.flow_roles = flow_roles
        templater.stamp(tmp_path / "manifests")

        actor = self._load_actor(tmp_path, "actor-handler-b")
        labels = actor["metadata"]["labels"]
        assert labels["asya.sh/role"] == "end"
        assert "asya.sh/generated" not in labels

    def test_all_actors_have_flow_label(self, tmp_path, conditional_meta, router_code, project, template_dir):
        templater = _make_templater("my-flow", conditional_meta, router_code, project, template_dir)
        templater.stamp(tmp_path / "manifests")

        base = tmp_path / "manifests" / "base"
        for path in sorted(base.glob("asya-*.yaml")):
            actor = yaml.safe_load(path.read_text())
            assert actor["metadata"]["labels"]["asya.sh/flow"] == "my-flow", f"{path.name} missing flow label"
