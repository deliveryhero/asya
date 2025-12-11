"""
Scene DSL compiler.

Main orchestrator that coordinates parsing, generation, and emission.
"""

from pathlib import Path

from asya_cli.scene.diagram import generate_diagram
from asya_cli.scene.emitter import CodeEmitter
from asya_cli.scene.errors import SceneCompileError
from asya_cli.scene.generator import RouterGenerator
from asya_cli.scene.ir import ActorCall, Router, SceneIR
from asya_cli.scene.parser import SceneParser


class SceneCompiler:
    """
    Main Scene DSL compiler.

    Coordinates all compilation stages:
    1. Parse source code into IR
    2. Generate router code
    3. Emit final Python code
    """

    def __init__(self, verbose: bool = False):
        """
        Initialize compiler.

        Args:
            verbose: Show all errors and warnings
        """
        self.verbose = verbose
        self.warnings: list[str] = []
        self.scene_ir: SceneIR | None = None

    def compile_file(self, source_file: str, output_file: str | None = None) -> str:
        """
        Compile a flow file.

        Args:
            source_file: Path to source file
            output_file: Path to output file (default: <source>_compiled.py)

        Returns:
            Path to output file

        Raises:
            SceneCompileError: If compilation fails
            FileNotFoundError: If source file doesn't exist
        """
        source_path = Path(source_file)
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_file}")

        # Read source code
        source_code = source_path.read_text()

        # Compile to code
        generated_code = self.compile(source_code, str(source_path))

        # Determine output file
        if output_file is None:
            output_file = str(source_path.with_stem(source_path.stem + "_compiled"))

        # Write output
        output_path = Path(output_file)
        output_path.write_text(generated_code)

        return str(output_path)

    def compile(self, source_code: str, source_file: str) -> str:
        """
        Compile scene source code to generated Python code.

        Args:
            source_code: Scene source code
            source_file: Source file name (for error messages)

        Returns:
            Generated Python code

        Raises:
            SceneCompileError: If compilation fails
        """
        # Stage 1: Parse
        parser = SceneParser(source_file, source_code)
        scene_ir = parser.parse()

        if scene_ir is None or parser.errors:
            raise SceneCompileError(parser.errors, source_file, parser.source_lines)

        # Store scene IR for diagram generation
        self.scene_ir = scene_ir

        # Stage 2: Generate routers
        generator = RouterGenerator(scene_ir)
        routers = generator.generate()

        # Stage 3: Emit code
        emitter = CodeEmitter(scene_ir, routers, source_code)
        generated_code = emitter.emit()

        return generated_code

    def validate(self, source_code: str, source_file: str) -> bool:
        """
        Validate scene source code without generating output.

        Args:
            source_code: Scene source code
            source_file: Source file name (for error messages)

        Returns:
            True if valid, False otherwise

        Raises:
            SceneCompileError: If validation fails
        """
        # Just run parser
        parser = SceneParser(source_file, source_code)
        scene_ir = parser.parse()

        if scene_ir is None or parser.errors:
            raise SceneCompileError(parser.errors, source_file, parser.source_lines)

        return True

    def get_warnings(self) -> list[str]:
        """Get all warnings from last compilation."""
        return self.warnings

    def show_mappings(self, source_code: str, source_file: str) -> dict[str, str]:
        """
        Show actor → qualified name mappings for a scene.

        Args:
            source_code: Scene source code
            source_file: Source file name

        Returns:
            Dictionary of display_name → qualified_name

        Raises:
            SceneCompileError: If parsing fails
        """
        parser = SceneParser(source_file, source_code)
        scene_ir = parser.parse()

        if scene_ir is None or parser.errors:
            raise SceneCompileError(parser.errors, source_file, parser.source_lines)

        def collect_actors(steps: list[ActorCall | Router]) -> dict[str, str]:
            mappings = {}
            for step in steps:
                if isinstance(step, ActorCall):
                    mappings[step.display_name] = step.qualified_name
                elif isinstance(step, Router):
                    for op in step.operations:
                        if isinstance(op, ActorCall):
                            mappings[op.display_name] = op.qualified_name
            return mappings

        return collect_actors(scene_ir.steps)

    def generate_diagram(self, output_dot: str | None = None, output_png: str | None = None) -> tuple[str, str | None]:
        """
        Generate scene diagram after compilation.

        Must be called after compile() or compile_file().

        Args:
            output_dot: Optional path to save DOT file
            output_png: Optional path to save PNG file (requires graphviz)

        Returns:
            Tuple of (dot_content, png_path)
            png_path is None if PNG generation was skipped or failed

        Raises:
            RuntimeError: If called before compilation
            FileNotFoundError: If graphviz not found (only when output_png specified)
        """
        if self.scene_ir is None:
            raise RuntimeError("Must compile scene before generating diagram")

        return generate_diagram(self.scene_ir, output_dot, output_png)
