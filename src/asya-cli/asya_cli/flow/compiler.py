"""Flow compiler public API."""

from __future__ import annotations

import os
from pathlib import Path

from asya_cli.flow.codegen import CodeGenerator
from asya_cli.flow.dotgen import DotGenerator
from asya_cli.flow.grouper import DEFAULT_MAX_LOOP_ITERATIONS, OperationGrouper, Router
from asya_cli.flow.parser import FlowParser


def _calculate_module_path(filename: str) -> str:
    """
    Calculate Python module path from filename.

    Converts /path/to/my_project/handlers/processor.py to my_project.handlers.processor
    Uses PYTHONPATH or current working directory as the base.
    """
    filepath = Path(filename).resolve()

    # Try to find the module root by looking for common markers
    python_paths = [Path(p).resolve() for p in os.environ.get("PYTHONPATH", "").split(":") if p]

    # Check if file is under any PYTHONPATH
    for python_path in python_paths:
        try:
            rel_path = filepath.relative_to(python_path)
            # Convert path to module notation
            parts = [*list(rel_path.parts[:-1]), rel_path.stem]
            return ".".join(parts)
        except ValueError:
            continue

    # Fallback: use filename without extension as module name
    return filepath.stem


class FlowCompiler:
    def __init__(self, verbose: bool = False, max_iterations: int = DEFAULT_MAX_LOOP_ITERATIONS):
        self.verbose = verbose
        self.max_iterations = max_iterations
        self.warnings: list[str] = []
        self.flow_name: str | None = None
        self.routers: list[Router] = []
        self.class_methods: set[str] = set()
        self.is_async: bool = False

    def compile_file(self, source_file: str, output_dir: str, overwrite: bool = False) -> str:
        source_path = Path(source_file)
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_file}")

        output_path = Path(output_dir)
        if output_path.exists():
            if not output_path.is_dir():
                raise ValueError(f"Output path exists and is not a directory: {output_dir}")
            if not overwrite and any(output_path.iterdir()):
                raise ValueError(f"Output directory is not empty: {output_dir}")

        output_path.mkdir(parents=True, exist_ok=True)

        source_code = source_path.read_text()
        compiled_file = output_path / "routers.py"
        compiled_code = self.compile(source_code, str(source_path), str(compiled_file))

        compiled_file.write_text(compiled_code)

        return str(compiled_file)

    def compile(self, source_code: str, filename: str, output_file: str | None = None) -> str:
        flow_name, operations = self._parse(source_code, filename)
        units = self._group(flow_name, operations)
        code = self._generate(flow_name, units, filename, output_file)

        self.flow_name = flow_name
        self.routers = units

        return code

    def validate(self, source_code: str, filename: str) -> None:
        self._parse(source_code, filename)

    def generate_plot(self, output_dir: str, plot_width: int = 50) -> tuple[str, str | None]:
        if not self.flow_name or not self.routers:
            raise RuntimeError("Must compile flow before generating plot")

        generator = DotGenerator(
            self.flow_name,
            self.routers,
            step_width=plot_width,
            class_methods=self.class_methods,
            is_async=self.is_async,
        )
        dot_content = generator.generate()

        output_path = Path(output_dir)
        dot_file = output_path / "flow.dot"
        dot_file.write_text(dot_content)

        png_path = None
        try:
            import subprocess  # nosec B404

            subprocess.run(["dot", "-V"], capture_output=True, check=True)  # nosec B603, B607

            png_file = output_path / "flow.png"

            result = subprocess.run(  # nosec B603, B607
                ["dot", "-Tpng", str(dot_file), "-o", str(png_file)],
                capture_output=True,
                text=True,
                check=True,
            )

            if result.returncode == 0:
                png_path = str(png_file)
            else:
                raise RuntimeError(f"graphviz dot failed: {result.stderr}")

        except FileNotFoundError as e:
            raise ImportError(
                "graphviz 'dot' command not found. Install graphviz to generate PNG plots. "
                "On Ubuntu/Debian: apt-get install graphviz"
            ) from e
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"graphviz dot failed: {e.stderr}") from e

        return str(dot_file), png_path

    def get_warnings(self) -> list[str]:
        return self.warnings

    def _parse(self, source_code: str, filename: str):
        module_path = _calculate_module_path(filename)
        parser = FlowParser(source_code, filename, module_path)
        flow_name, operations = parser.parse()
        # Store metadata for later use by DotGenerator
        self.class_methods = parser.get_class_methods()
        self.is_async = parser.is_async
        return flow_name, operations

    def _group(self, flow_name: str, operations):
        grouper = OperationGrouper(flow_name, operations, max_iterations=self.max_iterations)
        return grouper.group()

    def _generate(self, flow_name: str, units, filename: str, output_file: str | None = None):
        generator = CodeGenerator(flow_name, units, filename, output_file)
        return generator.generate()
