"""Compiler rules: exact-match classification for Python decorators and calls.

Each rule maps a Python symbol (e.g. ``tenacity.retry``) to compiler
behaviour (treat-as actor, inline, config, ...) and optionally extracts
parameter values via a ``where:`` tree.

Matching is exact: the rule's ``match`` field must equal the fully-qualified
symbol name.  No wildcards or pattern matching.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TreatAs(Enum):
    ACTOR = "actor"
    INLINE = "inline"
    UNFOLD = "unfold"
    FLOW = "flow"
    CONFIG = "config"


@dataclass
class ParamSpec:
    """Rich parameter binding: positional index, keyword name, and optional type.

    Allows rules to declare both positional and keyword bindings so the
    extractor can find the argument regardless of how it was passed::

        param: {arg: 0, kwarg: "name", type: "str"}

    The extractor tries ``kwarg`` first (always known), then falls back to
    ``arg`` (positional index).
    """

    arg: int | None = None
    kwarg: str | None = None
    type: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> ParamSpec:
        return cls(
            arg=d.get("arg"),
            kwarg=d.get("kwarg"),
            type=d.get("type"),
        )


@dataclass
class WhereNode:
    """Extraction rule tree node for pulling parameters from call sites."""

    param: str | int | ParamSpec | None = None
    access: list[str] | None = None
    match: str | None = None
    assign_to: str | None = None
    example: str | None = None
    flatten_on: str | None = None
    where: list[WhereNode] | None = None

    @classmethod
    def from_dict(cls, d: dict) -> WhereNode:
        children = None
        if "where" in d:
            children = [WhereNode.from_dict(c) for c in d["where"]]
        raw_param = d.get("param")
        if isinstance(raw_param, dict):
            param: str | int | ParamSpec | None = ParamSpec.from_dict(raw_param)
        else:
            param = raw_param
        return cls(
            param=param,
            access=d.get("access"),
            match=d.get("match"),
            assign_to=d.get("assign-to"),
            example=d.get("example"),
            flatten_on=d.get("flatten-on"),
            where=children,
        )


@dataclass
class CompilerRule:
    """A single compiler classification rule."""

    match: str
    treat_as: TreatAs
    where: list[WhereNode] | None = None

    @classmethod
    def from_dict(cls, d: dict) -> CompilerRule:
        where = None
        if "where" in d:
            where = [WhereNode.from_dict(c) for c in d["where"]]
            treat_as = TreatAs(d.get("treat-as", "config"))
        else:
            treat_as = TreatAs(d["treat-as"])
        return cls(match=d["match"], treat_as=treat_as, where=where)


class RuleEngine:
    """Classifies symbols against an ordered list of compiler rules.

    Resolution uses exact match only: the rule's ``match`` field must equal
    the fully-qualified symbol name.
    """

    def __init__(self, rules: list[CompilerRule]) -> None:
        self._rules = {rule.match: rule for rule in rules}

    @property
    def rules(self) -> list[CompilerRule]:
        return list(self._rules.values())

    def classify(self, symbol: str, *, module_path: str | None = None) -> TreatAs | None:
        """Return the TreatAs classification for a symbol, or None if no rule matches."""
        rule = self.get_rule(symbol, module_path=module_path)
        if rule is not None:
            return rule.treat_as
        return None

    def get_rule(self, symbol: str, *, module_path: str | None = None) -> CompilerRule | None:
        """Return the matching rule, or None."""
        return self._rules.get(symbol)

    @classmethod
    def with_defaults(cls, *, extra_rules: list[CompilerRule] | None = None) -> RuleEngine:
        """Create an engine with shipped defaults + optional user rules.

        User rules take precedence (overwrite defaults for the same match key).
        Defaults are loaded from ``asya_lab/defaults/compiler.rules.yaml``.
        """
        from asya_lab.flow.rules import _load_default_rules

        defaults = [CompilerRule.from_dict(d) for d in _load_default_rules() if "where" in d]
        rules = defaults + list(extra_rules or [])
        return cls(rules)

    @classmethod
    def from_config(cls, rules_cfg: list[dict] | None) -> RuleEngine:
        """Load rules from config dicts + shipped defaults."""
        extra: list[CompilerRule] = []
        if rules_cfg:
            extra = [CompilerRule.from_dict(d) for d in rules_cfg]
        return cls.with_defaults(extra_rules=extra)
