"""Component tests for FlowCompiler public API."""

import textwrap
from pathlib import Path

import pytest

from asya_cli.flow import FlowCompiler
from asya_cli.flow.errors import FlowCompileError


class TestCompile:
    """Test FlowCompiler.compile() method."""

    def test_compile_single_actor_flow_generates_metadata(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler_a(p)
                return p
        """)
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        assert "FLOW_METADATA" in code
        assert "single-actor" in code
        assert compiler.flow_name == "flow"
        assert len(compiler.routers) == 2
        assert compiler.single_actor_name == "handler_a"

    def test_compile_multi_actor_flow_generates_routers(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler_a(p)
                p = handler_b(p)
                return p
        """)
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        assert "def start_flow(" in code
        assert "def end_flow(" in code
        assert compiler.flow_name == "flow"
        assert len(compiler.routers) == 2

    def test_compile_with_conditionals(self):
        source = textwrap.dedent("""
            def my_flow(p: dict) -> dict:
                if p["x"]:
                    p = handler_a(p)
                else:
                    p = handler_b(p)
                return p
        """)
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        assert compiler.flow_name == "my_flow"
        assert len(compiler.routers) >= 2

    def test_compile_preserves_routers(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler_a(p)
                p = handler_b(p)
                return p
        """)
        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        assert compiler.routers is not None
        assert len(compiler.routers) > 0
        assert all(hasattr(r, "name") for r in compiler.routers)


class TestValidate:
    """Test FlowCompiler.validate() method."""

    def test_validate_correct_flow(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)
                return p
        """)
        compiler = FlowCompiler()
        compiler.validate(source, "test.py")

    def test_validate_raises_on_invalid_syntax(self):
        source = "def flow(p: dict) -> dict\n    return p"
        compiler = FlowCompiler()

        with pytest.raises(FlowCompileError, match="Syntax error"):
            compiler.validate(source, "test.py")

    def test_validate_raises_on_no_flow_function(self):
        source = textwrap.dedent("""
            def helper(x: int) -> int:
                return x
        """)
        compiler = FlowCompiler()

        with pytest.raises(FlowCompileError, match="No flow function found"):
            compiler.validate(source, "test.py")


class TestCompileFile:
    """Test FlowCompiler.compile_file() method."""

    def test_compile_file_success(self, tmp_path: Path):
        # Use two actors so a start router is generated
        source_file = tmp_path / "flow.py"
        source_file.write_text(textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler_a(p)
                p = handler_b(p)
                return p
        """))

        output_dir = tmp_path / "output"

        compiler = FlowCompiler()
        result_path = compiler.compile_file(str(source_file), str(output_dir))

        assert Path(result_path).exists()
        assert Path(result_path).name == "routers.py"
        assert "def start_flow(" in Path(result_path).read_text()

    def test_compile_file_nonexistent_source(self):
        compiler = FlowCompiler()

        with pytest.raises(FileNotFoundError, match="Source file not found"):
            compiler.compile_file("/nonexistent/file.py", "/tmp/output")

    def test_compile_file_output_not_directory(self, tmp_path: Path):
        source_file = tmp_path / "flow.py"
        source_file.write_text("def flow(p: dict) -> dict:\n    return p")

        output_file = tmp_path / "output.txt"
        output_file.write_text("existing file")

        compiler = FlowCompiler()

        with pytest.raises(ValueError, match="not a directory"):
            compiler.compile_file(str(source_file), str(output_file))

    def test_compile_file_output_directory_not_empty(self, tmp_path: Path):
        source_file = tmp_path / "flow.py"
        source_file.write_text("def flow(p: dict) -> dict:\n    return p")

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "existing.txt").write_text("something")

        compiler = FlowCompiler()

        with pytest.raises(ValueError, match="not empty"):
            compiler.compile_file(str(source_file), str(output_dir))

    def test_compile_file_creates_output_directory(self, tmp_path: Path):
        source_file = tmp_path / "flow.py"
        source_file.write_text(textwrap.dedent("""
            def flow(p: dict) -> dict:
                return p
        """))

        output_dir = tmp_path / "nested" / "output"

        compiler = FlowCompiler()
        result_path = compiler.compile_file(str(source_file), str(output_dir))

        assert output_dir.exists()
        assert output_dir.is_dir()
        assert Path(result_path).exists()


class TestGeneratePlot:
    """Test FlowCompiler.generate_plot() method."""

    def test_generate_plot_without_compile(self, tmp_path: Path):
        compiler = FlowCompiler()

        with pytest.raises(RuntimeError, match="Must compile flow before"):
            compiler.generate_plot(str(tmp_path))

    def test_generate_plot_creates_dot_file(self, tmp_path: Path):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = handler(p)
                return p
        """)
        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        try:
            dot_path, png_path = compiler.generate_plot(str(tmp_path))
        except RuntimeError as e:
            # Graphviz may not have PNG support in CI, but DOT file should still be written
            if "png" not in str(e).lower() and "format" not in str(e).lower():
                raise
            dot_path = str(tmp_path / "flow.dot")

        assert Path(dot_path).exists()
        assert Path(dot_path).name == "flow.dot"
        dot_content = Path(dot_path).read_text()
        assert "digraph flow {" in dot_content

    def test_generate_plot_dot_content_valid(self, tmp_path: Path):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["x"]:
                    p = handler_a(p)
                else:
                    p = handler_b(p)
                return p
        """)
        compiler = FlowCompiler()
        compiler.compile(source, "test.py")

        try:
            dot_path, _ = compiler.generate_plot(str(tmp_path))
        except RuntimeError as e:
            # Graphviz may not have PNG support in CI, but DOT file should still be written
            if "png" not in str(e).lower() and "format" not in str(e).lower():
                raise
            dot_path = str(tmp_path / "flow.dot")

        dot_content = Path(dot_path).read_text()

        assert "start_flow" in dot_content
        assert "end_flow" in dot_content
        assert "handler_a" in dot_content or "handler-a" in dot_content
        assert "handler_b" in dot_content or "handler-b" in dot_content


class TestVerboseMode:
    """Test verbose mode behavior."""

    def test_verbose_false_by_default(self):
        compiler = FlowCompiler()
        assert compiler.verbose is False

    def test_verbose_can_be_enabled(self):
        compiler = FlowCompiler(verbose=True)
        assert compiler.verbose is True


class TestWarnings:
    """Test warning collection."""

    def test_get_warnings_returns_list(self):
        compiler = FlowCompiler()
        warnings = compiler.get_warnings()
        assert isinstance(warnings, list)

    def test_warnings_empty_initially(self):
        compiler = FlowCompiler()
        assert compiler.get_warnings() == []
