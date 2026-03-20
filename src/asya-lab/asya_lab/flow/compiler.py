"""Flow compiler public API.

Pipeline: Parse -> CodeGen -> Analyze -> GraphGen
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from asya_lab.flow.analyzer import GraphData, analyze
from asya_lab.flow.codegen import CodeGenerator
from asya_lab.flow.graphgen import to_dot, to_json_string, to_mermaid
from asya_lab.flow.parser import FlowParser, ParseResult


if TYPE_CHECKING:
    from asya_lab.compiler.rules import RuleEngine


def _calculate_module_path(filename: str) -> str:
    """Calculate Python module path from filename.

    Converts /path/to/my_project/handlers/processor.py to my_project.handlers.processor
    Uses PYTHONPATH or current working directory as the base.
    """
    filepath = Path(filename).resolve()

    python_paths = [Path(p).resolve() for p in os.environ.get("PYTHONPATH", "").split(":") if p]

    for python_path in python_paths:
        try:
            rel_path = filepath.relative_to(python_path)
            parts = [*list(rel_path.parts[:-1]), rel_path.stem]
            return ".".join(parts)
        except ValueError:
            continue

    return filepath.stem


class FlowCompiler:
    def __init__(
        self,
        verbose: bool = False,
        max_iterations: int = 100,
        rule_engine: RuleEngine | None = None,
    ):
        self.verbose = verbose
        self.max_iterations = max_iterations
        self._rule_engine: RuleEngine | None = rule_engine
        self.warnings: list[str] = []
        self.flow_name: str | None = None
        self.class_methods: set[str] = set()
        self.is_async: bool = False
        self.import_map: dict[str, str] = {}
        self.module_constants: list[str] = []
        self._parse_result: ParseResult | None = None
        self._generated_code: str | None = None
        self._graph_data: GraphData | None = None

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
        # Step 1: Parse
        result = self._parse(source_code, filename)
        self._parse_result = result

        # Step 2: CodeGen
        codegen = CodeGenerator(result, filename, output_file)
        code = codegen.generate()
        self._generated_code = code

        # Step 3: Analyze (graph extraction from generated code)
        self._graph_data = analyze(code)
        self.warnings.extend(self._graph_data.warnings)

        self.flow_name = result.flow_name

        return code

    def validate(self, source_code: str, filename: str) -> None:
        self._parse(source_code, filename)

    def generate_plot(
        self,
        output_dir: str,
        plot_format: str = "svg",
    ) -> tuple[str, str | None]:
        if not self.flow_name or self._graph_data is None:
            raise RuntimeError("Must compile flow before generating plot")

        dot_content = to_dot(self._graph_data, self.flow_name)
        mmd_content = to_mermaid(self._graph_data, self.flow_name)
        json_content = to_json_string(self._graph_data, self.flow_name)

        output_path = Path(output_dir)
        dot_file = output_path / "flow.dot"
        dot_file.write_text(dot_content)

        mmd_file = output_path / "flow.mmd"
        mmd_file.write_text(mmd_content)

        json_file = output_path / "graph.json"
        json_file.write_text(json_content)

        output_path_str = None
        try:
            import subprocess  # nosec B404

            subprocess.run(["dot", "-V"], capture_output=True, check=True)  # nosec B603, B607

            output_file = output_path / f"flow.{plot_format}"

            result = subprocess.run(  # nosec B603, B607
                ["dot", f"-T{plot_format}", str(dot_file), "-o", str(output_file)],
                capture_output=True,
                text=True,
                check=True,
            )

            if result.returncode == 0:
                # Strip graphviz version comment to avoid SVG oscillation across versions
                import re

                svg_content = output_file.read_text()
                svg_content = re.sub(
                    r"<!-- Generated by graphviz version .+?\n -->",
                    "<!-- Generated by graphviz\n -->",
                    svg_content,
                )
                output_file.write_text(svg_content)
                output_path_str = str(output_file)
            else:
                raise RuntimeError(f"graphviz dot failed: {result.stderr}")

        except FileNotFoundError as e:
            raise ImportError(
                "graphviz 'dot' command not found. Install graphviz to generate plots. "
                "On Ubuntu/Debian: apt-get install graphviz"
            ) from e
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"graphviz dot failed: {e.stderr}") from e

        return str(dot_file), output_path_str

    @property
    def single_actor_name(self) -> str | None:
        """Returns the actor name if this is a single-actor flow, else None."""
        if self._parse_result is None:
            return None
        from asya_lab.flow.parser import ActorCall, Return

        ops = self._parse_result.operations
        actor_calls = [op for op in ops if isinstance(op, ActorCall)]
        non_actor = [op for op in ops if not isinstance(op, ActorCall | Return)]
        if len(actor_calls) == 1 and len(non_actor) == 0:
            return actor_calls[0].name
        return None

    def get_warnings(self) -> list[str]:
        return self.warnings

    def _parse(self, source_code: str, filename: str) -> ParseResult:
        module_path = _calculate_module_path(filename)
        parser = FlowParser(source_code, filename, module_path, rule_engine=self._rule_engine)
        result = parser.parse()
        self.class_methods = result.class_methods
        self.is_async = result.is_async
        self.import_map = result.import_map
        self.module_constants = result.constants
        return result
