"""Tests for the build CLI command (skaffold-based)."""

from __future__ import annotations

from unittest.mock import patch

import yaml
from asya_lab.build_cli import (
    _find_flow_images,
    build,
)
from click.testing import CliRunner


def test_build_help():
    runner = CliRunner()
    result = runner.invoke(build, ["--help"])
    assert result.exit_code == 0
    assert "flow_name" in result.output.lower()


def test_find_flow_images(tmp_path):
    base_dir = tmp_path / "base"
    base_dir.mkdir(parents=True)

    actor_manifest = {
        "apiVersion": "asya.sh/v1alpha1",
        "kind": "AsyncActor",
        "metadata": {"name": "actor-a"},
        "spec": {"image": "ghcr.io/org/image-a:v1"},
    }
    (base_dir / "asya-actor-a.yaml").write_text(yaml.dump(actor_manifest))

    images = _find_flow_images(base_dir)
    assert images == {"actor-a": "ghcr.io/org/image-a:v1"}


def test_find_flow_images_missing_dir(tmp_path):
    images = _find_flow_images(tmp_path / "nonexistent")
    assert images == {}


def test_build_no_asya_dir():
    runner = CliRunner()
    with patch("asya_lab.build_cli.find_asya_dir", return_value=None):
        result = runner.invoke(build, ["my-target"])
    assert result.exit_code != 0
    assert "No .asya/ directory" in result.output
