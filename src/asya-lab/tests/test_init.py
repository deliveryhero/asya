"""Tests for asya init scaffolding."""

from pathlib import Path

from asya_lab.init import init_project


_DEFAULTS = {"registry": "ghcr.io/test", "transport": "sqs"}


class TestInitProject:
    def test_creates_asya_directory(self, tmp_path: Path) -> None:
        asya_dir = init_project(tmp_path, **_DEFAULTS)
        assert asya_dir == tmp_path / ".asya"
        assert asya_dir.is_dir()

    def test_creates_config_yaml(self, tmp_path: Path) -> None:
        init_project(tmp_path, registry="ghcr.io/test", transport="sqs")
        config = tmp_path / ".asya" / "config.yaml"
        assert config.exists()
        content = config.read_text()
        assert "ghcr.io/test" in content
        assert "templates:" in content

    def test_creates_actor_template(self, tmp_path: Path) -> None:
        init_project(tmp_path, **_DEFAULTS)
        template = tmp_path / ".asya" / "compiler" / "templates" / "actor.yaml"
        assert template.exists()
        assert "AsyncActor" in template.read_text()

    def test_creates_rules_yaml(self, tmp_path: Path) -> None:
        init_project(tmp_path, **_DEFAULTS)
        rules = tmp_path / ".asya" / "config.compiler.rules.yaml"
        assert rules.exists()

    def test_no_manifests_dir(self, tmp_path: Path) -> None:
        init_project(tmp_path, **_DEFAULTS)
        manifests = tmp_path / ".asya" / "manifests"
        assert not manifests.exists()

    def test_no_gitignore(self, tmp_path: Path) -> None:
        init_project(tmp_path, **_DEFAULTS)
        gitignore = tmp_path / ".gitignore"
        assert not gitignore.exists()

    def test_transport_in_config(self, tmp_path: Path) -> None:
        init_project(tmp_path, registry="ghcr.io/test", transport="rabbitmq")
        config = tmp_path / ".asya" / "config.yaml"
        assert "transport: rabbitmq" in config.read_text()

    def test_registry_in_build_entry(self, tmp_path: Path) -> None:
        init_project(tmp_path, registry="ghcr.io/acme", transport="sqs")
        config = tmp_path / ".asya" / "config.yaml"
        content = config.read_text()
        assert "ghcr.io/acme/*:latest" in content

    def test_no_compiler_image_registry(self, tmp_path: Path) -> None:
        init_project(tmp_path, registry="ghcr.io/test", transport="sqs")
        config = tmp_path / ".asya" / "config.yaml"
        assert "image_registry" not in config.read_text()


class TestInitIdempotent:
    def test_preserves_existing_config(self, tmp_path: Path) -> None:
        init_project(tmp_path, registry="ghcr.io/first", transport="sqs")
        config = tmp_path / ".asya" / "config.yaml"
        original = config.read_text()

        init_project(tmp_path, registry="ghcr.io/second", transport="rabbitmq")
        assert config.read_text() == original

    def test_preserves_existing_template(self, tmp_path: Path) -> None:
        init_project(tmp_path, **_DEFAULTS)
        template = tmp_path / ".asya" / "compiler" / "templates" / "actor.yaml"
        template.write_text("custom: content\n")

        init_project(tmp_path, **_DEFAULTS)
        assert template.read_text() == "custom: content\n"

    def test_adds_missing_files(self, tmp_path: Path) -> None:
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("templates:\n  name: existing\n")

        init_project(tmp_path, **_DEFAULTS)
        assert (asya_dir / "compiler" / "templates" / "actor.yaml").exists()
        assert (asya_dir / "compiler" / "templates" / "router.yaml").exists()
        assert (asya_dir / "config.compiler.rules.yaml").exists()


class TestInitConfig:
    def test_config_loadable_by_omegaconf(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        init_project(tmp_path, registry="ghcr.io/test", transport="sqs")

        from asya_lab.config.project import AsyaProject

        cfg = AsyaProject.from_dir(tmp_path).cfg
        assert cfg.templates.transport == "sqs"
        assert cfg.build[0].module == "*"
        assert "ghcr.io/test" in cfg.build[0].image
