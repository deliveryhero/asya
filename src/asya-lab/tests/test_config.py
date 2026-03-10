"""Tests for config loading and walk-up merge."""

from pathlib import Path

import pytest
from asya_lab.config.config import load_asya_dir, load_effective_config
from omegaconf import OmegaConf
from omegaconf.errors import InterpolationResolutionError


class TestFilenameToKey:
    def test_root_config(self, tmp_path: Path) -> None:
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("var:\n  name: test\n")
        cfg = load_asya_dir(asya_dir)
        assert OmegaConf.to_container(cfg) == {"var": {"name": "test"}}

    def test_section_config(self, tmp_path: Path) -> None:
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("var:\n  name: test\n")
        (asya_dir / "config.compiler.yaml").write_text("manifests: ./out\n")
        cfg = load_asya_dir(asya_dir)
        container = OmegaConf.to_container(cfg)
        assert container["var"] == {"name": "test"}
        assert "compiler" in container
        assert container["compiler"]["manifests"] is not None

    def test_multiple_sections(self, tmp_path: Path) -> None:
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("{}")
        (asya_dir / "config.compiler.yaml").write_text("rules: []\n")
        (asya_dir / "config.template.yaml").write_text("actor: default\n")
        cfg = load_asya_dir(asya_dir)
        container = OmegaConf.to_container(cfg)
        assert container["compiler"] == {"rules": []}
        assert container["template"] == {"actor": "default"}


class TestDirectoryToKey:
    def test_directory_with_yaml(self, tmp_path: Path) -> None:
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("{}")
        compiler_dir = asya_dir / "compiler"
        compiler_dir.mkdir()
        (compiler_dir / "rules.yaml").write_text("- match: test\n  treat-as: inline\n")
        cfg = load_asya_dir(asya_dir)
        container = OmegaConf.to_container(cfg)
        assert "compiler" in container
        assert "rules" in container["compiler"]

    def test_nested_directory(self, tmp_path: Path) -> None:
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("{}")
        templates_dir = asya_dir / "compiler" / "templates"
        templates_dir.mkdir(parents=True)
        (templates_dir / "actor.yaml").write_text("kind: AsyncActor\n")
        cfg = load_asya_dir(asya_dir)
        container = OmegaConf.to_container(cfg)
        assert container["compiler"]["templates"]["actor"] == {"kind": "AsyncActor"}

    def test_manifests_dir_ignored(self, tmp_path: Path) -> None:
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("{}")
        manifests = asya_dir / "manifests"
        manifests.mkdir()
        (manifests / "something.yaml").write_text("key: val\n")
        cfg = load_asya_dir(asya_dir)
        container = OmegaConf.to_container(cfg)
        assert "manifests" not in container


class TestRelativePathResolution:
    def test_dot_slash_resolved(self, tmp_path: Path) -> None:
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("var:\n  project_root: ./\n")
        cfg = load_asya_dir(asya_dir)
        resolved = OmegaConf.to_container(cfg, resolve=False)
        assert not resolved["var"]["project_root"].startswith("./")
        assert str(tmp_path) in resolved["var"]["project_root"]

    def test_interpolation_preserved(self, tmp_path: Path) -> None:
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("var:\n  root: ./\ncompiler:\n  out: ${var.root}/compiled\n")
        cfg = load_asya_dir(asya_dir)
        resolved = OmegaConf.to_container(cfg, resolve=False)
        assert "${var.root}" in resolved["compiler"]["out"]


class TestWalkUpMerge:
    def test_single_config(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("var:\n  name: root\n")
        cfg = load_effective_config(tmp_path)
        assert OmegaConf.to_container(cfg)["var"]["name"] == "root"

    def test_child_overrides_parent(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        root_asya = tmp_path / ".asya"
        root_asya.mkdir()
        (root_asya / "config.yaml").write_text("var:\n  name: root\n  registry: ghcr.io/org\n")
        team_dir = tmp_path / "team"
        team_dir.mkdir()
        team_asya = team_dir / ".asya"
        team_asya.mkdir()
        (team_asya / "config.yaml").write_text("var:\n  registry: ghcr.io/team\n")
        cfg = load_effective_config(team_dir)
        container = OmegaConf.to_container(cfg)
        assert container["var"]["name"] == "root"
        assert container["var"]["registry"] == "ghcr.io/team"

    def test_no_asya_raises(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        with pytest.raises(FileNotFoundError, match="No .asya/ directory found"):
            load_effective_config(tmp_path)

    def test_interpolation_across_levels(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        root_asya = tmp_path / ".asya"
        root_asya.mkdir()
        (root_asya / "config.yaml").write_text("var:\n  org: my-org\n")
        team_dir = tmp_path / "team"
        team_dir.mkdir()
        team_asya = team_dir / ".asya"
        team_asya.mkdir()
        (team_asya / "config.yaml").write_text("var:\n  image: ${var.org}/app\n")
        cfg = load_effective_config(team_dir)
        assert cfg.var.image == "my-org/app"


class TestCustomResolvers:
    def test_env_resolver(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ASYA_TEST_VAR", "hello")
        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("var:\n  val: ${env:ASYA_TEST_VAR}\n")
        cfg = load_effective_config(tmp_path)
        assert cfg.var.val == "hello"

    def test_arg_resolver(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("var:\n  tag: ${arg:tag}\n")
        cfg = load_effective_config(tmp_path, arg_values={"tag": "v1.0"})
        assert cfg.var.tag == "v1.0"

    def test_arg_resolver_with_default(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("var:\n  replicas: ${arg:replicas,5}\n")
        cfg = load_effective_config(tmp_path)
        assert cfg.var.replicas == "5"

    def test_arg_resolver_missing_raises(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("var:\n  tag: ${arg:tag}\n")
        cfg = load_effective_config(tmp_path)
        with pytest.raises(InterpolationResolutionError, match="Missing --arg tag"):
            _ = cfg.var.tag

    def test_dynamic_resolver_outside_compile(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("var:\n  actor: ${dynamic:actor}\n")
        cfg = load_effective_config(tmp_path)
        with pytest.raises(InterpolationResolutionError, match="only available during compilation"):
            _ = cfg.var.actor


class TestSectionMerge:
    def test_config_section_and_directory_merge(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("compiler:\n  manifests: ./out\n")
        compiler_dir = asya_dir / "compiler"
        compiler_dir.mkdir()
        (compiler_dir / "rules.yaml").write_text("- match: test\n")
        cfg = load_effective_config(tmp_path)
        container = OmegaConf.to_container(cfg, resolve=False)
        assert "manifests" in container["compiler"]
        assert "rules" in container["compiler"]
