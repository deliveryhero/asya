"""Tests for parser integration with compiler rules."""

from asya_lab.compiler.rules import CompilerRule, RuleEngine, TreatAs
from asya_lab.flow.parser import ActorCall, AdapterCall, FlowParser, Mutation


class TestInlineComment:
    def test_asya_actor_comment(self) -> None:
        source = "@flow\ndef flow(p: dict) -> dict:\n    p = handler(p)  # asya: actor\n    return p\n"
        engine = RuleEngine.with_defaults()
        parser = FlowParser(source, "test.py", rule_engine=engine)
        ops = parser.parse().operations
        assert isinstance(ops[0], ActorCall)

    def test_asya_inline_comment(self) -> None:
        source = "@flow\ndef flow(p: dict) -> dict:\n    p = helper(p)  # asya: inline\n    return p\n"
        engine = RuleEngine.with_defaults()
        parser = FlowParser(source, "test.py", rule_engine=engine)
        ops = parser.parse().operations
        assert isinstance(ops[0], Mutation)
        assert "helper(p)" in ops[0].code

    def test_inline_comment_overrides_rule(self) -> None:
        source = "@flow\ndef flow(p: dict) -> dict:\n    p = handler(p)  # asya: inline\n    return p\n"
        engine = RuleEngine.with_defaults()
        parser = FlowParser(source, "test.py", module_path="my_project", rule_engine=engine)
        ops = parser.parse().operations
        # Inline comment wins regardless of rule engine classification
        assert isinstance(ops[0], Mutation)


class TestRuleClassification:
    def test_explicit_inline_rule(self) -> None:
        source = "@flow\ndef flow(p: dict) -> dict:\n    p = tenacity.retry(p)\n    return p\n"
        engine = RuleEngine([CompilerRule(match="tenacity.retry", treat_as=TreatAs.INLINE)])
        parser = FlowParser(source, "test.py", rule_engine=engine)
        ops = parser.parse().operations
        assert isinstance(ops[0], Mutation)

    def test_no_rule_defaults_to_actor(self) -> None:
        source = "@flow\ndef flow(p: dict) -> dict:\n    p = unknown_lib.func(p)\n    return p\n"
        engine = RuleEngine.with_defaults()
        parser = FlowParser(source, "test.py", rule_engine=engine)
        ops = parser.parse().operations
        assert isinstance(ops[0], ActorCall)

    def test_bare_symbol_no_rule_is_actor(self) -> None:
        # Without rules, bare symbols become actors.
        source = "@flow\ndef flow(p: dict) -> dict:\n    p = helper(p)\n    return p\n"
        engine = RuleEngine.with_defaults()
        parser = FlowParser(source, "test.py", module_path="my_project.flows", rule_engine=engine)
        ops = parser.parse().operations
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "helper"

    def test_unfold_with_definition(self) -> None:
        # When a function IS defined in the same file and classified as UNFOLD,
        # the parser expands it.
        source = (
            "def helper(p: dict) -> dict:\n"
            "    p = inner_handler(p)  # asya: actor\n"
            "    return p\n\n"
            "@flow\ndef flow(p: dict) -> dict:\n"
            "    p = helper(p)\n"
            "    return p\n"
        )
        engine = RuleEngine([CompilerRule(match="helper", treat_as=TreatAs.UNFOLD)])
        parser = FlowParser(source, "test.py", module_path="my_project.flows", rule_engine=engine)
        ops = parser.parse().operations
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "inner_handler"

    def test_no_engine_all_actors(self) -> None:
        source = "@flow\ndef flow(p: dict) -> dict:\n    p = handler(p)\n    return p\n"
        parser = FlowParser(source, "test.py")
        ops = parser.parse().operations
        assert isinstance(ops[0], ActorCall)

    def test_no_engine_backwards_compatible(self) -> None:
        source = "@flow\ndef flow(p: dict) -> dict:\n    p = handler_a(p)\n    p = handler_b(p)\n    return p\n"
        parser = FlowParser(source, "test.py")
        ops = parser.parse().operations
        assert len(ops) == 3  # 2 actor calls + return
        assert isinstance(ops[0], ActorCall)
        assert isinstance(ops[1], ActorCall)


class TestAutoDecoratorStripping:
    def test_rule_match_auto_strips_decorator(self) -> None:
        source = (
            "from claude_agent_sdk import tool\n"
            "@tool\n"
            "def get_weather(city: str) -> dict:\n"
            "    ...\n\n"
            "@flow\n"
            "def flow(p: dict) -> dict:\n"
            "    p = handler(p)\n"
            "    return p\n"
        )
        engine = RuleEngine([CompilerRule(match="claude_agent_sdk.tool", treat_as=TreatAs.ACTOR)])
        parser = FlowParser(source, "test.py", rule_engine=engine)
        result = parser.parse()
        assert "claude_agent_sdk.tool" in result.ignore_decorators

    def test_keep_decorator_prevents_stripping(self) -> None:
        source = (
            "from functools import lru_cache\n"
            "@lru_cache\n"
            "def cached_fn(p: dict) -> dict:\n"
            "    ...\n\n"
            "@flow\n"
            "def flow(p: dict) -> dict:\n"
            "    p = handler(p)\n"
            "    return p\n"
        )
        engine = RuleEngine([CompilerRule(match="functools.lru_cache", treat_as=TreatAs.INLINE, keep_decorator=True)])
        parser = FlowParser(source, "test.py", rule_engine=engine)
        result = parser.parse()
        assert "functools.lru_cache" not in result.ignore_decorators

    def test_no_rule_engine_no_stripping(self) -> None:
        source = (
            "from claude_agent_sdk import tool\n"
            "@tool\n"
            "def get_weather(city: str) -> dict:\n"
            "    ...\n\n"
            "@flow\n"
            "def flow(p: dict) -> dict:\n"
            "    p = handler(p)\n"
            "    return p\n"
        )
        parser = FlowParser(source, "test.py")
        result = parser.parse()
        assert "claude_agent_sdk.tool" not in result.ignore_decorators

    def test_tool_decorator_classifies_function_as_actor(self) -> None:
        source = (
            "from claude_agent_sdk import tool\n"
            "@tool\n"
            "def get_weather(city: str) -> dict:\n"
            "    ...\n\n"
            "@flow\n"
            "def flow(p: dict) -> dict:\n"
            "    p = get_weather(p)\n"
            "    return p\n"
        )
        engine = RuleEngine([CompilerRule(match="claude_agent_sdk.tool", treat_as=TreatAs.ACTOR)])
        parser = FlowParser(source, "test.py", rule_engine=engine)
        result = parser.parse()
        assert isinstance(result.operations[0], ActorCall)
        assert result.operations[0].name == "get_weather"


class TestAdapterCallDetection:
    def test_subscript_target_with_directive(self) -> None:
        source = (
            "@flow\n"
            "def flow(p: dict) -> dict:\n"
            '    p["result"] = get_weather(p["city"], p["time"])  # asya: actor\n'
            "    return p\n"
        )
        parser = FlowParser(source, "test.py")
        result = parser.parse()
        assert isinstance(result.operations[0], AdapterCall)
        assert result.operations[0].name == "get_weather"
        assert result.operations[0].input_args == ["p['city']", "p['time']"]
        assert result.operations[0].output_path == "p['result']"
        assert result.operations[0].is_async is False

    def test_subscript_target_with_await(self) -> None:
        source = (
            "@flow\n"
            "async def flow(p: dict) -> dict:\n"
            '    p["result"] = await get_weather(p["city"])  # asya: actor\n'
            "    return p\n"
        )
        parser = FlowParser(source, "test.py")
        result = parser.parse()
        assert isinstance(result.operations[0], AdapterCall)
        assert result.operations[0].is_async is True

    def test_p_target_with_multiple_args_and_directive(self) -> None:
        source = '@flow\ndef flow(p: dict) -> dict:\n    p = process(p["x"], p["y"])  # asya: actor\n    return p\n'
        parser = FlowParser(source, "test.py")
        result = parser.parse()
        assert isinstance(result.operations[0], AdapterCall)
        assert result.operations[0].name == "process"
        assert result.operations[0].output_path is None
        assert result.operations[0].input_args == ["p['x']", "p['y']"]

    def test_subscript_target_with_rule_engine(self) -> None:
        source = (
            "from my_tools import fetch_data\n"
            "@flow\n"
            "def flow(p: dict) -> dict:\n"
            '    p["data"] = fetch_data(p["url"])\n'
            "    return p\n"
        )
        engine = RuleEngine([CompilerRule(match="my_tools.fetch_data", treat_as=TreatAs.ACTOR)])
        parser = FlowParser(source, "test.py", rule_engine=engine)
        result = parser.parse()
        assert isinstance(result.operations[0], AdapterCall)
        assert result.operations[0].name == "fetch_data"

    def test_no_directive_no_rule_stays_mutation(self) -> None:
        source = '@flow\ndef flow(p: dict) -> dict:\n    p["result"] = some_func(p["x"])\n    return p\n'
        parser = FlowParser(source, "test.py")
        result = parser.parse()
        assert isinstance(result.operations[0], Mutation)

    def test_adapter_call_added_to_actors_list(self) -> None:
        source = (
            '@flow\ndef flow(p: dict) -> dict:\n    p["result"] = get_weather(p["city"])  # asya: actor\n    return p\n'
        )
        parser = FlowParser(source, "test.py")
        result = parser.parse()
        assert "get_weather" in result.actors

    def test_decorator_classified_adapter(self) -> None:
        source = (
            "from claude_agent_sdk import tool\n"
            "@tool\n"
            "def get_weather(city: str) -> dict:\n"
            "    ...\n\n"
            "@flow\n"
            "def flow(p: dict) -> dict:\n"
            '    p["weather"] = get_weather(p["city"])\n'
            "    return p\n"
        )
        engine = RuleEngine([CompilerRule(match="claude_agent_sdk.tool", treat_as=TreatAs.ACTOR)])
        parser = FlowParser(source, "test.py", rule_engine=engine)
        result = parser.parse()
        assert isinstance(result.operations[0], AdapterCall)
        assert result.operations[0].name == "get_weather"
