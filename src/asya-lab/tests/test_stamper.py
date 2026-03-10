"""Tests for compiler manifest stamping."""

from __future__ import annotations

import pytest
import yaml
from asya_lab.compiler.stamper import ManifestStamper
from asya_lab.config.config import ConfigLoader
from asya_lab.flow.grouper import Router
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
            "name": "${dynamic:actor}",
            "namespace": "${var.namespace}",
            "labels": {
                "asya.sh/flow": "${dynamic:flow}",
                "asya.sh/flow-role": "${dynamic:flow_role}",
            },
        },
        "spec": {
            "actor": "${dynamic:actor}",
            "image": "${dynamic:image}",
            "handler": "${dynamic:handler}",
            "transport": "${var.transport}",
            "env": "${dynamic:env}",
            "scaling": {
                "enabled": True,
                "minReplicas": 0,
                "maxReplicas": 5,
            },
        },
    }
    (templates_dir / "actor.yaml").write_text(yaml.dump(template, sort_keys=False))

    configmap_template = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": "${dynamic:flow}-routers",
            "namespace": "${var.namespace}",
            "labels": {
                "asya.sh/flow": "${dynamic:flow}",
                "asya.sh/managed-by": "asya-compiler",
            },
        },
        "data": {
            "routers.py": "${dynamic:router_code}",
        },
    }
    (templates_dir / "configmap_routers.yaml").write_text(yaml.dump(configmap_template, sort_keys=False))

    kustomization_template = {
        "apiVersion": "kustomize.config.k8s.io/v1beta1",
        "kind": "Kustomization",
        "resources": "${dynamic:resources}",
    }
    (templates_dir / "kustomization.yaml").write_text(yaml.dump(kustomization_template, sort_keys=False))

    return templates_dir / "actor.yaml"


@pytest.fixture()
def config():
    return OmegaConf.create(
        {
            "var": {
                "namespace": "test-ns",
                "transport": "sqs",
                "router_image": "python:3.13-slim",
                "image_registry": "ghcr.io/test-org",
            },
        }
    )


@pytest.fixture()
def config_with_contexts():
    return OmegaConf.create(
        {
            "var": {
                "namespace": "test-ns",
                "transport": "sqs",
                "router_image": "python:3.13-slim",
                "image_registry": "ghcr.io/test-org",
            },
            "contexts": {
                "stg": {"kubecontext": "stg-cluster"},
                "prod": {"kubecontext": "prod-cluster"},
            },
        }
    )


@pytest.fixture()
def sequential_routers():
    """Routers for a simple sequential flow: start -> handler_a -> handler_b -> end."""
    return [
        Router(
            name="start_my_flow",
            lineno=0,
            true_branch_actors=["handler_a", "handler_b", "end_my_flow"],
        ),
        Router(
            name="end_my_flow",
            lineno=0,
        ),
    ]


@pytest.fixture()
def router_code():
    return "# Auto-generated\ndef start_my_flow(payload):\n    yield payload\n\ndef end_my_flow(payload):\n    yield payload\n"


def _make_stamper(flow_name, routers, router_code, config, template_path, flow_function=None):
    loader = ConfigLoader()
    templates_dir = template_path.parent
    return ManifestStamper(
        flow_name=flow_name,
        flow_function=flow_function or flow_name.replace("-", "_"),
        routers=routers,
        router_code=router_code,
        config=config,
        config_loader=loader,
        template_path=template_path,
        configmap_routers_template_path=templates_dir / "configmap_routers.yaml",
        kustomization_template_path=templates_dir / "kustomization.yaml",
    )


class TestBaseLayer:
    def test_base_dir_created(self, tmp_path, sequential_routers, router_code, config, template_dir):
        stamper = _make_stamper("my-flow", sequential_routers, router_code, config, template_dir)
        stamper.stamp(tmp_path / "manifests")
        assert (tmp_path / "manifests" / "base").is_dir()

    def test_base_contains_kustomization(self, tmp_path, sequential_routers, router_code, config, template_dir):
        stamper = _make_stamper("my-flow", sequential_routers, router_code, config, template_dir)
        stamper.stamp(tmp_path / "manifests")

        kust_path = tmp_path / "manifests" / "base" / "kustomization.yaml"
        assert kust_path.exists()

        kust = yaml.safe_load(kust_path.read_text())
        assert kust["kind"] == "Kustomization"
        assert "resources" in kust

    def test_base_contains_actor_manifests(self, tmp_path, sequential_routers, router_code, config, template_dir):
        stamper = _make_stamper("my-flow", sequential_routers, router_code, config, template_dir)
        stamper.stamp(tmp_path / "manifests")

        base = tmp_path / "manifests" / "base"
        # 2 router actors + 2 handler actors + configmap + kustomization
        assert (base / "start-my-flow.yaml").exists()
        assert (base / "end-my-flow.yaml").exists()
        assert (base / "handler-a.yaml").exists()
        assert (base / "handler-b.yaml").exists()

    def test_actor_manifest_has_correct_metadata(self, tmp_path, sequential_routers, router_code, config, template_dir):
        stamper = _make_stamper("my-flow", sequential_routers, router_code, config, template_dir)
        stamper.stamp(tmp_path / "manifests")

        actor = yaml.safe_load((tmp_path / "manifests" / "base" / "handler-a.yaml").read_text())
        assert actor["apiVersion"] == "asya.sh/v1alpha1"
        assert actor["kind"] == "AsyncActor"
        assert actor["metadata"]["name"] == "handler-a"
        assert actor["metadata"]["namespace"] == "test-ns"
        assert actor["metadata"]["labels"]["asya.sh/flow"] == "my-flow"
        assert actor["metadata"]["labels"]["asya.sh/flow-role"] == "handler"

    def test_handler_image_is_fully_resolved(self, tmp_path, sequential_routers, router_code, config, template_dir):
        stamper = _make_stamper("my-flow", sequential_routers, router_code, config, template_dir)
        stamper.stamp(tmp_path / "manifests")

        actor = yaml.safe_load((tmp_path / "manifests" / "base" / "handler-a.yaml").read_text())
        image = actor["spec"]["image"]
        # Manifests are real K8s resources — no OmegaConf interpolations allowed
        assert "${" not in image
        assert image == "ghcr.io/test-org/handler-a:latest"

    def test_router_actor_uses_router_image(self, tmp_path, sequential_routers, router_code, config, template_dir):
        stamper = _make_stamper("my-flow", sequential_routers, router_code, config, template_dir)
        stamper.stamp(tmp_path / "manifests")

        actor = yaml.safe_load((tmp_path / "manifests" / "base" / "start-my-flow.yaml").read_text())
        assert actor["spec"]["image"] == "python:3.13-slim"
        assert actor["spec"]["handler"] == "routers.start_my_flow"
        assert actor["metadata"]["labels"]["asya.sh/flow-role"] == "entrypoint"

    def test_router_actor_has_handler_env(self, tmp_path, sequential_routers, router_code, config, template_dir):
        stamper = _make_stamper("my-flow", sequential_routers, router_code, config, template_dir)
        stamper.stamp(tmp_path / "manifests")

        actor = yaml.safe_load((tmp_path / "manifests" / "base" / "start-my-flow.yaml").read_text())
        env = actor["spec"]["env"]
        env_names = {e["name"] for e in env}
        assert "ASYA_HANDLER_HANDLER_A" in env_names
        assert "ASYA_HANDLER_HANDLER_B" in env_names

    def test_configmap_contains_router_code(self, tmp_path, sequential_routers, router_code, config, template_dir):
        stamper = _make_stamper("my-flow", sequential_routers, router_code, config, template_dir)
        stamper.stamp(tmp_path / "manifests")

        cm = yaml.safe_load((tmp_path / "manifests" / "base" / "configmap-routers.yaml").read_text())
        assert cm["kind"] == "ConfigMap"
        assert cm["metadata"]["name"] == "my-flow-routers"
        assert "routers.py" in cm["data"]
        assert "start_my_flow" in cm["data"]["routers.py"]

    def test_kustomization_lists_all_resources(self, tmp_path, sequential_routers, router_code, config, template_dir):
        stamper = _make_stamper("my-flow", sequential_routers, router_code, config, template_dir)
        stamper.stamp(tmp_path / "manifests")

        kust = yaml.safe_load((tmp_path / "manifests" / "base" / "kustomization.yaml").read_text())
        resources = kust["resources"]
        assert "configmap-routers.yaml" in resources
        assert "start-my-flow.yaml" in resources
        assert "handler-a.yaml" in resources

    def test_recompile_regenerates_base(self, tmp_path, sequential_routers, router_code, config, template_dir):
        out = tmp_path / "manifests"
        stamper = _make_stamper("my-flow", sequential_routers, router_code, config, template_dir)

        stamper.stamp(out)
        # Add a stale file
        (out / "base" / "stale.yaml").write_text("stale")

        stamper.stamp(out)
        assert not (out / "base" / "stale.yaml").exists()
        assert (out / "base" / "start-my-flow.yaml").exists()


class TestCommonLayer:
    def test_common_created_on_first_stamp(self, tmp_path, sequential_routers, router_code, config, template_dir):
        stamper = _make_stamper("my-flow", sequential_routers, router_code, config, template_dir)
        stamper.stamp(tmp_path / "manifests")

        kust = yaml.safe_load((tmp_path / "manifests" / "common" / "kustomization.yaml").read_text())
        assert kust["resources"] == ["../base"]

    def test_common_preserved_on_recompile(self, tmp_path, sequential_routers, router_code, config, template_dir):
        out = tmp_path / "manifests"
        stamper = _make_stamper("my-flow", sequential_routers, router_code, config, template_dir)

        stamper.stamp(out)
        # User adds a patch
        (out / "common" / "my-patch.yaml").write_text("user-patch")
        # Recompile
        stamper.stamp(out)
        assert (out / "common" / "my-patch.yaml").exists()
        assert (out / "common" / "my-patch.yaml").read_text() == "user-patch"


class TestOverlaysLayer:
    def test_no_overlays_without_contexts(self, tmp_path, sequential_routers, router_code, config, template_dir):
        stamper = _make_stamper("my-flow", sequential_routers, router_code, config, template_dir)
        stamper.stamp(tmp_path / "manifests")
        assert not (tmp_path / "manifests" / "overlays").exists()

    def test_overlays_created_from_contexts(
        self, tmp_path, sequential_routers, router_code, config_with_contexts, template_dir
    ):
        stamper = _make_stamper("my-flow", sequential_routers, router_code, config_with_contexts, template_dir)
        stamper.stamp(tmp_path / "manifests")

        for ctx in ("stg", "prod"):
            kust = yaml.safe_load((tmp_path / "manifests" / "overlays" / ctx / "kustomization.yaml").read_text())
            assert kust["resources"] == ["../../common"]

    def test_overlays_preserved_on_recompile(
        self, tmp_path, sequential_routers, router_code, config_with_contexts, template_dir
    ):
        out = tmp_path / "manifests"
        stamper = _make_stamper("my-flow", sequential_routers, router_code, config_with_contexts, template_dir)

        stamper.stamp(out)
        # User adds a patch to stg overlay
        (out / "overlays" / "stg" / "my-patch.yaml").write_text("stg-patch")
        # Recompile
        stamper.stamp(out)
        assert (out / "overlays" / "stg" / "my-patch.yaml").read_text() == "stg-patch"


class TestIdempotency:
    def test_identical_output_on_repeated_compile(
        self, tmp_path, sequential_routers, router_code, config, template_dir
    ):
        out = tmp_path / "manifests"
        stamper = _make_stamper("my-flow", sequential_routers, router_code, config, template_dir)

        stamper.stamp(out)
        first_run = {}
        for f in (out / "base").iterdir():
            first_run[f.name] = f.read_text()

        stamper.stamp(out)
        for f in (out / "base").iterdir():
            assert f.read_text() == first_run[f.name], f"Content changed for {f.name}"


class TestReturnedFiles:
    def test_stamp_returns_generated_paths(self, tmp_path, sequential_routers, router_code, config, template_dir):
        stamper = _make_stamper("my-flow", sequential_routers, router_code, config, template_dir)
        generated = stamper.stamp(tmp_path / "manifests")

        assert any("base/kustomization.yaml" in g for g in generated)
        assert any("base/configmap-routers.yaml" in g for g in generated)
        assert any("common/kustomization.yaml" in g for g in generated)

    def test_second_stamp_skips_existing_common(self, tmp_path, sequential_routers, router_code, config, template_dir):
        stamper = _make_stamper("my-flow", sequential_routers, router_code, config, template_dir)
        stamper.stamp(tmp_path / "manifests")
        generated = stamper.stamp(tmp_path / "manifests")

        # common/ should not be in second run's generated list
        assert not any("common/" in g for g in generated)
