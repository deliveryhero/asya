"""Tests for compiler rules engine."""

import pytest
from asya_lab.compiler.rules import (
    CompilerRule,
    RuleEngine,
    TreatAs,
    WhereNode,
)


class TestTreatAs:
    def test_valid_values(self) -> None:
        assert TreatAs("actor") is TreatAs.ACTOR
        assert TreatAs("inline") is TreatAs.INLINE
        assert TreatAs("unfold") is TreatAs.UNFOLD
        assert TreatAs("flow") is TreatAs.FLOW
        assert TreatAs("config") is TreatAs.CONFIG

    def test_invalid_value_raises(self) -> None:
        with pytest.raises(ValueError):
            TreatAs("bogus")


class TestWhereNodeFromDict:
    def test_minimal(self) -> None:
        node = WhereNode.from_dict({"param": "wait"})
        assert node.param == "wait"
        assert node.assign_to is None
        assert node.where is None

    def test_assign_to_key_mapping(self) -> None:
        node = WhereNode.from_dict({"param": "wait", "assign-to": "retry.wait"})
        assert node.assign_to == "retry.wait"

    def test_nested_where(self) -> None:
        d = {
            "param": "retry",
            "where": [
                {"param": "max_retries", "assign-to": "retry.max"},
            ],
        }
        node = WhereNode.from_dict(d)
        assert node.where is not None
        assert len(node.where) == 1
        assert node.where[0].param == "max_retries"
        assert node.where[0].assign_to == "retry.max"


class TestCompilerRuleFromDict:
    def test_classification_rule(self) -> None:
        rule = CompilerRule.from_dict({"match": "tenacity.retry", "treat-as": "inline"})
        assert rule.match == "tenacity.retry"
        assert rule.treat_as is TreatAs.INLINE
        assert rule.where is None

    def test_extraction_rule_defaults_to_config(self) -> None:
        rule = CompilerRule.from_dict(
            {
                "match": "tenacity.retry",
                "where": [{"param": "wait"}],
            }
        )
        assert rule.treat_as is TreatAs.CONFIG
        assert rule.where is not None
        assert len(rule.where) == 1

    def test_extraction_rule_with_explicit_treat_as(self) -> None:
        rule = CompilerRule.from_dict(
            {
                "match": "tenacity.retry",
                "treat-as": "inline",
                "where": [{"param": "wait"}],
            }
        )
        assert rule.treat_as is TreatAs.INLINE
        assert rule.where is not None


class TestRuleEngineExactMatch:
    def test_exact_match(self) -> None:
        engine = RuleEngine([CompilerRule(match="tenacity.retry", treat_as=TreatAs.CONFIG)])
        assert engine.classify("tenacity.retry") is TreatAs.CONFIG

    def test_exact_no_match(self) -> None:
        engine = RuleEngine([CompilerRule(match="tenacity.retry", treat_as=TreatAs.CONFIG)])
        assert engine.classify("tenacity.stop") is None


class TestRuleEngineWildcardMatch:
    def test_global_wildcard(self) -> None:
        engine = RuleEngine([CompilerRule(match="*", treat_as=TreatAs.INLINE)])
        assert engine.classify("anything") is TreatAs.INLINE
        assert engine.classify("some.module.func") is TreatAs.INLINE

    def test_prefix_wildcard(self) -> None:
        engine = RuleEngine([CompilerRule(match="tenacity.*", treat_as=TreatAs.CONFIG)])
        assert engine.classify("tenacity.retry") is TreatAs.CONFIG
        assert engine.classify("tenacity.stop") is TreatAs.CONFIG

    def test_prefix_wildcard_no_match(self) -> None:
        engine = RuleEngine([CompilerRule(match="tenacity.*", treat_as=TreatAs.CONFIG)])
        assert engine.classify("other.retry") is None
        assert engine.classify("tenacity") is None


class TestRuleEngineDotMatch:
    def test_dot_matches_bare_symbol(self) -> None:
        engine = RuleEngine([CompilerRule(match=".", treat_as=TreatAs.UNFOLD)])
        assert engine.classify("my_func") is TreatAs.UNFOLD

    def test_dot_matches_same_package(self) -> None:
        engine = RuleEngine([CompilerRule(match=".", treat_as=TreatAs.UNFOLD)])
        assert engine.classify("mypackage.util", module_path="mypackage.main") is TreatAs.UNFOLD

    def test_dot_no_match_different_package(self) -> None:
        engine = RuleEngine([CompilerRule(match=".", treat_as=TreatAs.UNFOLD)])
        assert engine.classify("other.util", module_path="mypackage.main") is None

    def test_dot_no_match_dotted_symbol_without_module_path(self) -> None:
        engine = RuleEngine([CompilerRule(match=".", treat_as=TreatAs.UNFOLD)])
        assert engine.classify("other.util") is None


class TestRuleEngineSpecificity:
    def test_exact_beats_prefix(self) -> None:
        engine = RuleEngine(
            [
                CompilerRule(match="tenacity.*", treat_as=TreatAs.INLINE),
                CompilerRule(match="tenacity.retry", treat_as=TreatAs.CONFIG),
            ]
        )
        assert engine.classify("tenacity.retry") is TreatAs.CONFIG
        assert engine.classify("tenacity.stop") is TreatAs.INLINE

    def test_prefix_beats_dot(self) -> None:
        engine = RuleEngine(
            [
                CompilerRule(match=".", treat_as=TreatAs.UNFOLD),
                CompilerRule(match="mypackage.*", treat_as=TreatAs.ACTOR),
            ]
        )
        assert engine.classify("mypackage.func", module_path="mypackage.main") is TreatAs.ACTOR

    def test_dot_beats_wildcard(self) -> None:
        engine = RuleEngine(
            [
                CompilerRule(match="*", treat_as=TreatAs.INLINE),
                CompilerRule(match=".", treat_as=TreatAs.UNFOLD),
            ]
        )
        assert engine.classify("my_func") is TreatAs.UNFOLD

    def test_longer_prefix_wins(self) -> None:
        engine = RuleEngine(
            [
                CompilerRule(match="a.*", treat_as=TreatAs.INLINE),
                CompilerRule(match="a.b.*", treat_as=TreatAs.ACTOR),
            ]
        )
        assert engine.classify("a.b.c") is TreatAs.ACTOR
        assert engine.classify("a.x") is TreatAs.INLINE

    def test_exact_beats_everything(self) -> None:
        engine = RuleEngine(
            [
                CompilerRule(match="*", treat_as=TreatAs.INLINE),
                CompilerRule(match=".", treat_as=TreatAs.UNFOLD),
                CompilerRule(match="tenacity.*", treat_as=TreatAs.FLOW),
                CompilerRule(match="tenacity.retry", treat_as=TreatAs.CONFIG),
            ]
        )
        assert engine.classify("tenacity.retry") is TreatAs.CONFIG


class TestRuleEngineGetRule:
    def test_get_rule_returns_matching_rule(self) -> None:
        rule = CompilerRule(match="tenacity.retry", treat_as=TreatAs.CONFIG)
        engine = RuleEngine([rule])
        assert engine.get_rule("tenacity.retry") is rule

    def test_get_rule_returns_none_when_no_match(self) -> None:
        engine = RuleEngine([CompilerRule(match="tenacity.retry", treat_as=TreatAs.CONFIG)])
        assert engine.get_rule("other.func") is None


class TestRuleEngineWithDefaults:
    def test_defaults_provide_dot_and_wildcard(self) -> None:
        engine = RuleEngine.with_defaults()
        assert engine.classify("my_func") is TreatAs.UNFOLD
        assert engine.classify("external.lib") is TreatAs.INLINE

    def test_extra_rules_override_defaults(self) -> None:
        extra = [CompilerRule(match="tenacity.retry", treat_as=TreatAs.CONFIG)]
        engine = RuleEngine.with_defaults(extra_rules=extra)
        assert engine.classify("tenacity.retry") is TreatAs.CONFIG
        assert engine.classify("my_func") is TreatAs.UNFOLD
        assert engine.classify("other.lib") is TreatAs.INLINE

    def test_defaults_rules_property(self) -> None:
        engine = RuleEngine.with_defaults()
        matches = [r.match for r in engine.rules]
        assert "." in matches
        assert "*" in matches


class TestRuleEngineFromConfig:
    def test_none_config(self) -> None:
        engine = RuleEngine.from_config(None)
        assert engine.classify("my_func") is TreatAs.UNFOLD
        assert engine.classify("ext.lib") is TreatAs.INLINE

    def test_empty_config(self) -> None:
        engine = RuleEngine.from_config([])
        assert engine.classify("my_func") is TreatAs.UNFOLD

    def test_config_with_user_rules(self) -> None:
        cfg = [
            {"match": "tenacity.retry", "treat-as": "config"},
            {"match": "functools.*", "treat-as": "inline"},
        ]
        engine = RuleEngine.from_config(cfg)
        assert engine.classify("tenacity.retry") is TreatAs.CONFIG
        assert engine.classify("functools.lru_cache") is TreatAs.INLINE
        assert engine.classify("my_func") is TreatAs.UNFOLD

    def test_config_extraction_rule(self) -> None:
        cfg = [
            {
                "match": "tenacity.retry",
                "where": [{"param": "wait", "assign-to": "retry.wait"}],
            },
        ]
        engine = RuleEngine.from_config(cfg)
        rule = engine.get_rule("tenacity.retry")
        assert rule is not None
        assert rule.treat_as is TreatAs.CONFIG
        assert rule.where is not None
        assert rule.where[0].assign_to == "retry.wait"


class TestRuleEngineNoMatch:
    def test_empty_engine_returns_none(self) -> None:
        engine = RuleEngine([])
        assert engine.classify("anything") is None
        assert engine.get_rule("anything") is None
