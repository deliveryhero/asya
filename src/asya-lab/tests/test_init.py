"""Tests for asya init scaffolding."""

from pathlib import Path

import yaml
from asya_lab.init import init_project, scan_and_generate_skaffold


class TestInitProject:
    def test_creates_asya_directory(self, tmp_path: Path) -> None:
        asya_dir = init_project(tmp_path)
        assert asya_dir == tmp_path / ".asya"
        assert asya_dir.is_dir()

    def test_creates_config_yaml(self, tmp_path: Path) -> None:
        init_project(tmp_path)
        config = tmp_path / ".asya" / "config.yaml"
        assert config.exists()
        content = config.read_text()
        assert "templates:" in content
        assert "compiler:" in content

    def test_creates_actor_template(self, tmp_path: Path) -> None:
        init_project(tmp_path)
        template = tmp_path / ".asya" / "templates" / "actor.yaml"
        assert template.exists()
        assert "AsyncActor" in template.read_text()

    def test_creates_rules_yaml(self, tmp_path: Path) -> None:
        init_project(tmp_path)
        rules = tmp_path / ".asya" / "config.compiler.rules.yaml"
        assert rules.exists()

    def test_no_build_section(self, tmp_path: Path) -> None:
        init_project(tmp_path)
        config = tmp_path / ".asya" / "config.yaml"
        assert "build:" not in config.read_text()

    def test_config_has_flow_name_interpolation(self, tmp_path: Path) -> None:
        init_project(tmp_path)
        config = tmp_path / ".asya" / "config.yaml"
        assert "${arg:flow_name}" in config.read_text()


class TestInitIdempotent:
    def test_preserves_existing_config(self, tmp_path: Path) -> None:
        init_project(tmp_path)
        config = tmp_path / ".asya" / "config.yaml"
        original = config.read_text()

        init_project(tmp_path)
        assert config.read_text() == original

    def test_preserves_existing_template(self, tmp_path: Path) -> None:
        init_project(tmp_path)
        template = tmp_path / ".asya" / "templates" / "actor.yaml"
        template.write_text("custom: content\n")

        init_project(tmp_path)
        assert template.read_text() == "custom: content\n"

    def test_adds_missing_files(self, tmp_path: Path) -> None:
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("templates:\n  name: existing\n")

        init_project(tmp_path)
        assert (asya_dir / "templates" / "actor.yaml").exists()
        assert (asya_dir / "templates" / "router.yaml").exists()
        assert (asya_dir / "config.compiler.rules.yaml").exists()


class TestScanSkaffold:
    def test_discovers_dockerfile(self, tmp_path: Path) -> None:
        (tmp_path / "actors" / "nlp").mkdir(parents=True)
        (tmp_path / "actors" / "nlp" / "Dockerfile").write_text("FROM python:3.13\n")

        results = scan_and_generate_skaffold(tmp_path)
        created = [r for r in results if r.created]
        assert len(created) == 1
        assert created[0].image == "actors-nlp"

        skaffold = yaml.safe_load((tmp_path / "actors" / "nlp" / "skaffold.yaml").read_text())
        assert skaffold["apiVersion"] == "skaffold/v4beta13"
        assert len(skaffold["build"]["artifacts"]) == 1
        assert skaffold["build"]["artifacts"][0]["docker"]["dockerfile"] == "Dockerfile"

    def test_ignores_pyproject_without_dockerfile(self, tmp_path: Path) -> None:
        (tmp_path / "libs" / "common").mkdir(parents=True)
        (tmp_path / "libs" / "common" / "pyproject.toml").write_text("[project]\nname='common'\n")

        results = scan_and_generate_skaffold(tmp_path)
        assert len(results) == 0

    def test_idempotent_no_duplicates(self, tmp_path: Path) -> None:
        (tmp_path / "svc").mkdir()
        (tmp_path / "svc" / "Dockerfile").write_text("FROM python:3.13\n")

        first = scan_and_generate_skaffold(tmp_path)
        assert len([r for r in first if r.created]) == 1

        second = scan_and_generate_skaffold(tmp_path)
        assert len([r for r in second if r.created]) == 0

        skaffold = yaml.safe_load((tmp_path / "svc" / "skaffold.yaml").read_text())
        assert len(skaffold["build"]["artifacts"]) == 1

    def test_multiple_dockerfiles(self, tmp_path: Path) -> None:
        (tmp_path / "team-a" / "nlp").mkdir(parents=True)
        (tmp_path / "team-a" / "nlp" / "Dockerfile").write_text("FROM python:3.13\n")
        (tmp_path / "team-b" / "api").mkdir(parents=True)
        (tmp_path / "team-b" / "api" / "Dockerfile").write_text("FROM python:3.13\n")

        results = scan_and_generate_skaffold(tmp_path)
        created = [r for r in results if r.created]
        assert len(created) == 2

        assert (tmp_path / "team-a" / "nlp" / "skaffold.yaml").exists()
        assert (tmp_path / "team-b" / "api" / "skaffold.yaml").exists()

    def test_skips_hidden_and_venv_dirs(self, tmp_path: Path) -> None:
        (tmp_path / ".venv" / "lib").mkdir(parents=True)
        (tmp_path / ".venv" / "lib" / "Dockerfile").write_text("FROM x\n")
        (tmp_path / ".git" / "hooks").mkdir(parents=True)
        (tmp_path / ".git" / "hooks" / "Dockerfile").write_text("FROM x\n")

        results = scan_and_generate_skaffold(tmp_path)
        assert len(results) == 0


class TestSkaffoldImageResolution:
    def test_resolve_image_from_skaffold(self, tmp_path: Path) -> None:
        """resolve_image finds the image from skaffold.yaml artifacts."""
        from asya_lab.config.project import AsyaProject

        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("templates:\n  namespace: test\n")

        # Create a skaffold.yaml with an artifact
        pkg_dir = tmp_path / "src" / "nlp"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "skaffold.yaml").write_text(
            yaml.dump(
                {
                    "apiVersion": "skaffold/v4beta13",
                    "kind": "Config",
                    "build": {"artifacts": [{"image": "team-a-nlp", "context": "."}]},
                }
            )
        )
        # Create a Python module in the context
        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "analyzer.py").write_text("def analyze(p): return p\n")

        project = AsyaProject.from_dir(tmp_path)
        artifacts = project._collect_skaffold_artifacts()
        assert len(artifacts) == 1
        assert artifacts[0][1] == "team-a-nlp"
        assert str(artifacts[0][0]).endswith("src/nlp")


class TestInitConfig:
    def test_config_loadable_by_omegaconf(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        init_project(tmp_path)

        from asya_lab.config.project import AsyaProject

        project = AsyaProject.from_dir(tmp_path, arg_values={"flow_name": "test-flow"})
        cfg = project.cfg
        assert "compiler" in cfg
