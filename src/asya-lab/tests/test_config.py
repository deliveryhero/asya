"""Tests for config loading and walk-up merge."""

from pathlib import Path

import pytest
from asya_lab.config.project import AsyaProject
from asya_lab.config.store import ConfigStore
from omegaconf import OmegaConf
from omegaconf.errors import InterpolationResolutionError


class TestFilenameToKey:
    def test_root_config(self, tmp_path: Path) -> None:
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("templates:\n  name: test\n")
        store = ConfigStore(tmp_path)
        assert OmegaConf.to_container(store.cfg) == {"templates": {"name": "test"}}

    def test_section_config(self, tmp_path: Path) -> None:
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("templates:\n  name: test\n")
        (asya_dir / "config.compiler.yaml").write_text("manifests: ./out\n")
        store = ConfigStore(tmp_path)
        container = OmegaConf.to_container(store.cfg)
        assert container["templates"] == {"name": "test"}
        assert "compiler" in container
        assert container["compiler"]["manifests"] is not None

    def test_multiple_sections(self, tmp_path: Path) -> None:
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("{}")
        (asya_dir / "config.compiler.yaml").write_text("rules: []\n")
        (asya_dir / "config.template.yaml").write_text("actor: default\n")
        store = ConfigStore(tmp_path)
        container = OmegaConf.to_container(store.cfg)
        assert container["compiler"] == {"rules": []}
        assert container["template"] == {"actor": "default"}


class TestDottedSectionSupport:
    def test_dotted_section_config(self, tmp_path: Path) -> None:
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("{}")
        (asya_dir / "config.compiler.rules.yaml").write_text("- match: test\n  treat-as: inline\n")
        store = ConfigStore(tmp_path)
        container = OmegaConf.to_container(store.cfg)
        assert "compiler" in container
        assert "rules" in container["compiler"]
        assert len(container["compiler"]["rules"]) > 0


class TestRelativePathResolution:
    def test_dot_slash_resolved(self, tmp_path: Path) -> None:
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("templates:\n  base_path: ./\n")
        store = ConfigStore(tmp_path)
        resolved = OmegaConf.to_container(store.cfg, resolve=False)
        assert not resolved["templates"]["base_path"].startswith("./")
        assert str(tmp_path) in resolved["templates"]["base_path"]

    def test_interpolation_preserved(self, tmp_path: Path) -> None:
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("templates:\n  root: ./\ncompiler:\n  out: ${templates.root}/compiled\n")
        store = ConfigStore(tmp_path)
        resolved = OmegaConf.to_container(store.cfg, resolve=False)
        assert "${templates.root}" in resolved["compiler"]["out"]


class TestWalkUpMerge:
    def test_single_config(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("templates:\n  name: root\n")
        project = AsyaProject.from_dir(tmp_path)
        assert OmegaConf.to_container(project.cfg)["templates"]["name"] == "root"

    def test_child_overrides_parent(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        root_asya = tmp_path / ".asya"
        root_asya.mkdir()
        (root_asya / "config.yaml").write_text("templates:\n  name: root\n  registry: ghcr.io/org\n")
        team_dir = tmp_path / "team"
        team_dir.mkdir()
        team_asya = team_dir / ".asya"
        team_asya.mkdir()
        (team_asya / "config.yaml").write_text("templates:\n  registry: ghcr.io/team\n")
        project = AsyaProject.from_dir(team_dir)
        container = OmegaConf.to_container(project.cfg)
        assert container["templates"]["name"] == "root"
        assert container["templates"]["registry"] == "ghcr.io/team"

    def test_no_asya_raises(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        with pytest.raises(FileNotFoundError, match="No .asya/ directory found"):
            AsyaProject.from_dir(tmp_path)

    def test_interpolation_across_levels(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        root_asya = tmp_path / ".asya"
        root_asya.mkdir()
        (root_asya / "config.yaml").write_text("templates:\n  org: my-org\n")
        team_dir = tmp_path / "team"
        team_dir.mkdir()
        team_asya = team_dir / ".asya"
        team_asya.mkdir()
        (team_asya / "config.yaml").write_text("templates:\n  image: ${templates.org}/app\n")
        project = AsyaProject.from_dir(team_dir)
        assert project.cfg.templates.image == "my-org/app"


class TestCustomResolvers:
    def test_env_resolver(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ASYA_TEST_VAR", "hello")
        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("templates:\n  val: ${env:ASYA_TEST_VAR}\n")
        project = AsyaProject.from_dir(tmp_path)
        assert project.cfg.templates.val == "hello"

    def test_arg_resolver(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("templates:\n  tag: ${arg:tag}\n")
        project = AsyaProject.from_dir(tmp_path, arg_values={"tag": "v1.0"})
        assert project.cfg.templates.tag == "v1.0"

    def test_arg_resolver_with_default(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("templates:\n  replicas: ${arg:replicas,5}\n")
        project = AsyaProject.from_dir(tmp_path)
        assert project.cfg.templates.replicas == "5"

    def test_arg_resolver_missing_raises(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("templates:\n  tag: ${arg:tag}\n")
        project = AsyaProject.from_dir(tmp_path)
        with pytest.raises(InterpolationResolutionError, match="Missing --arg tag"):
            _ = project.cfg.templates.tag


class TestSectionMerge:
    def test_config_section_and_dotted_file_merge(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("compiler:\n  manifests: ./out\n")
        (asya_dir / "config.compiler.rules.yaml").write_text("- match: test\n")
        project = AsyaProject.from_dir(tmp_path)
        container = OmegaConf.to_container(project.cfg, resolve=False)
        assert "manifests" in container["compiler"]
        assert "rules" in container["compiler"]
