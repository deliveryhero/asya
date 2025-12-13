"""Flow compiler public API."""

from pathlib import Path

from asya_cli.flow.codegen import CodeGenerator
from asya_cli.flow.dotgen import DotGenerator
from asya_cli.flow.grouper import OperationGrouper, Router
from asya_cli.flow.parser import FlowParser


class FlowCompiler:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.warnings: list[str] = []
        self.flow_name: str | None = None
        self.routers: list[Router] = []

    def compile_file(self, source_file: str, output_file: str = None) -> str:
        source_path = Path(source_file)
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_file}")

        if output_file is None:
            raise ValueError("Missing required parameter: output_file")

        source_code = source_path.read_text()
        compiled_code = self.compile(source_code, str(source_path))

        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(compiled_code)

        return str(output_path)

    def compile(self, source_code: str, filename: str) -> str:
        flow_name, operations = self._parse(source_code, filename)
        units = self._group(flow_name, operations)
        code = self._generate(flow_name, units, filename)

        self.flow_name = flow_name
        self.routers = units

        return code

    def validate(self, source_code: str, filename: str) -> None:
        self._parse(source_code, filename)

    def show_mappings(self, source_code: str, filename: str) -> dict[str, str]:
        flow_name, operations = self._parse(source_code, filename)
        units = self._group(flow_name, operations)

        mappings = {}
        for unit in units:
            mappings[unit.name] = unit.name

        return mappings

    def generate_diagram(self, output_dot: str = None, output_png: str = None) -> tuple[str, str | None]:
        if not self.flow_name or not self.routers:
            raise RuntimeError("Must compile flow before generating diagram")

        generator = DotGenerator(self.flow_name, self.routers)
        dot_content = generator.generate()

        if output_dot:
            dot_path = Path(output_dot)
            dot_path.parent.mkdir(parents=True, exist_ok=True)
            dot_path.write_text(dot_content)

        png_path = None
        if output_png:
            try:
                import subprocess

                subprocess.run(["dot", "-V"], capture_output=True, check=True)

                png_file = Path(output_png)
                png_file.parent.mkdir(parents=True, exist_ok=True)

                result = subprocess.run(
                    ["dot", "-Tpng", output_dot, "-o", str(png_file)],
                    capture_output=True,
                    text=True,
                    check=True,
                )

                if result.returncode == 0:
                    png_path = str(png_file)
                else:
                    raise RuntimeError(f"graphviz dot failed: {result.stderr}")

            except FileNotFoundError:
                raise ImportError(
                    "graphviz 'dot' command not found. Install graphviz to generate PNG diagrams. "
                    "On Ubuntu/Debian: apt-get install graphviz"
                )
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"graphviz dot failed: {e.stderr}")

        return dot_content, png_path

    def get_warnings(self) -> list[str]:
        return self.warnings

    def _parse(self, source_code: str, filename: str):
        parser = FlowParser(source_code, filename)
        return parser.parse()

    def _group(self, flow_name: str, operations):
        grouper = OperationGrouper(flow_name, operations)
        return grouper.group()

    def _generate(self, flow_name: str, units, filename: str):
        generator = CodeGenerator(flow_name, units, filename)
        return generator.generate()
