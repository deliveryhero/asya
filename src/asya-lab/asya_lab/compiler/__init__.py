"""Compiler output: manifest templating and kustomize structure."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from asya_lab.compiler.templater import ManifestTemplater

__all__ = ["ManifestTemplater"]


def __getattr__(name: str) -> type:
    if name == "ManifestTemplater":
        from asya_lab.compiler.templater import ManifestTemplater

        return ManifestTemplater
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
