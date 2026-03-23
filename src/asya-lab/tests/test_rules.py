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


class TestRuleEngineMultipleExactRules:
    def test_last_exact_match_wins(self) -> None:
        engine = RuleEngine(
            [
                CompilerRule(match="tenacity.retry", treat_as=TreatAs.INLINE),
                CompilerRule(match="tenacity.retry", treat_as=TreatAs.CONFIG),
            ]
        )
        assert engine.classify("tenacity.retry") is TreatAs.CONFIG

    def test_unmatched_returns_none(self) -> None:
        engine = RuleEngine(
            [
                CompilerRule(match="tenacity.retry", treat_as=TreatAs.CONFIG),
                CompilerRule(match="tenacity.stop", treat_as=TreatAs.INLINE),
            ]
        )
        assert engine.classify("tenacity.retry") is TreatAs.CONFIG
        assert engine.classify("tenacity.stop") is TreatAs.INLINE
        assert engine.classify("other.func") is None


class TestRuleEngineGetRule:
    def test_get_rule_returns_matching_rule(self) -> None:
        rule = CompilerRule(match="tenacity.retry", treat_as=TreatAs.CONFIG)
        engine = RuleEngine([rule])
        assert engine.get_rule("tenacity.retry") is rule

    def test_get_rule_returns_none_when_no_match(self) -> None:
        engine = RuleEngine([CompilerRule(match="tenacity.retry", treat_as=TreatAs.CONFIG)])
        assert engine.get_rule("other.func") is None


class TestRuleEngineWithDefaults:
    def test_defaults_loads_shipped_where_rules(self) -> None:
        engine = RuleEngine.with_defaults()
        assert engine.classify("tenacity.retry") is TreatAs.CONFIG
        assert engine.classify("my_func") is None

    def test_extra_rules_are_used(self) -> None:
        extra = [CompilerRule(match="custom.lib", treat_as=TreatAs.INLINE)]
        engine = RuleEngine.with_defaults(extra_rules=extra)
        assert engine.classify("custom.lib") is TreatAs.INLINE
        assert engine.classify("tenacity.retry") is TreatAs.CONFIG
        assert engine.classify("other.lib") is None

    def test_defaults_rules_property(self) -> None:
        engine = RuleEngine.with_defaults()
        assert len(engine.rules) > 0
        assert any(r.match == "tenacity.retry" for r in engine.rules)


class TestRuleEngineFromConfig:
    def test_none_config(self) -> None:
        engine = RuleEngine.from_config(None)
        assert engine.classify("my_func") is None
        assert engine.classify("ext.lib") is None

    def test_empty_config(self) -> None:
        engine = RuleEngine.from_config([])
        assert engine.classify("my_func") is None

    def test_config_with_user_rules(self) -> None:
        cfg = [
            {"match": "tenacity.retry", "treat-as": "config"},
            {"match": "functools.lru_cache", "treat-as": "inline"},
        ]
        engine = RuleEngine.from_config(cfg)
        assert engine.classify("tenacity.retry") is TreatAs.CONFIG
        assert engine.classify("functools.lru_cache") is TreatAs.INLINE
        assert engine.classify("my_func") is None

    def test_config_loads_all_rules_regardless_of_scope(self) -> None:
        cfg = [
            {"match": "tenacity.retry", "treat-as": "config"},
            {"match": "asyncio.timeout", "treat-as": "config"},
        ]
        engine = RuleEngine.from_config(cfg)
        assert engine.classify("tenacity.retry") is TreatAs.CONFIG
        assert engine.classify("asyncio.timeout") is TreatAs.CONFIG

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


class TestKeepDecorator:
    def test_keep_decorator_defaults_to_false(self) -> None:
        rule = CompilerRule.from_dict({"match": "tenacity.retry", "treat-as": "config"})
        assert rule.keep_decorator is False

    def test_keep_decorator_true_from_dict(self) -> None:
        rule = CompilerRule.from_dict({"match": "functools.lru_cache", "treat-as": "inline", "keep-decorator": True})
        assert rule.keep_decorator is True

    def test_keep_decorator_false_from_dict(self) -> None:
        rule = CompilerRule.from_dict({"match": "tool", "treat-as": "actor", "keep-decorator": False})
        assert rule.keep_decorator is False


class TestDefaultToolRules:
    def test_defaults_include_tool_rules(self) -> None:
        engine = RuleEngine.with_defaults()
        assert engine.classify("claude_agent_sdk.tool") is TreatAs.ACTOR
        assert engine.classify("langchain.tools.tool") is TreatAs.ACTOR
        assert engine.classify("langchain_core.tools.tool") is TreatAs.ACTOR

    def test_tool_rules_have_keep_decorator_false(self) -> None:
        engine = RuleEngine.with_defaults()
        rule = engine.get_rule("claude_agent_sdk.tool")
        assert rule is not None
        assert rule.keep_decorator is False


class TestRuleEngineNoMatch:
    def test_empty_engine_returns_none(self) -> None:
        engine = RuleEngine([])
        assert engine.classify("anything") is None
        assert engine.get_rule("anything") is None
