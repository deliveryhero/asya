"""
Flow DSL compiler.

Main orchestrator that coordinates parsing, analysis, generation, and emission.
"""

from pathlib import Path

from asya_cli.scene.analyzer import ControlFlowAnalyzer
from asya_cli.scene.diagram import generate_diagram
from asya_cli.scene.emitter import CodeEmitter
from asya_cli.scene.errors import SceneCompileError
from asya_cli.scene.generator import RouterGenerator
from asya_cli.scene.ir import SceneIR
from asya_cli.scene.parser import SceneParser


class SceneCompiler:
    """
    Main Flow DSL compiler.

    Coordinates all compilation stages:
    1. Parse source code into IR
    2. Analyze control flow and assign router IDs
    3. Generate router code
    4. Emit final Python code
    """

    def __init__(self, check_infinite_loops: bool = True, verbose: bool = False):
        """
        Initialize compiler.

        Args:
            check_infinite_loops: Enable infinite loop detection
            verbose: Show all errors and warnings
        """
        self.check_infinite_loops = check_infinite_loops
        self.verbose = verbose
        self.warnings: list[str] = []
        self.flow_ir: SceneIR | None = None

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

    def compile(self, source_code: str, source_file: str = "<string>") -> str:
        """
        Compile flow source code to generated Python code.

        Args:
            source_code: Flow source code
            source_file: Source file name (for error messages)

        Returns:
            Generated Python code

        Raises:
            SceneCompileError: If compilation fails
        """
        # Stage 1: Parse
        parser = SceneParser(source_file, source_code)
        flow_ir = parser.parse()

        if flow_ir is None or parser.errors:
            raise SceneCompileError(parser.errors, source_file, parser.source_lines)

        # Stage 2: Analyze
        analyzer = ControlFlowAnalyzer(flow_ir.name, flow_ir.param_name, self.check_infinite_loops)
        flow_ir = analyzer.analyze(flow_ir)

        # Store flow IR for diagram generation
        self.flow_ir = flow_ir

        # Collect warnings
        if analyzer.warnings:
            self.warnings.extend(analyzer.warnings)

        # Stage 3: Generate routers
        generator = RouterGenerator(flow_ir)
        routers = generator.generate()

        # Stage 4: Emit code
        emitter = CodeEmitter(flow_ir, routers, source_code)
        generated_code = emitter.emit()

        return generated_code

    def validate(self, source_code: str, source_file: str = "<string>") -> bool:
        """
        Validate flow source code without generating output.

        Args:
            source_code: Flow source code
            source_file: Source file name (for error messages)

        Returns:
            True if valid, False otherwise

        Raises:
            SceneCompileError: If validation fails
        """
        # Just run parser
        parser = SceneParser(source_file, source_code)
        flow_ir = parser.parse()

        if flow_ir is None or parser.errors:
            raise SceneCompileError(parser.errors, source_file, parser.source_lines)

        # Run analyzer to check for warnings
        analyzer = ControlFlowAnalyzer(flow_ir.name, flow_ir.param_name, self.check_infinite_loops)
        analyzer.analyze(flow_ir)

        if analyzer.warnings:
            self.warnings.extend(analyzer.warnings)

        return True

    def get_warnings(self) -> list[str]:
        """Get all warnings from last compilation."""
        return self.warnings

    def show_mappings(self, source_code: str, source_file: str = "<string>") -> dict[str, str]:
        """
        Show handler → actor name mappings for a flow.

        Args:
            source_code: Flow source code
            source_file: Source file name

        Returns:
            Dictionary of handler_name → qualified_name

        Raises:
            SceneCompileError: If parsing fails
        """
        parser = SceneParser(source_file, source_code)
        flow_ir = parser.parse()

        if flow_ir is None or parser.errors:
            raise SceneCompileError(parser.errors, source_file, parser.source_lines)

        # Extract all handler calls
        from asya_cli.scene.ir import HandlerCall, IfBlock, Operation, WhileLoop

        def collect_handlers(ops: list[Operation]) -> dict[str, str]:
            mappings = {}
            for op in ops:
                if isinstance(op, HandlerCall):
                    mappings[op.func_name] = op.qualified_name
                elif isinstance(op, IfBlock):
                    mappings.update(collect_handlers(op.then_ops))
                    for _, _, elif_ops in op.elif_blocks:
                        mappings.update(collect_handlers(elif_ops))
                    mappings.update(collect_handlers(op.else_ops))
                elif isinstance(op, WhileLoop):
                    mappings.update(collect_handlers(op.body_ops))
            return mappings

        return collect_handlers(flow_ir.operations)

    def generate_diagram(self, output_dot: str | None = None, output_png: str | None = None) -> tuple[str, str | None]:
        """
        Generate flow diagram after compilation.

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
        if self.flow_ir is None:
            raise RuntimeError("Must compile flow before generating diagram")

        return generate_diagram(self.flow_ir, output_dot, output_png)
