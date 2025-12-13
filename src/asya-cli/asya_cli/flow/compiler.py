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

    def compile_file(self, source_file: str, output_dir: str) -> str:
        source_path = Path(source_file)
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_file}")

        output_path = Path(output_dir)
        if output_path.exists():
            if not output_path.is_dir():
                raise ValueError(f"Output path exists and is not a directory: {output_dir}")
            if any(output_path.iterdir()):
                raise ValueError(f"Output directory is not empty: {output_dir}")

        output_path.mkdir(parents=True, exist_ok=True)

        source_code = source_path.read_text()
        compiled_code = self.compile(source_code, str(source_path))

        compiled_file = output_path / "compiled_routers.py"
        compiled_file.write_text(compiled_code)

        return str(compiled_file)

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

    def generate_plot(self, output_dir: str) -> tuple[str, str | None]:
        if not self.flow_name or not self.routers:
            raise RuntimeError("Must compile flow before generating plot")

        generator = DotGenerator(self.flow_name, self.routers)
        dot_content = generator.generate()

        output_path = Path(output_dir)
        dot_file = output_path / "plot.dot"
        dot_file.write_text(dot_content)

        png_path = None
        try:
            import subprocess  # nosec B404

            subprocess.run(["dot", "-V"], capture_output=True, check=True)  # nosec B603, B607

            png_file = output_path / "plot.png"

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
        parser = FlowParser(source_code, filename)
        return parser.parse()

    def _group(self, flow_name: str, operations):
        grouper = OperationGrouper(flow_name, operations)
        return grouper.group()

    def _generate(self, flow_name: str, units, filename: str):
        generator = CodeGenerator(flow_name, units, filename)
        return generator.generate()
