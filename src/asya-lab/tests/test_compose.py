"""Tests for Docker Compose YAML generation."""

from __future__ import annotations

import yaml
from asya_lab.compose import (
    MESH_DIR,
    MESH_VOLUME,
    SIDECAR_IMAGE,
    _extract_actor_info,
    generate_compose,
    load_actors,
    load_actors_from_yaml,
    write_compose,
)


def _make_actor_doc(
    name: str,
    handler: str = "my_module.process",
    image: str = "my-image:latest",
    extra_env: list[dict] | None = None,
) -> dict:
    spec: dict = {
        "actor": name,
        "transport": "sqs",
        "image": image,
        "handler": handler,
    }
    if extra_env:
        spec["env"] = list(extra_env)
    return {
        "apiVersion": "asya.sh/v1alpha1",
        "kind": "AsyncActor",
        "metadata": {"name": name, "namespace": "test"},
        "spec": spec,
    }


class TestExtractActorInfo:
    def test_basic_extraction(self):
        doc = _make_actor_doc("my-actor", handler="mod.func", image="img:v1")
        info = _extract_actor_info(doc)
        assert info["name"] == "my-actor"
        assert info["handler"] == "mod.func"
        assert info["image"] == "img:v1"
        assert info["actor"] == "my-actor"
        assert info["python_executable"] == "python3"
        assert info["sidecar_image"] == SIDECAR_IMAGE
        assert info["sidecar_env"] == []

    def test_drops_state_proxy_mounts(self):
        doc = _make_actor_doc(
            "stateful",
            extra_env=[{"name": "ASYA_STATE_PROXY_MOUNTS", "value": "meta:/state/meta:write=buffered"}],
        )
        info = _extract_actor_info(doc)
        env_names = [e["name"] for e in info["env"]]
        assert "ASYA_STATE_PROXY_MOUNTS" not in env_names

    def test_keeps_user_env_vars(self):
        doc = _make_actor_doc(
            "custom",
            extra_env=[
                {"name": "MY_VAR", "value": "hello"},
                {"name": "ASYA_LOG_LEVEL", "value": "DEBUG"},
            ],
        )
        info = _extract_actor_info(doc)
        env_names = [e["name"] for e in info["env"]]
        assert "MY_VAR" in env_names
        assert "ASYA_LOG_LEVEL" in env_names

    def test_skips_valuefrom_env(self):
        doc = _make_actor_doc("secret-user")
        doc["spec"]["env"] = [
            {"name": "SECRET_KEY", "valueFrom": {"secretKeyRef": {"name": "my-secret", "key": "key"}}}
        ]
        info = _extract_actor_info(doc)
        env_names = [e["name"] for e in info["env"]]
        assert "SECRET_KEY" not in env_names

    def test_missing_fields(self):
        doc = {
            "apiVersion": "asya.sh/v1alpha1",
            "kind": "AsyncActor",
            "metadata": {"name": "bare"},
            "spec": {"actor": "bare"},
        }
        info = _extract_actor_info(doc)
        assert info["name"] == "bare"
        assert info["image"] == ""
        assert info["handler"] == ""
        assert info["env"] == []
        assert info["python_executable"] == "python3"
        assert info["sidecar_image"] == SIDECAR_IMAGE
        assert info["sidecar_env"] == []

    def test_python_executable(self):
        doc = _make_actor_doc("py-actor")
        doc["spec"]["pythonExecutable"] = "/usr/bin/python"
        info = _extract_actor_info(doc)
        assert info["python_executable"] == "/usr/bin/python"

    def test_sidecar_overrides(self):
        doc = _make_actor_doc("custom-sidecar")
        doc["spec"]["sidecar"] = {
            "image": "my-sidecar:v2",
            "env": [{"name": "ASYA_LOG_LEVEL", "value": "DEBUG"}],
        }
        info = _extract_actor_info(doc)
        assert info["sidecar_image"] == "my-sidecar:v2"
        assert info["sidecar_env"] == [{"name": "ASYA_LOG_LEVEL", "value": "DEBUG"}]


_RUNTIME_PY = "/path/to/asya_runtime.py"


class TestGenerateCompose:
    def test_basic_flow(self):
        actors = [
            _make_actor_doc("actor-a", handler="mod.a", image="img:v1"),
            _make_actor_doc("actor-b", handler="mod.b", image="img:v2"),
        ]
        compose = generate_compose(actors, "my-flow", runtime_py=_RUNTIME_PY)

        assert compose["name"] == "asya-my-flow"

        services = compose["services"]
        assert "actor-a-sidecar" in services
        assert "actor-a-runtime" in services
        assert "actor-b-sidecar" in services
        assert "actor-b-runtime" in services
        assert "x-sink" in services
        assert "x-sump" in services

    def test_sidecar_config(self):
        actors = [_make_actor_doc("test-actor")]
        compose = generate_compose(actors, "flow", runtime_py=_RUNTIME_PY)
        sidecar = compose["services"]["test-actor-sidecar"]

        assert sidecar["image"] == SIDECAR_IMAGE
        env = sidecar["environment"]
        assert env["ASYA_TRANSPORT"] == "socket"
        assert env["ASYA_ACTOR_NAME"] == "test-actor"
        assert env["ASYA_SOCKET_MESH_DIR"] == MESH_DIR

    def test_runtime_config(self):
        actors = [_make_actor_doc("test-actor", handler="my.handler", image="my:img")]
        compose = generate_compose(actors, "flow", runtime_py=_RUNTIME_PY)
        runtime = compose["services"]["test-actor-runtime"]

        assert runtime["image"] == "my:img"
        assert runtime["command"] == ["python3", "/opt/asya/asya_runtime.py"]
        assert runtime["environment"]["ASYA_HANDLER"] == "my.handler"
        assert "test-actor-sidecar" in runtime["depends_on"]
        assert any("asya_runtime.py" in v for v in runtime["volumes"])

    def test_system_actors(self):
        actors = [_make_actor_doc("actor-a")]
        compose = generate_compose(actors, "flow", runtime_py=_RUNTIME_PY)

        sink = compose["services"]["x-sink"]
        assert sink["environment"]["ASYA_IS_END_ACTOR"] == "true"
        assert sink["environment"]["ASYA_ACTOR_NAME"] == "x-sink"

        sump = compose["services"]["x-sump"]
        assert sump["environment"]["ASYA_IS_END_ACTOR"] == "true"
        assert sump["environment"]["ASYA_ACTOR_NAME"] == "x-sump"

    def test_cli_service(self):
        actors = [_make_actor_doc("actor-a")]
        compose = generate_compose(actors, "flow", runtime_py=_RUNTIME_PY)

        cli = compose["services"]["asya-cli"]
        assert cli["image"] == "python:3-alpine"
        assert cli["profiles"] == ["cli"]
        mesh_mounts = [v for v in cli["volumes"] if v.startswith(MESH_VOLUME)]
        assert len(mesh_mounts) == 1

    def test_mesh_volume_shared(self):
        actors = [_make_actor_doc("a"), _make_actor_doc("b")]
        compose = generate_compose(actors, "flow", runtime_py=_RUNTIME_PY)

        assert MESH_VOLUME in compose["volumes"]
        for name in ("a-sidecar", "b-sidecar", "x-sink", "x-sump"):
            svc = compose["services"][name]
            mesh_mounts = [v for v in svc["volumes"] if v.startswith(MESH_VOLUME)]
            assert len(mesh_mounts) == 1

    def test_per_actor_runtime_volume(self):
        actors = [_make_actor_doc("a"), _make_actor_doc("b")]
        compose = generate_compose(actors, "flow", runtime_py=_RUNTIME_PY)

        assert "rt-a" in compose["volumes"]
        assert "rt-b" in compose["volumes"]

    def test_runtime_py_mount(self):
        actors = [_make_actor_doc("test-actor", handler="my.handler", image="my:img")]
        compose = generate_compose(actors, "flow", runtime_py="/path/to/asya_runtime.py")
        runtime = compose["services"]["test-actor-runtime"]
        assert runtime["command"] == ["python3", "/opt/asya/asya_runtime.py"]
        assert any("asya_runtime.py" in v for v in runtime["volumes"])

    def test_python_executable_in_command(self):
        doc = _make_actor_doc("py-actor", handler="mod.func", image="img:v1")
        doc["spec"]["pythonExecutable"] = "/usr/bin/python"
        compose = generate_compose([doc], "flow", runtime_py=_RUNTIME_PY)
        runtime = compose["services"]["py-actor-runtime"]
        assert runtime["command"] == ["/usr/bin/python", "/opt/asya/asya_runtime.py"]

    def test_sidecar_image_override(self):
        doc = _make_actor_doc("custom", handler="mod.func", image="img:v1")
        doc["spec"]["sidecar"] = {"image": "my-sidecar:v2"}
        compose = generate_compose([doc], "flow", runtime_py=_RUNTIME_PY)
        sidecar = compose["services"]["custom-sidecar"]
        assert sidecar["image"] == "my-sidecar:v2"

    def test_handler_dir_mount(self):
        actors = [_make_actor_doc("test-actor", handler="my.handler", image="my:img")]
        compose = generate_compose(actors, "flow", runtime_py=_RUNTIME_PY, handler_dir="/app/handlers")
        runtime = compose["services"]["test-actor-runtime"]
        assert any("/opt/asya/handlers" in v for v in runtime["volumes"])
        assert runtime["environment"]["PYTHONPATH"] == "/opt/asya/handlers"

    def test_user_env_in_runtime(self):
        actors = [_make_actor_doc("env-actor", extra_env=[{"name": "MY_VAR", "value": "hello"}])]
        compose = generate_compose(actors, "flow", runtime_py=_RUNTIME_PY)
        runtime = compose["services"]["env-actor-runtime"]
        assert runtime["environment"]["MY_VAR"] == "hello"


class TestLoadActors:
    def test_loads_from_directory(self, tmp_path):
        actor = _make_actor_doc("hello")
        (tmp_path / "actor.yaml").write_text(yaml.dump(actor))
        (tmp_path / "kustomization.yaml").write_text("resources: []")

        actors = load_actors(tmp_path)
        assert len(actors) == 1
        assert actors[0]["metadata"]["name"] == "hello"

    def test_loads_multi_doc(self, tmp_path):
        docs = [_make_actor_doc("a"), _make_actor_doc("b")]
        content = "---\n".join(yaml.dump(d) for d in docs)
        (tmp_path / "actors.yaml").write_text(content)

        actors = load_actors(tmp_path)
        assert len(actors) == 2

    def test_skips_non_asyncactor(self, tmp_path):
        configmap = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "test"}}
        actor = _make_actor_doc("real")
        content = yaml.dump(configmap) + "---\n" + yaml.dump(actor)
        (tmp_path / "mixed.yaml").write_text(content)

        actors = load_actors(tmp_path)
        assert len(actors) == 1
        assert actors[0]["metadata"]["name"] == "real"


class TestLoadActorsFromYaml:
    def test_parses_multi_doc(self):
        docs = [_make_actor_doc("a"), _make_actor_doc("b")]
        content = "---\n".join(yaml.dump(d) for d in docs)
        actors = load_actors_from_yaml(content)
        assert len(actors) == 2
        assert actors[0]["metadata"]["name"] == "a"
        assert actors[1]["metadata"]["name"] == "b"

    def test_skips_non_asyncactor(self):
        configmap = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "cfg"}}
        actor = _make_actor_doc("real")
        content = yaml.dump(configmap) + "---\n" + yaml.dump(actor)
        actors = load_actors_from_yaml(content)
        assert len(actors) == 1
        assert actors[0]["metadata"]["name"] == "real"

    def test_empty_string(self):
        actors = load_actors_from_yaml("")
        assert actors == []


class TestWriteCompose:
    def test_writes_yaml(self, tmp_path):
        compose = {"name": "test", "services": {}, "volumes": {}}
        output = tmp_path / "compose" / "test.yaml"
        result = write_compose(compose, output)

        assert result == output
        assert output.exists()
        loaded = yaml.safe_load(output.read_text())
        assert loaded["name"] == "test"

    def test_creates_parent_dirs(self, tmp_path):
        output = tmp_path / "deep" / "nested" / "compose.yaml"
        write_compose({"name": "test"}, output)
        assert output.exists()
