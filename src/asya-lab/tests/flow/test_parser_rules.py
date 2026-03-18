"""Tests for parser integration with compiler rules."""

from asya_lab.compiler.rules import RuleEngine
from asya_lab.flow.ir import ActorCall, InlineCode
from asya_lab.flow.parser import FlowParser


class TestInlineComment:
    def test_asya_actor_comment(self) -> None:
        source = "def flow(p: dict) -> dict:\n    p = handler(p)  # asya: actor\n    return p\n"
        engine = RuleEngine.with_defaults()
        parser = FlowParser(source, "test.py", rule_engine=engine)
        _, ops = parser.parse()
        assert isinstance(ops[0], ActorCall)

    def test_asya_inline_comment(self) -> None:
        source = "def flow(p: dict) -> dict:\n    p = helper(p)  # asya: inline\n    return p\n"
        engine = RuleEngine.with_defaults()
        parser = FlowParser(source, "test.py", rule_engine=engine)
        _, ops = parser.parse()
        assert isinstance(ops[0], InlineCode)
        assert "helper(p)" in ops[0].code

    def test_inline_comment_overrides_rule(self) -> None:
        source = "def flow(p: dict) -> dict:\n    p = handler(p)  # asya: inline\n    return p\n"
        engine = RuleEngine.with_defaults()
        parser = FlowParser(source, "test.py", module_path="my_project", rule_engine=engine)
        _, ops = parser.parse()
        # Even though same-package default is unfold, inline comment wins
        assert isinstance(ops[0], InlineCode)


class TestRuleClassification:
    def test_external_classified_inline_by_default(self) -> None:
        source = "def flow(p: dict) -> dict:\n    p = tenacity.retry(p)\n    return p\n"
        engine = RuleEngine.with_defaults()
        parser = FlowParser(source, "test.py", rule_engine=engine)
        _, ops = parser.parse()
        assert isinstance(ops[0], InlineCode)

    def test_same_package_classified_unfold(self) -> None:
        source = "def flow(p: dict) -> dict:\n    p = helper(p)\n    return p\n"
        engine = RuleEngine.with_defaults()
        parser = FlowParser(source, "test.py", module_path="my_project.flows", rule_engine=engine)
        _, ops = parser.parse()
        assert isinstance(ops[0], ActorCall)
        assert ops[0].treat_as == "unfold"

    def test_no_engine_all_actors(self) -> None:
        source = "def flow(p: dict) -> dict:\n    p = handler(p)\n    return p\n"
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()
        assert isinstance(ops[0], ActorCall)
        assert ops[0].treat_as == "actor"

    def test_no_engine_backwards_compatible(self) -> None:
        source = "def flow(p: dict) -> dict:\n    p = handler_a(p)\n    p = handler_b(p)\n    return p\n"
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()
        assert len(ops) == 3  # 2 actor calls + return
        assert isinstance(ops[0], ActorCall)
        assert isinstance(ops[1], ActorCall)
