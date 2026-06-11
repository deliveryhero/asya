"""Tests for the expose and unexpose CLI commands (kustomize-native)."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from asya_lab.expose_cli import EXPOSE_FILENAME, expose, unexpose
from click.testing import CliRunner


ACTOR_MANIFEST = {
    "apiVersion": "asya.sh/v1alpha1",
    "kind": "AsyncActor",
    "metadata": {
        "name": "start-my-flow",
        "labels": {
            "asya.sh/flow": "my-flow",
            "asya.sh/role": "start",
            "asya.sh/managed-by": "asya-compiler",
        },
    },
    "spec": {
        "handler": "routers.start_my-flow",
        "image": "python:3.13-slim",
    },
}

KUSTOMIZATION = {
    "apiVersion": "kustomize.config.k8s.io/v1beta1",
    "kind": "Kustomization",
    "resources": [
        "configmap-routers.yaml",
        "asya-start-my-flow.yaml",
    ],
}


def _setup_project(tmp_path: Path) -> Path:
    """Create a mock project with .asya/ and compiled manifests."""
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir(exist_ok=True)
    (asya_dir / "config.yaml").write_text(
        'templates:\n  namespace: default\ncompiler:\n  manifests: "./compiled/${arg:flow_name}/manifests"\n'
    )

    base_dir = tmp_path / "compiled" / "my-flow" / "manifests" / "base"
    base_dir.mkdir(parents=True)
    common_dir = tmp_path / "compiled" / "my-flow" / "manifests" / "common"
    common_dir.mkdir(parents=True)

    (base_dir / "asya-start-my-flow.yaml").write_text(yaml.dump(ACTOR_MANIFEST, default_flow_style=False))
    (base_dir / "kustomization.yaml").write_text(yaml.dump(KUSTOMIZATION, default_flow_style=False))
    (common_dir / "kustomization.yaml").write_text(
        yaml.dump(
            {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "resources": ["../base"]},
            default_flow_style=False,
        )
    )

    return base_dir


def test_expose_help():
    runner = CliRunner()
    result = runner.invoke(expose, ["--help"])
    assert result.exit_code == 0
    assert "expose" in result.output.lower()
    assert "target" in result.output.lower()


def test_unexpose_help():
    runner = CliRunner()
    result = runner.invoke(unexpose, ["--help"])
    assert result.exit_code == 0
    assert "unexpose" in result.output.lower()
    assert "target" in result.output.lower()


def test_expose_creates_intent_mcp_default(tmp_path: Path):
    _setup_project(tmp_path)

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        os.chdir(tmp_path)
        result = runner.invoke(expose, ["my-flow", "--description", "Test flow"])

    assert result.exit_code == 0, result.output

    common_dir = tmp_path / "compiled" / "my-flow" / "manifests" / "common"
    intent_path = common_dir / EXPOSE_FILENAME
    assert intent_path.exists(), f"Expected {intent_path} to exist"

    intent = yaml.safe_load(intent_path.read_text())
    # New format: a normalized intent doc, NOT a k8s ConfigMap.
    assert "kind" not in intent
    assert intent["flow"] == "my-flow"
    # Default protocol is MCP; entrypoint (start actor) becomes `actor`.
    assert intent["mcp"]["name"] == "my-flow"
    assert intent["mcp"]["actor"] == "start-my-flow"
    assert intent["mcp"]["description"] == "Test flow"
    assert "a2a" not in intent


def test_expose_a2a_emits_agent_entry(tmp_path: Path):
    _setup_project(tmp_path)

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        os.chdir(tmp_path)
        result = runner.invoke(expose, ["my-flow", "--description", "Test flow", "--a2a"])

    assert result.exit_code == 0, result.output

    common_dir = tmp_path / "compiled" / "my-flow" / "manifests" / "common"
    intent = yaml.safe_load((common_dir / EXPOSE_FILENAME).read_text())
    agent = intent["a2a"]
    assert agent["name"] == "my-flow"
    assert agent["actor"] == "start-my-flow"
    assert agent["streaming"] is True
    assert agent["skills"][0]["id"] == "my-flow"
    assert agent["inputModes"] == ["text/plain", "application/json"]
    assert "mcp" not in intent


def test_expose_does_not_touch_kustomization(tmp_path: Path):
    _setup_project(tmp_path)
    common_dir = tmp_path / "compiled" / "my-flow" / "manifests" / "common"
    before = (common_dir / "kustomization.yaml").read_text()

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        os.chdir(tmp_path)
        result = runner.invoke(expose, ["my-flow", "--description", "Test flow", "--a2a"])

    assert result.exit_code == 0, result.output
    # The intent is consumed by `asya k apply`, not by kustomize.
    assert (common_dir / "kustomization.yaml").read_text() == before
