"""Compiler rules for classifying symbols encountered in the flow DSL."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar


@dataclass
class CompilerRule:
    """Classification rule for a single symbol (context manager, decorator, etc.)."""

    treat_as: str  # "config" | "inline"
    extract: dict[str, str] = field(default_factory=dict)  # param_name -> env_var
    imports: list[str] = field(default_factory=list)  # import statements for generated code


class CompilerRules:
    """Registry of compiler rules indexed by fully-qualified symbol name.

    Built-in defaults cover the most common integrations.  Custom rules
    passed to ``__init__`` are merged on top of the defaults, so
    user-provided rules extend rather than replace the built-ins.

    To start with no built-in rules at all use ``CompilerRules.empty()``.
    """

    _DEFAULT_RULES: ClassVar[dict[str, CompilerRule]] = {
        "asyncio.timeout": CompilerRule(
            treat_as="config",
            extract={"delay": "ASYA_RESILIENCY_ACTOR_TIMEOUT"},
        ),
        # contextlib.suppress suppresses exceptions inline in the router function.
        # The import is emitted in generated code automatically.
        "contextlib.suppress": CompilerRule(
            treat_as="inline",
            imports=["import contextlib"],
        ),
    }

    def __init__(self, rules: dict[str, CompilerRule] | None = None) -> None:
        self._rules: dict[str, CompilerRule] = dict(self._DEFAULT_RULES)
        if rules is not None:
            self._rules.update(rules)

    @classmethod
    def empty(cls) -> CompilerRules:
        """Return a CompilerRules with no rules at all (not even the built-in defaults)."""
        instance = cls.__new__(cls)
        instance._rules = {}
        return instance

    def lookup(self, symbol: str) -> CompilerRule | None:
        """Return the rule for *symbol*, or None if not found."""
        return self._rules.get(symbol)
