"""Tests for asya init scaffolding."""

from pathlib import Path

from asya_lab.init import init_project


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
        assert "project_root" in content

    def test_creates_actor_template(self, tmp_path: Path) -> None:
        init_project(tmp_path)
        template = tmp_path / ".asya" / "compiler" / "templates" / "actor.yaml"
        assert template.exists()
        content = template.read_text()
        assert "AsyncActor" in content

    def test_creates_rules_yaml(self, tmp_path: Path) -> None:
        init_project(tmp_path)
        rules = tmp_path / ".asya" / "compiler" / "rules.yaml"
        assert rules.exists()

    def test_creates_manifests_dir(self, tmp_path: Path) -> None:
        init_project(tmp_path)
        manifests = tmp_path / ".asya" / "manifests"
        assert manifests.is_dir()

    def test_updates_gitignore(self, tmp_path: Path) -> None:
        init_project(tmp_path)
        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        assert ".env.secret" in gitignore.read_text()

    def test_gitignore_no_duplicate(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text(".env.secret\n")
        init_project(tmp_path)
        content = (tmp_path / ".gitignore").read_text()
        assert content.count(".env.secret") == 1

    def test_gitignore_appends_to_existing(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("*.pyc\n")
        init_project(tmp_path)
        content = (tmp_path / ".gitignore").read_text()
        assert "*.pyc" in content
        assert ".env.secret" in content


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
        (asya_dir / "config.yaml").write_text("var:\n  name: existing\n")

        init_project(tmp_path)
        assert (asya_dir / "compiler" / "templates" / "actor.yaml").exists()
        assert (asya_dir / "compiler" / "rules.yaml").exists()
        assert (asya_dir / "manifests").is_dir()


class TestInitConfig:
    def test_config_loadable_by_omegaconf(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        init_project(tmp_path, image_registry="ghcr.io/test")

        from asya_lab.config.config import load_effective_config

        cfg = load_effective_config(tmp_path)
        assert cfg.var.image_registry == "ghcr.io/test"
        assert cfg.var.transport == "sqs"
