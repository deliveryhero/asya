"""Helm template tests for crew persistence flavor."""

import subprocess
from pathlib import Path

import pytest
import yaml

CHART_PATH = Path(__file__).parent.parent


def helm_template(**set_values: str) -> list[dict]:
    """Render Helm chart and return parsed YAML documents."""
    cmd = ["helm", "template", "test", str(CHART_PATH)]
    for key, value in set_values.items():
        cmd.extend(["--set", f"{key}={value}"])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.fail(f"helm template failed: {result.stderr}")
    docs = []
    for doc in yaml.safe_load_all(result.stdout):
        if doc:
            docs.append(doc)
    return docs


def helm_template_expect_fail(**set_values: str) -> str:
    """Render Helm chart expecting failure, return stderr."""
    cmd = ["helm", "template", "test", str(CHART_PATH)]
    for key, value in set_values.items():
        cmd.extend(["--set", f"{key}={value}"])
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode != 0, "Expected helm template to fail"
    return result.stderr


def find_docs(docs: list[dict], kind: str) -> list[dict]:
    """Find all documents of a given kind."""
    return [d for d in docs if d.get("kind") == kind]


def find_doc(docs: list[dict], kind: str, name: str) -> dict | None:
    """Find a document by kind and name."""
    for d in docs:
        if d.get("kind") == kind and d.get("metadata", {}).get("name") == name:
            return d
    return None


# -- Persistence disabled (default) --


class TestPersistenceDisabled:
    """When persistence is not enabled, no flavor resources are created."""

    @pytest.fixture()
    def docs(self):
        return helm_template(**{
            "x-sink.transport": "sqs",
            "x-sump.transport": "sqs",
        })

    def test_no_environment_config(self, docs):
        assert find_docs(docs, "EnvironmentConfig") == []

    def test_no_flavors_on_sink(self, docs):
        sink = find_doc(docs, "AsyncActor", "x-sink")
        assert sink is not None
        assert "flavors" not in sink["spec"]

    def test_no_flavors_on_sump(self, docs):
        sump = find_doc(docs, "AsyncActor", "x-sump")
        assert sump is not None
        assert "flavors" not in sump["spec"]


# -- Persistence enabled --


PERSISTENCE_VALUES = {
    "x-sink.transport": "sqs",
    "x-sump.transport": "sqs",
    "checkpoint-s3.enabled": "true",
    "checkpoint-s3.transport": "sqs",
    "persistence.enabled": "true",
    "persistence.backend": "s3",
    "persistence.config.bucket": "test-bucket",
}


class TestPersistenceEnabled:
    """When persistence is enabled with S3 backend."""

    @pytest.fixture()
    def docs(self):
        return helm_template(**PERSISTENCE_VALUES)

    def test_environment_config_created(self, docs):
        ec = find_doc(docs, "EnvironmentConfig", "test-persistence-s3")
        assert ec is not None

    def test_environment_config_labels(self, docs):
        ec = find_doc(docs, "EnvironmentConfig", "test-persistence-s3")
        assert ec["metadata"]["labels"]["asya.sh/flavor"] == "test-persistence-s3"

    def test_state_proxy_config(self, docs):
        ec = find_doc(docs, "EnvironmentConfig", "test-persistence-s3")
        sp = ec["data"]["stateProxy"]
        assert len(sp) == 1
        assert sp[0]["name"] == "checkpoints"
        assert sp[0]["mount"]["path"] == "/state/checkpoints"
        assert "asya-state-proxy-s3-buffered-lww" in sp[0]["connector"]["image"]

    def test_state_proxy_bucket_env(self, docs):
        ec = find_doc(docs, "EnvironmentConfig", "test-persistence-s3")
        env = ec["data"]["stateProxy"][0]["connector"]["env"]
        bucket_env = next(e for e in env if e["name"] == "STATE_BUCKET")
        assert bucket_env["value"] == "test-bucket"

    def test_sink_has_flavor(self, docs):
        sink = find_doc(docs, "AsyncActor", "x-sink")
        assert "test-persistence-s3" in sink["spec"]["flavors"]

    def test_sump_has_flavor(self, docs):
        sump = find_doc(docs, "AsyncActor", "x-sump")
        assert "test-persistence-s3" in sump["spec"]["flavors"]

    def test_checkpoint_has_flavor(self, docs):
        cp = find_doc(docs, "AsyncActor", "checkpoint-s3")
        assert "test-persistence-s3" in cp["spec"]["flavors"]


# -- Optional config --


class TestPersistenceOptionalConfig:
    """Optional endpoint and region are rendered only when set."""

    def test_endpoint_rendered_when_set(self):
        vals = {**PERSISTENCE_VALUES, "persistence.config.endpoint": "http://minio:9000"}
        docs = helm_template(**vals)
        ec = find_doc(docs, "EnvironmentConfig", "test-persistence-s3")
        env = ec["data"]["stateProxy"][0]["connector"]["env"]
        endpoint_env = next(e for e in env if e["name"] == "STATE_ENDPOINT")
        assert endpoint_env["value"] == "http://minio:9000"

    def test_endpoint_not_rendered_when_empty(self):
        docs = helm_template(**PERSISTENCE_VALUES)
        ec = find_doc(docs, "EnvironmentConfig", "test-persistence-s3")
        env = ec["data"]["stateProxy"][0]["connector"]["env"]
        env_names = [e["name"] for e in env]
        assert "STATE_ENDPOINT" not in env_names

    def test_region_rendered_when_set(self):
        vals = {**PERSISTENCE_VALUES, "persistence.config.region": "eu-west-1"}
        docs = helm_template(**vals)
        ec = find_doc(docs, "EnvironmentConfig", "test-persistence-s3")
        env = ec["data"]["stateProxy"][0]["connector"]["env"]
        region_env = next(e for e in env if e["name"] == "AWS_REGION")
        assert region_env["value"] == "eu-west-1"


# -- Fail-fast validation --


class TestPersistenceValidation:
    """Fail-fast when required values are missing."""

    def test_fails_without_bucket(self):
        stderr = helm_template_expect_fail(**{
            "x-sink.transport": "sqs",
            "x-sump.transport": "sqs",
            "persistence.enabled": "true",
            "persistence.backend": "s3",
        })
        assert "persistence.config.bucket is required" in stderr

    def test_fails_with_unsupported_backend(self):
        stderr = helm_template_expect_fail(**{
            "x-sink.transport": "sqs",
            "x-sump.transport": "sqs",
            "persistence.enabled": "true",
            "persistence.backend": "gcs",
            "persistence.config.bucket": "test",
        })
        assert "persistence.backend must be" in stderr
