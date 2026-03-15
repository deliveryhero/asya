"""Tests for asya init scaffolding."""

from pathlib import Path
from unittest.mock import patch

from asya_lab.init import detect_transport, init_project


class TestInitProject:
    def test_creates_asya_directory(self, tmp_path: Path) -> None:
        asya_dir = init_project(tmp_path)
        assert asya_dir == tmp_path / ".asya"
        assert asya_dir.is_dir()

    def test_creates_config_yaml(self, tmp_path: Path) -> None:
        init_project(tmp_path, image_registry="ghcr.io/test")
        config = tmp_path / ".asya" / "config.yaml"
        assert config.exists()
        content = config.read_text()
        assert "ghcr.io/test" in content
        assert "templates:" in content

    def test_creates_actor_template(self, tmp_path: Path) -> None:
        init_project(tmp_path)
        template = tmp_path / ".asya" / "compiler" / "templates" / "actor.yaml"
        assert template.exists()
        content = template.read_text()
        assert "AsyncActor" in content

    def test_creates_rules_yaml(self, tmp_path: Path) -> None:
        init_project(tmp_path)
        rules = tmp_path / ".asya" / "config.compiler.rules.yaml"
        assert rules.exists()

    def test_no_manifests_dir(self, tmp_path: Path) -> None:
        init_project(tmp_path)
        manifests = tmp_path / ".asya" / "manifests"
        assert not manifests.exists()

    def test_no_gitignore(self, tmp_path: Path) -> None:
        init_project(tmp_path)
        gitignore = tmp_path / ".gitignore"
        assert not gitignore.exists()

    def test_transport_in_config(self, tmp_path: Path) -> None:
        init_project(tmp_path, transport="rabbitmq")
        config = tmp_path / ".asya" / "config.yaml"
        assert "transport: rabbitmq" in config.read_text()

    def test_default_transport_is_sqs(self, tmp_path: Path) -> None:
        init_project(tmp_path)
        config = tmp_path / ".asya" / "config.yaml"
        assert "transport: sqs" in config.read_text()


class TestInitIdempotent:
    def test_preserves_existing_config(self, tmp_path: Path) -> None:
        init_project(tmp_path, image_registry="ghcr.io/first")
        config = tmp_path / ".asya" / "config.yaml"
        original = config.read_text()

        init_project(tmp_path, image_registry="ghcr.io/second")
        assert config.read_text() == original

    def test_preserves_existing_template(self, tmp_path: Path) -> None:
        init_project(tmp_path)
        template = tmp_path / ".asya" / "compiler" / "templates" / "actor.yaml"
        template.write_text("custom: content\n")

        init_project(tmp_path)
        assert template.read_text() == "custom: content\n"

    def test_adds_missing_files(self, tmp_path: Path) -> None:
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("templates:\n  name: existing\n")

        init_project(tmp_path)
        assert (asya_dir / "compiler" / "templates" / "actor.yaml").exists()
        assert (asya_dir / "compiler" / "templates" / "router.yaml").exists()
        assert (asya_dir / "config.compiler.rules.yaml").exists()


class TestInitConfig:
    def test_config_loadable_by_omegaconf(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        init_project(tmp_path, image_registry="ghcr.io/test")

        from asya_lab.config.project import AsyaProject

        cfg = AsyaProject.from_dir(tmp_path).cfg
        assert cfg.compiler.image_registry == "ghcr.io/test"
        assert cfg.templates.transport == "sqs"


class TestDetectTransport:
    def test_returns_transport_on_single_match(self) -> None:
        with patch("asya_lab.init.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "sqs"
            assert detect_transport() == "sqs"

    def test_returns_none_on_multiple_transports(self) -> None:
        with patch("asya_lab.init.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "sqs rabbitmq"
            assert detect_transport() is None

    def test_returns_none_on_kubectl_failure(self) -> None:
        with patch("asya_lab.init.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            assert detect_transport() is None

    def test_returns_none_when_kubectl_missing(self) -> None:
        with patch("asya_lab.init.subprocess.run", side_effect=FileNotFoundError):
            assert detect_transport() is None

    def test_returns_none_on_empty_output(self) -> None:
        with patch("asya_lab.init.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            assert detect_transport() is None
