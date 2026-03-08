"""Compiler rules for classifying symbols encountered in the flow DSL."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CompilerRule:
    """Classification rule for a single symbol (context manager, decorator, etc.)."""

    treat_as: str  # "config" | "inline"
    extract: dict[str, str] = field(default_factory=dict)  # param_name -> env_var


class CompilerRules:
    """Registry of compiler rules indexed by fully-qualified symbol name.

    Built-in defaults cover the most common third-party integrations.
    Pass a custom dict to ``__init__`` to override or extend the defaults.
    """

    _DEFAULT_RULES: dict[str, CompilerRule] = {
        "asyncio.timeout": CompilerRule(
            treat_as="config",
            extract={"delay": "ASYA_RESILIENCY_ACTOR_TIMEOUT"},
        ),
        # contextlib.suppress is a lightweight inline wrapper — no config to extract.
        # It suppresses the listed exceptions inline in the router function, which is
        # useful for optional steps where errors should be silently swallowed.
        "contextlib.suppress": CompilerRule(treat_as="inline"),
    }

    def __init__(self, rules: dict[str, CompilerRule] | None = None) -> None:
        if rules is None:
            self._rules: dict[str, CompilerRule] = dict(self._DEFAULT_RULES)
        else:
            self._rules = dict(rules)

    def lookup(self, symbol: str) -> CompilerRule | None:
        """Return the rule for *symbol*, or None if not found."""
        return self._rules.get(symbol)
