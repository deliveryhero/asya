"""
Code emitter for Flow DSL compiler.

Combines all generated code into final Python file.
"""

import ast

from asya_cli.flow.ir import FlowIR, IfBlock, WhileLoop
from asya_cli.flow.templates import get_file_header, get_initial_route, get_resolve_function


class CodeEmitter:
    """Emit final Python code from Flow IR and generated routers."""

    def __init__(self, flow_ir: FlowIR, routers: list[tuple[str, str, str]], source_code: str):
        """
        Initialize code emitter.

        Args:
            flow_ir: Flow intermediate representation
            routers: List of (router_id, docstring, code) tuples
            source_code: Original source code
        """
        self.flow_ir = flow_ir
        self.routers = routers
        self.source_code = source_code

    def emit(self) -> str:
        """
        Generate complete Python file.

        Returns:
            Python source code as string
        """
        sections = []

        # File header
        sections.append(get_file_header(self.flow_ir.source_file))
        sections.append("")

        # resolve() function
        sections.append("# " + "=" * 70)
        sections.append("# Handler Resolution")
        sections.append("# " + "=" * 70)
        sections.append("")
        sections.append(get_resolve_function())
        sections.append("")

        # Initial route constant
        first_router = self._find_first_router()
        if first_router:
            sections.append("")
            sections.append("# " + "=" * 70)
            sections.append("# Initial Route")
            sections.append("# " + "=" * 70)
            sections.append("")
            sections.append(get_initial_route(self.flow_ir.name, first_router))
            sections.append("")

        # Original flow function (for PoC mode)
        sections.append("")
        sections.append("# " + "=" * 70)
        sections.append("# Original Flow Function (for PoC execution)")
        sections.append("# " + "=" * 70)
        sections.append("")
        sections.append(self._extract_original_flow())
        sections.append("")

        # Generated routers (for production deployment)
        if self.routers:
            sections.append("")
            sections.append("# " + "=" * 70)
            sections.append("# Generated Routers (for production deployment)")
            sections.append("# " + "=" * 70)
            sections.append("")

            for _router_id, _docstring, code in self.routers:
                sections.append(code)
                sections.append("")

        return "\n".join(sections)

    def _find_first_router(self) -> str | None:
        """
        Find the first router in the flow.

        Returns:
            Router ID of first control flow statement, or None if no routers
        """
        for op in self.flow_ir.operations:
            if isinstance(op, IfBlock | WhileLoop) and op.router_id:
                return op.router_id
        return None

    def _extract_original_flow(self) -> str:
        """
        Extract original flow function from source code.

        Returns:
            Source code of the flow function and its imports
        """
        parts = []

        # Add imports
        if self.flow_ir.imports:
            import_lines = []
            for imp in self.flow_ir.imports:
                import_lines.append(ast.unparse(imp))
            parts.append("\n".join(import_lines))
            parts.append("")

        # Add flow function
        # Parse source to get just the function
        tree = ast.parse(self.source_code)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == self.flow_ir.name:
                # Check if function has docstring and add one if missing
                has_docstring = (
                    node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)
                )

                if not has_docstring:
                    # Add docstring by modifying the AST
                    docstring_node = ast.Expr(value=ast.Constant(value="Original flow function for PoC mode execution"))
                    node.body.insert(0, docstring_node)

                func_code = ast.unparse(node)
                parts.append(func_code)
                break

        return "\n".join(parts)
