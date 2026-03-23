"""Compiler rules for classifying symbols encountered in the flow DSL.

Rules are loaded from YAML config rather than hardcoded.  Defaults ship in
``asya_lab/defaults/compiler.rules.yaml``; user rules in
``.asya/config.compiler.rules.yaml`` extend the defaults.

The parser auto-detects scope from Python syntax (context manager vs
decorator vs call-site) — rules do not need a ``scope`` field.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from asya_lab.compiler.rules import WhereNode, _load_default_rules


@dataclass
class CompilerRule:
    """Classification rule for a single symbol (context manager, decorator, etc.)."""

    treat_as: str  # "config" | "inline"
    where: list[WhereNode] | None = None  # extraction tree
    imports: list[str] = field(default_factory=list)  # import statements for generated code


def _rule_from_dict(d: dict) -> CompilerRule:
    """Convert a YAML rule dict to a CompilerRule."""
    where = None
    if "where" in d:
        where = [WhereNode.from_dict(w) for w in d["where"]]
    return CompilerRule(
        treat_as=d.get("treat-as", "config"),
        where=where,
        imports=d.get("imports", []),
    )


class CompilerRules:
    """Registry of compiler rules indexed by fully-qualified symbol name.

    Rules are loaded from YAML config files.  To start with no rules at all
    use ``CompilerRules.empty()``.
    """

    def __init__(self, rules: dict[str, CompilerRule] | None = None) -> None:
        self._rules: dict[str, CompilerRule] = {}
        for d in _load_default_rules():
            self._rules[d["match"]] = _rule_from_dict(d)
        if rules is not None:
            self._rules.update(rules)

    @classmethod
    def empty(cls) -> CompilerRules:
        """Return a CompilerRules with no rules at all."""
        instance = cls.__new__(cls)
        instance._rules = {}
        return instance

    @classmethod
    def from_config(cls, rules_cfg: list[dict] | None) -> CompilerRules:
        """Create CompilerRules from a config rule list.

        All rules are loaded (no scope filtering). User rules override
        defaults for the same match key.
        """
        user_rules: dict[str, CompilerRule] | None = None
        if rules_cfg:
            user_rules = {d["match"]: _rule_from_dict(d) for d in rules_cfg}
        return cls(user_rules)

    def lookup(self, symbol: str) -> CompilerRule | None:
        """Return the rule for *symbol*, or None if not found."""
        return self._rules.get(symbol)
