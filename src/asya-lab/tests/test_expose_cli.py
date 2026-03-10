"""Tests for the expose and unexpose CLI commands."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from asya_lab.expose_cli import CONFIGMAP_FILENAME, expose, unexpose
from click.testing import CliRunner


ACTOR_MANIFEST = {
    "apiVersion": "asya.sh/v1alpha1",
    "kind": "AsyncActor",
    "metadata": {
        "name": "start-my-flow",
        "labels": {
            "asya.sh/flow": "my-flow",
            "asya.sh/flow-role": "entrypoint",
            "asya.sh/managed-by": "asya-compiler",
        },
    },
    "spec": {
        "handler": "routers.start_my_flow",
        "image": "python:3.13-slim",
    },
}

KUSTOMIZATION = {
    "apiVersion": "kustomize.config.k8s.io/v1beta1",
    "kind": "Kustomization",
    "resources": [
        "configmap-routers.yaml",
        "asyncactor-start-my-flow.yaml",
    ],
}


def _setup_base_dir(tmp_path: Path) -> Path:
    """Create a mock .asya/manifests/<flow>/base/ directory with actor YAML."""
    base_dir = tmp_path / ".asya" / "manifests" / "my-flow" / "base"
    base_dir.mkdir(parents=True)

    actor_path = base_dir / "asyncactor-start-my-flow.yaml"
    actor_path.write_text(yaml.dump(ACTOR_MANIFEST, default_flow_style=False))

    kust_path = base_dir / "kustomization.yaml"
    kust_path.write_text(yaml.dump(KUSTOMIZATION, default_flow_style=False))

    return base_dir


def test_expose_help():
    """Verify expose --help exits cleanly and shows expected content."""
    runner = CliRunner()
    result = runner.invoke(expose, ["--help"])
    assert result.exit_code == 0
    assert "expose" in result.output.lower()
    assert "target" in result.output.lower()
    assert "--description" in result.output


def test_unexpose_help():
    """Verify unexpose --help exits cleanly and shows expected content."""
    runner = CliRunner()
    result = runner.invoke(unexpose, ["--help"])
    assert result.exit_code == 0
    assert "unexpose" in result.output.lower()
    assert "target" in result.output.lower()


def test_expose_creates_configmap(tmp_path: Path):
    """Run expose on a mock base/ dir and verify configmap-flows.yaml is created."""
    base_dir = _setup_base_dir(tmp_path)

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        os.chdir(tmp_path)
        result = runner.invoke(expose, ["my-flow", "--description", "Test flow"])

    assert result.exit_code == 0, result.output

    cm_path = base_dir / CONFIGMAP_FILENAME
    assert cm_path.exists(), f"Expected {cm_path} to exist"

    cm = yaml.safe_load(cm_path.read_text())
    assert cm["kind"] == "ConfigMap"
    assert cm["metadata"]["name"] == "gateway-flows"
    assert cm["metadata"]["labels"]["asya.sh/managed-by"] == "asya-compiler"

    flow_data = yaml.safe_load(cm["data"]["my-flow.yaml"])
    assert flow_data["name"] == "my-flow"
    assert flow_data["entrypoint"] == "start-my-flow"
    assert flow_data["description"] == "Test flow"
    assert "mcp" in flow_data
    assert "a2a" not in flow_data

    kust = yaml.safe_load((base_dir / "kustomization.yaml").read_text())
    assert CONFIGMAP_FILENAME in kust["resources"]


def test_expose_mcp_with_schema(tmp_path: Path):
    """Run expose with MCP input schema."""
    base_dir = _setup_base_dir(tmp_path)

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        os.chdir(tmp_path)
        result = runner.invoke(
            expose,
            [
                "my-flow",
                "--description",
                "MCP flow",
                "--timeout",
                "30",
                "--mcp",
                "--input-schema",
                '{"type": "object", "properties": {"url": {"type": "string"}}}',
            ],
        )

    assert result.exit_code == 0, result.output

    cm = yaml.safe_load((base_dir / CONFIGMAP_FILENAME).read_text())
    flow_data = yaml.safe_load(cm["data"]["my-flow.yaml"])
    assert flow_data["timeout"] == 30
    assert flow_data["mcp"]["inputSchema"] == {"type": "object", "properties": {"url": {"type": "string"}}}
    assert "a2a" not in flow_data


def test_expose_a2a_with_options(tmp_path: Path):
    """Run expose with A2A skill options."""
    base_dir = _setup_base_dir(tmp_path)

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        os.chdir(tmp_path)
        result = runner.invoke(
            expose,
            [
                "my-flow",
                "--description",
                "Research assistant",
                "--a2a",
                "--tags",
                "research,general",
                "--examples",
                "What are trends in renewable energy?",
                "--examples",
                "Summarize this paper",
                "--input-modes",
                "text/plain,application/json",
                "--output-modes",
                "text/plain",
            ],
        )

    assert result.exit_code == 0, result.output

    cm = yaml.safe_load((base_dir / CONFIGMAP_FILENAME).read_text())
    flow_data = yaml.safe_load(cm["data"]["my-flow.yaml"])
    assert "mcp" not in flow_data
    assert flow_data["a2a"]["tags"] == ["research", "general"]
    assert flow_data["a2a"]["examples"] == ["What are trends in renewable energy?", "Summarize this paper"]
    assert flow_data["a2a"]["input_modes"] == ["text/plain", "application/json"]
    assert flow_data["a2a"]["output_modes"] == ["text/plain"]


def test_expose_both_protocols(tmp_path: Path):
    """Run expose with both MCP and A2A enabled."""
    base_dir = _setup_base_dir(tmp_path)

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        os.chdir(tmp_path)
        result = runner.invoke(
            expose,
            [
                "my-flow",
                "--description",
                "Dual protocol",
                "--mcp",
                "--input-schema",
                '{"type": "object"}',
                "--a2a",
                "--tags",
                "analysis,nlp",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "mcp+a2a" in result.output

    cm = yaml.safe_load((base_dir / CONFIGMAP_FILENAME).read_text())
    flow_data = yaml.safe_load(cm["data"]["my-flow.yaml"])
    assert "mcp" in flow_data
    assert flow_data["mcp"]["inputSchema"] == {"type": "object"}
    assert "a2a" in flow_data
    assert flow_data["a2a"]["tags"] == ["analysis", "nlp"]


def test_unexpose_removes_configmap(tmp_path: Path):
    """Run unexpose and verify configmap-flows.yaml is removed from base/ and kustomization."""
    base_dir = _setup_base_dir(tmp_path)

    cm_path = base_dir / CONFIGMAP_FILENAME
    cm_path.write_text("placeholder")

    kust_path = base_dir / "kustomization.yaml"
    kust = yaml.safe_load(kust_path.read_text())
    kust["resources"].append(CONFIGMAP_FILENAME)
    kust_path.write_text(yaml.dump(kust, default_flow_style=False))

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        os.chdir(tmp_path)
        result = runner.invoke(unexpose, ["my-flow"])

    assert result.exit_code == 0, result.output
    assert not cm_path.exists(), f"Expected {cm_path} to be removed"

    kust_after = yaml.safe_load(kust_path.read_text())
    assert CONFIGMAP_FILENAME not in kust_after["resources"]


def test_unexpose_no_configmap(tmp_path: Path):
    """Unexpose gracefully handles missing configmap-flows.yaml."""
    _setup_base_dir(tmp_path)

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        os.chdir(tmp_path)
        result = runner.invoke(unexpose, ["my-flow"])

    assert result.exit_code == 0
    assert "nothing to remove" in result.output


def test_expose_py_file_target(tmp_path: Path):
    """Expose accepts a .py file path as target and derives the flow name."""
    base_dir = _setup_base_dir(tmp_path)

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        os.chdir(tmp_path)
        result = runner.invoke(expose, ["my_flow.py", "--description", "From .py file"])

    assert result.exit_code == 0, result.output

    cm = yaml.safe_load((base_dir / CONFIGMAP_FILENAME).read_text())
    flow_data = yaml.safe_load(cm["data"]["my-flow.yaml"])
    assert flow_data["name"] == "my-flow"


def test_expose_idempotent_kustomization(tmp_path: Path):
    """Running expose twice does not duplicate the resource in kustomization.yaml."""
    base_dir = _setup_base_dir(tmp_path)

    runner = CliRunner()
    for _ in range(2):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            os.chdir(tmp_path)
            result = runner.invoke(expose, ["my-flow", "--description", "Test"])
            assert result.exit_code == 0, result.output

    kust = yaml.safe_load((base_dir / "kustomization.yaml").read_text())
    count = kust["resources"].count(CONFIGMAP_FILENAME)
    assert count == 1, f"Expected exactly 1 occurrence, got {count}"
