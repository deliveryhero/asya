"""Tests for the status CLI command."""

from unittest.mock import patch

from asya_lab.status_cli import status
from click.testing import CliRunner


def test_status_help():
    runner = CliRunner()
    result = runner.invoke(status, ["--help"])
    assert result.exit_code == 0
    assert "status" in result.output.lower()


def test_status_with_compiled_flow(tmp_path):
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir(exist_ok=True)
    (asya_dir / "config.yaml").write_text('compiler:\n  manifests: ".asya/manifests"\n')
    manifests_dir = asya_dir / "manifests"
    flow_dir = manifests_dir / "order-processing"
    base_dir = flow_dir / "base"
    base_dir.mkdir(parents=True)

    kustomization = {
        "resources": [
            "configmap-routers.yaml",
            "asyncactor-router-1.yaml",
            "asyncactor-router-2.yaml",
            "asyncactor-router-3.yaml",
            "configmap-flows.yaml",
        ]
    }
    import yaml

    (base_dir / "kustomization.yaml").write_text(yaml.dump(kustomization))

    runner = CliRunner()
    with patch("asya_lab.status_cli.find_asya_dir", return_value=asya_dir):
        result = runner.invoke(status, [])
    assert result.exit_code == 0
    assert "FLOW" in result.output
    assert "STATUS" in result.output
    assert "ACTORS" in result.output
    assert "EXPOSED" in result.output
    assert "order-processing" in result.output
    assert "compiled" in result.output
    assert "3" in result.output  # excludes configmap-routers and configmap-flows
    assert "yes" in result.output


def test_status_empty(tmp_path):
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir()
    (asya_dir / "config.yaml").write_text('compiler:\n  manifests: ".asya/manifests"\n')

    runner = CliRunner()
    with patch("asya_lab.status_cli.find_asya_dir", return_value=asya_dir):
        result = runner.invoke(status, [])
    assert result.exit_code == 0
    assert "FLOW" in result.output
    assert "STATUS" in result.output
    lines = result.output.strip().split("\n")
    assert len(lines) == 1  # header only
