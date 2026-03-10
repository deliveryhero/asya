"""Tests for the Kubernetes CLI commands (asya k)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import yaml
from asya_lab.k_cli import (
    apply,
    context_group,
    delete,
    edit,
    k,
    k_status,
    logs,
)
from click.testing import CliRunner


# ---------------------------------------------------------------------------
# asya k (group)
# ---------------------------------------------------------------------------


def test_k_group_help():
    runner = CliRunner()
    result = runner.invoke(k, ["--help"])
    assert result.exit_code == 0
    assert "apply" in result.output
    assert "delete" in result.output
    assert "status" in result.output
    assert "logs" in result.output
    assert "edit" in result.output
    assert "context" in result.output


# ---------------------------------------------------------------------------
# asya k apply
# ---------------------------------------------------------------------------


def test_apply_help():
    runner = CliRunner()
    result = runner.invoke(apply, ["--help"])
    assert result.exit_code == 0
    assert "target" in result.output.lower()
    assert "--context" in result.output


def test_apply_missing_manifests(tmp_path):
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir()
    (asya_dir / "manifests").mkdir()

    runner = CliRunner()
    with patch("asya_lab.k_cli.find_asya_dir", return_value=asya_dir):
        result = runner.invoke(apply, ["nonexistent-flow"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


@patch("asya_lab.k_cli.subprocess.run")
def test_apply_success(mock_run, tmp_path):
    asya_dir = tmp_path / ".asya"
    base_dir = asya_dir / "manifests" / "my-flow" / "base"
    base_dir.mkdir(parents=True)
    (base_dir / "kustomization.yaml").write_text("resources: []")

    # kustomize build succeeds, kubectl apply succeeds
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="rendered-yaml", stderr=""),
        MagicMock(returncode=0, stdout="asyncactor.asya.sh/my-actor serverside-applied\n", stderr=""),
    ]

    runner = CliRunner()
    with (
        patch("asya_lab.k_cli.find_asya_dir", return_value=asya_dir),
        patch("asya_lab.k_cli._resolve_context", return_value=None),
    ):
        result = runner.invoke(apply, ["my-flow"])

    assert result.exit_code == 0
    assert "serverside-applied" in result.output
    assert mock_run.call_count == 2


@patch("asya_lab.k_cli.subprocess.run")
def test_apply_with_context(mock_run, tmp_path):
    asya_dir = tmp_path / ".asya"
    overlay_dir = asya_dir / "manifests" / "my-flow" / "overlays" / "stg"
    overlay_dir.mkdir(parents=True)
    (overlay_dir / "kustomization.yaml").write_text("resources: [../../base]")

    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="rendered-yaml", stderr=""),
        MagicMock(returncode=0, stdout="applied\n", stderr=""),
    ]

    context = {"kubecontext": "my-stg", "namespace": "team-one"}

    runner = CliRunner()
    with (
        patch("asya_lab.k_cli.find_asya_dir", return_value=asya_dir),
        patch("asya_lab.k_cli._resolve_context", return_value=context),
    ):
        result = runner.invoke(apply, ["my-flow", "--context", "stg"])

    assert result.exit_code == 0
    # Check that -n namespace was passed to kubectl apply
    apply_call = mock_run.call_args_list[1]
    apply_cmd = apply_call[0][0]
    assert "-n" in apply_cmd
    assert "team-one" in apply_cmd


def test_apply_readonly_context(tmp_path):
    asya_dir = tmp_path / ".asya"
    base_dir = asya_dir / "manifests" / "my-flow" / "base"
    base_dir.mkdir(parents=True)
    (base_dir / "kustomization.yaml").write_text("resources: []")

    context = {"kubecontext": "my-prod", "namespace": "prod", "readonly": True}

    runner = CliRunner()
    with (
        patch("asya_lab.k_cli.find_asya_dir", return_value=asya_dir),
        patch("asya_lab.k_cli._resolve_context", return_value=context),
    ):
        result = runner.invoke(apply, ["my-flow"])

    assert result.exit_code != 0
    assert "readonly" in result.output.lower()


@patch("asya_lab.k_cli.subprocess.run")
def test_apply_kustomize_failure(mock_run, tmp_path):
    asya_dir = tmp_path / ".asya"
    base_dir = asya_dir / "manifests" / "my-flow" / "base"
    base_dir.mkdir(parents=True)
    (base_dir / "kustomization.yaml").write_text("resources: []")

    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="kustomize error")

    runner = CliRunner()
    with (
        patch("asya_lab.k_cli.find_asya_dir", return_value=asya_dir),
        patch("asya_lab.k_cli._resolve_context", return_value=None),
    ):
        result = runner.invoke(apply, ["my-flow"])

    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# asya k delete
# ---------------------------------------------------------------------------


def test_delete_help():
    runner = CliRunner()
    result = runner.invoke(delete, ["--help"])
    assert result.exit_code == 0
    assert "target" in result.output.lower()


@patch("asya_lab.k_cli._run_cmd")
def test_delete_success(mock_run):
    mock_run.return_value = MagicMock(returncode=0)

    runner = CliRunner()
    with patch("asya_lab.k_cli._resolve_context", return_value=None):
        result = runner.invoke(delete, ["my-flow"])

    assert result.exit_code == 0
    cmd = mock_run.call_args[0][0]
    assert "kubectl" in cmd
    assert "delete" in cmd
    assert "asya.sh/flow=my-flow" in cmd


def test_delete_readonly_context():
    context = {"kubecontext": "prod", "namespace": "prod", "readonly": True}

    runner = CliRunner()
    with patch("asya_lab.k_cli._resolve_context", return_value=context):
        result = runner.invoke(delete, ["my-flow"])

    assert result.exit_code != 0
    assert "readonly" in result.output.lower()


# ---------------------------------------------------------------------------
# asya k status
# ---------------------------------------------------------------------------


def test_k_status_help():
    runner = CliRunner()
    result = runner.invoke(k_status, ["--help"])
    assert result.exit_code == 0
    assert "target" in result.output.lower()


@patch("asya_lab.k_cli._run_cmd")
def test_k_status_success(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="NAME  STATUS\nactor-a  Running\n")

    runner = CliRunner()
    with patch("asya_lab.k_cli._resolve_context", return_value=None):
        result = runner.invoke(k_status, ["my-flow"])

    assert result.exit_code == 0
    cmd = mock_run.call_args[0][0]
    assert "kubectl" in cmd
    assert "get" in cmd
    assert "asyncactor" in cmd


# ---------------------------------------------------------------------------
# asya k logs
# ---------------------------------------------------------------------------


def test_logs_help():
    runner = CliRunner()
    result = runner.invoke(logs, ["--help"])
    assert result.exit_code == 0
    assert "--follow" in result.output
    assert "--tail" in result.output
    assert "--container" in result.output


@patch("asya_lab.k_cli._run_cmd")
def test_logs_success(mock_run):
    mock_run.return_value = MagicMock(returncode=0)

    runner = CliRunner()
    with patch("asya_lab.k_cli._resolve_context", return_value=None):
        result = runner.invoke(logs, ["my-flow"])

    assert result.exit_code == 0
    cmd = mock_run.call_args[0][0]
    assert "kubectl" in cmd
    assert "logs" in cmd
    assert "asya-runtime" in cmd  # default container


@patch("asya_lab.k_cli._run_cmd")
def test_logs_with_follow_and_tail(mock_run):
    mock_run.return_value = MagicMock(returncode=0)

    runner = CliRunner()
    with patch("asya_lab.k_cli._resolve_context", return_value=None):
        result = runner.invoke(logs, ["my-flow", "--follow", "--tail", "100"])

    assert result.exit_code == 0
    cmd = mock_run.call_args[0][0]
    assert "-f" in cmd
    assert "--tail" in cmd
    assert "100" in cmd


# ---------------------------------------------------------------------------
# asya k edit
# ---------------------------------------------------------------------------


def test_edit_help():
    runner = CliRunner()
    result = runner.invoke(edit, ["--help"])
    assert result.exit_code == 0
    assert "actor_name" in result.output.lower()


def test_edit_no_asya_dir():
    runner = CliRunner()
    with patch("asya_lab.k_cli.find_asya_dir", return_value=None):
        result = runner.invoke(edit, ["my-actor"])
    assert result.exit_code != 0
    assert "No .asya/ directory" in result.output


def test_edit_actor_not_found(tmp_path):
    asya_dir = tmp_path / ".asya"
    manifests_dir = asya_dir / "manifests"
    manifests_dir.mkdir(parents=True)

    runner = CliRunner()
    with patch("asya_lab.k_cli.find_asya_dir", return_value=asya_dir):
        result = runner.invoke(edit, ["nonexistent-actor"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


@patch("os.execvp")
def test_edit_creates_patch_and_opens_editor(mock_execvp, tmp_path):
    asya_dir = tmp_path / ".asya"
    base_dir = asya_dir / "manifests" / "my-flow" / "base"
    base_dir.mkdir(parents=True)

    manifest = {
        "apiVersion": "asya.sh/v1alpha1",
        "kind": "AsyncActor",
        "metadata": {"name": "validate-order"},
        "spec": {"image": "test:v1"},
    }
    (base_dir / "asyncactor-validate-order.yaml").write_text(yaml.dump(manifest))

    runner = CliRunner()
    with (
        patch("asya_lab.k_cli.find_asya_dir", return_value=asya_dir),
        patch.dict("os.environ", {"EDITOR": "nano"}),
    ):
        runner.invoke(edit, ["validate-order"])

    # Patch file should be created
    patch_file = asya_dir / "manifests" / "my-flow" / "common" / "patch-validate-order.yaml"
    assert patch_file.exists()
    assert "validate-order" in patch_file.read_text()

    # Editor should be called
    mock_execvp.assert_called_once()
    assert "nano" in mock_execvp.call_args[0]


# ---------------------------------------------------------------------------
# asya k context
# ---------------------------------------------------------------------------


def test_context_list_help():
    runner = CliRunner()
    result = runner.invoke(context_group, ["list", "--help"])
    assert result.exit_code == 0


def test_context_list_no_contexts(tmp_path):
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir()
    (asya_dir / "config.yaml").write_text("var:\n  namespace: default\n")

    runner = CliRunner()
    with patch("asya_lab.k_cli.find_asya_dir", return_value=asya_dir):
        result = runner.invoke(context_group, ["list"])
    assert result.exit_code == 0
    assert "No contexts" in result.output


def test_context_list_with_contexts(tmp_path):
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir()
    config = {
        "contexts": {
            "stg": {"kubecontext": "my-stg", "namespace": "team-one"},
            "prod": {"kubecontext": "my-prod", "namespace": "prod", "readonly": True},
        },
        "default_context": "stg",
    }
    (asya_dir / "config.yaml").write_text(yaml.dump(config))

    runner = CliRunner()
    with patch("asya_lab.k_cli.find_asya_dir", return_value=asya_dir):
        result = runner.invoke(context_group, ["list"])
    assert result.exit_code == 0
    assert "stg" in result.output
    assert "prod" in result.output
    assert "readonly" in result.output
    assert "*" in result.output  # default marker


def test_context_use(tmp_path):
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir()
    config = {
        "contexts": {
            "stg": {"kubecontext": "my-stg", "namespace": "team-one"},
            "prod": {"kubecontext": "my-prod", "namespace": "prod"},
        },
        "default_context": "stg",
    }
    (asya_dir / "config.yaml").write_text(yaml.dump(config))

    runner = CliRunner()
    with patch("asya_lab.k_cli.find_asya_dir", return_value=asya_dir):
        result = runner.invoke(context_group, ["use", "prod"])
    assert result.exit_code == 0
    assert "prod" in result.output

    # Verify file was updated
    updated = yaml.safe_load((asya_dir / "config.yaml").read_text())
    assert updated["default_context"] == "prod"


def test_context_use_nonexistent(tmp_path):
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir()
    config = {
        "contexts": {"stg": {"kubecontext": "my-stg"}},
        "default_context": "stg",
    }
    (asya_dir / "config.yaml").write_text(yaml.dump(config))

    runner = CliRunner()
    with patch("asya_lab.k_cli.find_asya_dir", return_value=asya_dir):
        result = runner.invoke(context_group, ["use", "nonexistent"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# Field manager naming
# ---------------------------------------------------------------------------


@patch("asya_lab.k_cli.subprocess.run")
def test_apply_uses_correct_field_manager(mock_run, tmp_path):
    asya_dir = tmp_path / ".asya"
    base_dir = asya_dir / "manifests" / "order-processing" / "base"
    base_dir.mkdir(parents=True)
    (base_dir / "kustomization.yaml").write_text("resources: []")

    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="yaml", stderr=""),
        MagicMock(returncode=0, stdout="applied\n", stderr=""),
    ]

    runner = CliRunner()
    with (
        patch("asya_lab.k_cli.find_asya_dir", return_value=asya_dir),
        patch("asya_lab.k_cli._resolve_context", return_value=None),
    ):
        result = runner.invoke(apply, ["order-processing"])

    assert result.exit_code == 0
    apply_call = mock_run.call_args_list[1]
    apply_cmd = apply_call[0][0]
    assert "--field-manager=asya-flow-order-processing" in apply_cmd
