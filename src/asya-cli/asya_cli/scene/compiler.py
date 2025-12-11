"""Scene compiler public API."""

from pathlib import Path
from typing import Dict, List, Tuple

from asya_cli.scene.codegen import CodeGenerator
from asya_cli.scene.errors import SceneCompileError
from asya_cli.scene.grouper import OperationGrouper
from asya_cli.scene.parser import SceneParser


class SceneCompiler:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.warnings: List[str] = []

    def compile_file(self, source_file: str, output_file: str = None) -> str:
        source_path = Path(source_file)
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_file}")

        if output_file is None:
            raise ValueError(f"Missing required parameter: output_file")

        source_code = source_path.read_text()
        compiled_code = self.compile(source_code, str(source_path))

        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(compiled_code)

        return str(output_path)

    def compile(self, source_code: str, filename: str) -> str:
        scene_name, operations = self._parse(source_code, filename)
        units = self._group(scene_name, operations)
        code = self._generate(scene_name, units, filename)
        return code

    def validate(self, source_code: str, filename: str) -> None:
        self._parse(source_code, filename)

    def show_mappings(self, source_code: str, filename: str) -> Dict[str, str]:
        scene_name, operations = self._parse(source_code, filename)
        units = self._group(scene_name, operations)

        mappings = {}
        for unit in units:
            mappings[unit.name] = unit.name

        return mappings

    def generate_diagram(self, output_dot: str = None, output_png: str = None) -> Tuple[str, str]:
        raise NotImplementedError("Diagram generation not yet implemented")

    def get_warnings(self) -> List[str]:
        return self.warnings

    def _parse(self, source_code: str, filename: str):
        parser = SceneParser(source_code, filename)
        return parser.parse()

    def _group(self, scene_name: str, operations):
        grouper = OperationGrouper(scene_name, operations)
        return grouper.group()

    def _generate(self, scene_name: str, units, filename: str):
        generator = CodeGenerator(scene_name, units, filename)
        return generator.generate()
