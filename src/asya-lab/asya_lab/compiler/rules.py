"""Compiler rules: pattern matching for Python decorators and calls.

Each rule maps a Python construct (e.g. ``tenacity.retry``) to compiler
behaviour (treat-as actor, inline, config, ...) and optionally extracts
parameter values via a ``where:`` tree.

Matching uses a most-specific-wins strategy with four tiers:
  Tier 0 -- exact match ("tenacity.retry" matches "tenacity.retry")
  Tier 1 -- prefix wildcard ("tenacity.*" matches "tenacity.retry")
  Tier 2 -- same-package dot (".") -- symbol in the same package as module_path
  Tier 3 -- global wildcard ("*") -- matches everything
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
class WhereNode:
    """Extraction rule tree node for pulling parameters from call sites."""

    param: str | None = None
    access: list[str] | None = None
    match: str | None = None
    assign_to: str | None = None
    example: str | None = None
    where: list[WhereNode] | None = None

    @classmethod
    def from_dict(cls, d: dict) -> WhereNode:
        children = None
        if "where" in d:
            children = [WhereNode.from_dict(c) for c in d["where"]]
        return cls(
            param=d.get("param"),
            access=d.get("access"),
            match=d.get("match"),
            assign_to=d.get("assign-to"),
            example=d.get("example"),
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


def _root_package(dotted: str) -> str | None:
    """Return the root package of a dotted path, or None if no dots."""
    parts = dotted.split(".")
    if len(parts) > 1:
        return parts[0]
    return None


def _match_tier(pattern: str, symbol: str, *, module_path: str | None) -> int | None:
    """Return the match tier (0-3) or None if no match.

    Lower tier = more specific = higher priority.
    """
    if pattern == symbol:
        return 0

    if pattern.endswith(".*"):
        prefix = pattern[:-2]
        if symbol.startswith(prefix + "."):
            return 1
        return None

    if pattern == ".":
        if "." not in symbol:
            return 2
        if module_path is not None:
            sym_root = _root_package(symbol)
            mod_root = _root_package(module_path)
            if sym_root is not None and mod_root is not None and sym_root == mod_root:
                return 2
        return None

    if pattern == "*":
        return 3

    return None


_DEFAULT_RULES: list[CompilerRule] = [
    CompilerRule(match=".", treat_as=TreatAs.UNFOLD),
    CompilerRule(match="*", treat_as=TreatAs.INLINE),
]


class RuleEngine:
    """Classifies symbols against an ordered list of compiler rules.

    Resolution uses most-specific-wins: the rule with the lowest tier wins.
    Within tier 1 (prefix wildcards), longer prefixes win.
    """

    def __init__(self, rules: list[CompilerRule]) -> None:
        self._rules = list(rules)

    @property
    def rules(self) -> list[CompilerRule]:
        return list(self._rules)

    def classify(self, symbol: str, *, module_path: str | None = None) -> TreatAs | None:
        """Return the TreatAs classification for a symbol, or None if no rule matches."""
        rule = self.get_rule(symbol, module_path=module_path)
        if rule is not None:
            return rule.treat_as
        return None

    def get_rule(self, symbol: str, *, module_path: str | None = None) -> CompilerRule | None:
        """Return the most-specific matching rule, or None."""
        best_rule: CompilerRule | None = None
        best_tier: int = 999
        best_prefix_len: int = -1

        for rule in self._rules:
            tier = _match_tier(rule.match, symbol, module_path=module_path)
            if tier is None:
                continue
            prefix_len = len(rule.match) if tier == 1 else 0
            if tier < best_tier or (tier == best_tier and tier == 1 and prefix_len > best_prefix_len):
                best_rule = rule
                best_tier = tier
                best_prefix_len = prefix_len

        return best_rule

    @classmethod
    def with_defaults(cls, *, extra_rules: list[CompilerRule] | None = None) -> RuleEngine:
        """Create an engine with default rules, optionally prepending extras.

        Default rules (lowest priority):
          "." -> UNFOLD  (same-package symbols are unfolded)
          "*" -> INLINE  (everything else is inlined)
        """
        rules = list(extra_rules or []) + list(_DEFAULT_RULES)
        return cls(rules)

    @classmethod
    def from_config(cls, rules_cfg: list[dict] | None) -> RuleEngine:
        """Load rules from config dicts and append defaults."""
        extra: list[CompilerRule] = []
        if rules_cfg:
            extra = [CompilerRule.from_dict(d) for d in rules_cfg]
        return cls.with_defaults(extra_rules=extra)
