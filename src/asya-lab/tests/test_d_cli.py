"""Tests for the Docker Compose CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import yaml
from asya_lab.d_cli import _get_compose_cmd, _reset_compose_cmd, _resolve_target, d
from click.testing import CliRunner


def _make_actor_yaml(name: str, handler: str = "mod.func", image: str = "my-image:v1") -> dict:
    return {
        "apiVersion": "asya.sh/v1alpha1",
        "kind": "AsyncActor",
        "metadata": {"name": name},
        "spec": {
            "actor": name,
            "transport": "sqs",
            "image": image,
            "handler": handler,
        },
    }


@pytest.fixture(autouse=True)
def _reset_compose_cache():
    """Reset cached compose command between tests."""
    _reset_compose_cmd()
    yield
    _reset_compose_cmd()


class TestResolveTarget:
    def test_py_file(self, tmp_path, monkeypatch):
        flow_file = tmp_path / "order_processing.py"
        flow_file.write_text("# flow")
        monkeypatch.chdir(tmp_path)

        name, source = _resolve_target(str(flow_file))
        assert name == "order-processing"
        assert source == flow_file

    def test_kebab_name(self):
        name, source = _resolve_target("order-processing")
        assert name == "order-processing"
        assert source is None

    def test_snake_name(self):
        name, source = _resolve_target("order_processing")
        assert name == "order-processing"
        assert source is None

    def test_missing_py_file(self):
        with pytest.raises(SystemExit):
            _resolve_target("nonexistent.py")


class TestGetComposeCmd:
    def test_from_config(self, tmp_path, monkeypatch):
        """Reads docker.compose_command from .asya/config.yaml."""
        monkeypatch.chdir(tmp_path)
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("docker:\n  compose_command: docker-compose\n")

        cmd = _get_compose_cmd()
        assert cmd == ["docker-compose"]

    def test_from_config_multi_word(self, tmp_path, monkeypatch):
        """Supports multi-word compose commands like 'docker compose'."""
        monkeypatch.chdir(tmp_path)
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("docker:\n  compose_command: docker compose\n")

        cmd = _get_compose_cmd()
        assert cmd == ["docker", "compose"]

    @patch("asya_lab.d_cli.subprocess.run")
    def test_autodetect_v2(self, mock_run, tmp_path, monkeypatch):
        """Auto-detects docker compose v2 plugin."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".asya").mkdir()
        (tmp_path / ".asya" / "config.yaml").write_text("templates: {}\n")

        mock_run.return_value = MagicMock(returncode=0)

        cmd = _get_compose_cmd()
        assert cmd == ["docker", "compose"]

    @patch("asya_lab.d_cli.shutil.which", return_value="/usr/bin/docker-compose")
    @patch("asya_lab.d_cli.subprocess.run", side_effect=FileNotFoundError)
    def test_fallback_v1(self, _mock_run, _mock_which, tmp_path, monkeypatch):
        """Falls back to docker-compose v1 when v2 plugin unavailable."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".asya").mkdir()
        (tmp_path / ".asya" / "config.yaml").write_text("templates: {}\n")

        cmd = _get_compose_cmd()
        assert cmd == ["docker-compose"]

    def test_caches_result(self, tmp_path, monkeypatch):
        """Compose command is cached after first resolution."""
        monkeypatch.chdir(tmp_path)
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("docker:\n  compose_command: custom-compose\n")

        cmd1 = _get_compose_cmd()
        cmd2 = _get_compose_cmd()
        assert cmd1 == cmd2 == ["custom-compose"]


class TestDCliHelp:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(d, ["--help"])
        assert result.exit_code == 0
        assert "up" in result.output
        assert "down" in result.output
        assert "send" in result.output
        assert "logs" in result.output

    def test_up_help(self):
        runner = CliRunner()
        result = runner.invoke(d, ["up", "--help"])
        assert result.exit_code == 0
        assert "TARGET" in result.output

    def test_down_help(self):
        runner = CliRunner()
        result = runner.invoke(d, ["down", "--help"])
        assert result.exit_code == 0

    def test_send_help(self):
        runner = CliRunner()
        result = runner.invoke(d, ["send", "--help"])
        assert result.exit_code == 0
        assert "ACTOR" in result.output
        assert "PAYLOAD" in result.output

    def test_logs_help(self):
        runner = CliRunner()
        result = runner.invoke(d, ["logs", "--help"])
        assert result.exit_code == 0


class TestCmdUp:
    @patch("asya_lab.d_cli._get_compose_cmd", return_value=["docker", "compose"])
    @patch("asya_lab.d_cli.subprocess.run")
    def test_up_from_manifests(self, mock_run, _mock_compose_cmd, tmp_path):
        asya_dir = tmp_path / ".asya"
        manifests_dir = asya_dir / "manifests" / "my-flow"
        manifests_dir.mkdir(parents=True)

        actor = _make_actor_yaml("actor-a")
        (manifests_dir / "actor.yaml").write_text(yaml.dump(actor))

        mock_run.return_value = MagicMock(returncode=0)

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            import os
            import shutil

            shutil.copytree(str(asya_dir), os.path.join(td, ".asya"))
            result = runner.invoke(d, ["up", "my-flow"])

        assert result.exit_code == 0, result.output
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0:2] == ["docker", "compose"]
        assert "up" in call_args
        assert "-d" in call_args

    @patch("asya_lab.d_cli._get_compose_cmd", return_value=["docker", "compose"])
    @patch("asya_lab.d_cli.subprocess.run")
    def test_up_no_manifests(self, mock_run, _mock_compose_cmd, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            import os

            os.makedirs(os.path.join(td, ".asya"))
            result = runner.invoke(d, ["up", "nonexistent"])

        assert result.exit_code != 0

    @patch("asya_lab.d_cli._get_compose_cmd", return_value=["docker", "compose"])
    @patch("asya_lab.d_cli.subprocess.run")
    def test_up_with_build(self, mock_run, _mock_compose_cmd, tmp_path):
        asya_dir = tmp_path / ".asya"
        manifests_dir = asya_dir / "manifests" / "my-flow"
        manifests_dir.mkdir(parents=True)

        actor = _make_actor_yaml("actor-a")
        (manifests_dir / "actor.yaml").write_text(yaml.dump(actor))

        mock_run.return_value = MagicMock(returncode=0)

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            import os
            import shutil

            shutil.copytree(str(asya_dir), os.path.join(td, ".asya"))
            result = runner.invoke(d, ["up", "my-flow", "--build"])

        assert result.exit_code == 0, result.output
        call_args = mock_run.call_args[0][0]
        assert "--build" in call_args


class TestCmdDown:
    @patch("asya_lab.d_cli._get_compose_cmd", return_value=["docker", "compose"])
    @patch("asya_lab.d_cli.subprocess.run")
    def test_down(self, mock_run, _mock_compose_cmd, tmp_path):
        asya_dir = tmp_path / ".asya"
        compose_dir = asya_dir / "compose"
        compose_dir.mkdir(parents=True)
        (compose_dir / "my-flow.yaml").write_text("services: {}")

        mock_run.return_value = MagicMock(returncode=0)

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            import os
            import shutil

            shutil.copytree(str(asya_dir), os.path.join(td, ".asya"))
            result = runner.invoke(d, ["down", "my-flow"])

        assert result.exit_code == 0, result.output
        call_args = mock_run.call_args[0][0]
        assert "down" in call_args

    @patch("asya_lab.d_cli._get_compose_cmd", return_value=["docker", "compose"])
    @patch("asya_lab.d_cli.subprocess.run")
    def test_down_with_volumes(self, mock_run, _mock_compose_cmd, tmp_path):
        asya_dir = tmp_path / ".asya"
        compose_dir = asya_dir / "compose"
        compose_dir.mkdir(parents=True)
        (compose_dir / "my-flow.yaml").write_text("services: {}")

        mock_run.return_value = MagicMock(returncode=0)

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            import os
            import shutil

            shutil.copytree(str(asya_dir), os.path.join(td, ".asya"))
            result = runner.invoke(d, ["down", "my-flow", "-v"])

        assert result.exit_code == 0, result.output
        call_args = mock_run.call_args[0][0]
        assert "-v" in call_args

    def test_down_no_compose_file(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            import os

            os.makedirs(os.path.join(td, ".asya"))
            result = runner.invoke(d, ["down", "nonexistent"])

        assert result.exit_code != 0


class TestCmdLogs:
    @patch("asya_lab.d_cli._get_compose_cmd", return_value=["docker", "compose"])
    @patch("asya_lab.d_cli.subprocess.run")
    def test_logs_follow(self, mock_run, _mock_compose_cmd, tmp_path):
        asya_dir = tmp_path / ".asya"
        compose_dir = asya_dir / "compose"
        compose_dir.mkdir(parents=True)
        (compose_dir / "my-flow.yaml").write_text("services: {}")

        mock_run.return_value = MagicMock(returncode=0)

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            import os
            import shutil

            shutil.copytree(str(asya_dir), os.path.join(td, ".asya"))
            result = runner.invoke(d, ["logs", "my-flow", "-f"])

        assert result.exit_code == 0, result.output
        call_args = mock_run.call_args[0][0]
        assert "logs" in call_args
        assert "-f" in call_args

    @patch("asya_lab.d_cli._get_compose_cmd", return_value=["docker", "compose"])
    @patch("asya_lab.d_cli.subprocess.run")
    def test_logs_tail(self, mock_run, _mock_compose_cmd, tmp_path):
        asya_dir = tmp_path / ".asya"
        compose_dir = asya_dir / "compose"
        compose_dir.mkdir(parents=True)
        (compose_dir / "my-flow.yaml").write_text("services: {}")

        mock_run.return_value = MagicMock(returncode=0)

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            import os
            import shutil

            shutil.copytree(str(asya_dir), os.path.join(td, ".asya"))
            result = runner.invoke(d, ["logs", "my-flow", "--tail", "100"])

        assert result.exit_code == 0, result.output
        call_args = mock_run.call_args[0][0]
        assert "--tail" in call_args
        assert "100" in call_args


class TestCmdSend:
    def test_send_invalid_json(self):
        runner = CliRunner()
        result = runner.invoke(d, ["send", "my-actor", "not-json"])
        assert result.exit_code != 0

    @patch("asya_lab.d_cli.socket.socket")
    def test_send_valid(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock

        with patch("asya_lab.d_cli.Path.exists", return_value=True):
            runner = CliRunner()
            result = runner.invoke(d, ["send", "my-actor", '{"key": "value"}'])

        assert result.exit_code == 0, result.output
        mock_sock.connect.assert_called_once()
        assert mock_sock.sendall.call_count == 2
        mock_sock.close.assert_called_once()
