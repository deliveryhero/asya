"""Flow DSL compiler for Asya framework."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from asya_lab.flow.compiler import FlowCompiler
from asya_lab.flow.errors import FlowCompileError
from asya_lab.flow.result_types import ActorInfo, FlowInfo


_F = TypeVar("_F", bound=Callable)


def flow(func: _F) -> _F:
    """Mark a function as the flow entry point for the Asya flow compiler.

    This decorator is a no-op at runtime -- it returns the function unchanged.
    The flow compiler uses it as an AST marker to identify the entry-point
    function when compiling a flow file.
    """
    return func


def compile(  # noqa: A001
    source: str,
    *,
    output_dir: str | None = None,
    flow_name: str | None = None,
    plot: bool = True,
    verbose: bool = False,
) -> FlowInfo:
    """Compile a flow source file into routers + manifests + graph.

    Args:
        source: Path to the flow .py file.
        output_dir: Override output directory. Defaults to config-resolved path.
        flow_name: Override inferred flow name.
        plot: Generate SVG rendering (requires graphviz).
        verbose: Print progress messages.

    Returns:
        FlowInfo with all compilation artifacts.
    """
    source_path = Path(source).resolve()

    project = None
    rule_engine = None
    try:
        from asya_lab.config.project import AsyaProject

        project = AsyaProject.from_dir(source_path.parent)
        rule_engine = project.load_rules()
    except FileNotFoundError:
        pass

    compiler = FlowCompiler(
        verbose=verbose,
        rule_engine=rule_engine,
        project=project,
    )

    if output_dir is None:
        if project:
            try:
                flow_function = _infer_flow_function(source_path)
                output_dir = str(project.resolve_path("compiler.routers") / (flow_function or source_path.stem))
            except Exception:
                output_dir = str(source_path.parent / "compiled" / source_path.stem)
        else:
            output_dir = str(source_path.parent / "compiled" / source_path.stem)

    return compiler.compile_file(str(source_path), output_dir, overwrite=True)


def _infer_flow_function(source_path: Path) -> str | None:
    """Quick scan for @flow decorator to get function name before full compile."""
    import ast

    try:
        tree = ast.parse(source_path.read_text())
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Name) and dec.id == "flow":
                    return node.name
    return None


__all__ = ["ActorInfo", "FlowCompileError", "FlowCompiler", "FlowInfo", "compile", "flow"]
