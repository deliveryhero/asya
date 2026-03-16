"""Flow DSL compiler for Asya framework."""

from collections.abc import Callable
from typing import TypeVar

from asya_lab.flow.compiler import FlowCompiler
from asya_lab.flow.errors import FlowCompileError


_F = TypeVar("_F", bound=Callable)


def flow(func: _F) -> _F:
    """Mark a function as the flow entry point for the Asya flow compiler.

    This decorator is a no-op at runtime — it returns the function unchanged.
    The flow compiler uses it as an AST marker to identify the entry-point
    function when compiling a flow file.

    Usage::

        @flow
        def my_pipeline(p: dict) -> dict:
            p = step_one(p)
            p = step_two(p)
            return p
    """
    return func


__all__ = ["FlowCompileError", "FlowCompiler", "flow"]
