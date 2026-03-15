"""Click parameter type for target references.

Centralizes target argument parsing across all CLI commands.
Every command that accepts a flow or actor target uses the same type.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import click


_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_DOTTED_NAME_RE = re.compile(r"^[a-z_][a-z0-9_.]*$")  # module.path.function


def _to_kebab(name: str) -> str:
    return name.replace("_", "-").replace(".", "-")


def _to_snake(name: str) -> str:
    return name.replace("-", "_")


@dataclass(frozen=True)
class AsyaRef:
    """Parsed target reference used by all CLI commands.

    name:     K8s/manifest name in kebab-case (e.g. "order-processing")
    function: Python identifier in snake_case (e.g. "order_processing")
    source:   Path to .py source file, or None if resolved by name
    """

    name: str
    function: str
    source: Path | None = None


class AsyaRefType(click.ParamType):
    """Click type that parses target references.

    Accepted formats:
      order-processing              kebab-case name
      order_processing              snake_case name (converted)
      path/to/flow.py               source file (name from stem)
      path/to/flow.py:my_flow       source file with explicit function
    """

    name = "TARGET"

    def convert(self, value: str, param: click.Parameter | None, ctx: click.Context | None) -> AsyaRef:
        if isinstance(value, AsyaRef):
            return value

        # path/to/file.py:function_name
        if ":" in value:
            file_part, func = value.rsplit(":", 1)
            source = Path(file_part)
            if source.suffix != ".py":
                self.fail(f"expected .py file before ':', got '{file_part}'", param, ctx)
            if not _DOTTED_NAME_RE.match(func):
                self.fail(f"function name must be valid Python identifier, got '{func}'", param, ctx)
            return AsyaRef(name=_to_kebab(func), function=func, source=source)

        # path/to/file.py
        if value.endswith(".py"):
            source = Path(value)
            function = source.stem
            return AsyaRef(name=_to_kebab(function), function=function, source=source)

        # kebab-case or snake_case name
        if not _NAME_RE.match(value):
            self.fail(
                f"invalid target '{value}': expected kebab-case name, snake_case name, or a .py file path",
                param,
                ctx,
            )
        return AsyaRef(name=_to_kebab(value), function=_to_snake(value), source=None)


ASYA_REF = AsyaRefType()
