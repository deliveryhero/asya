"""Unit tests for fan-out parsing in the flow DSL parser."""

import textwrap

import pytest
from asya_cli.flow.errors import FlowCompileError
from asya_cli.flow.ir import FanOutCall
from asya_cli.flow.parser import FlowParser

from .test_helpers import contains_with_either_quotes


class TestListComprehensionFanOut:
    """Test parsing of list comprehension fan-out syntax."""

    def test_parse_homogeneous_fanout_for_in(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["results"] = [research_agent(t) for t in p["topics"]]
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 2
        fanout = ops[0]
        assert isinstance(fanout, FanOutCall)
        assert fanout.target_key == "/results"
        assert fanout.pattern == "comprehension"
        assert len(fanout.actor_calls) == 1
        assert fanout.actor_calls[0][0] == "research_agent"
        assert fanout.actor_calls[0][1] == "t"
        assert fanout.iter_var == "t"
        assert fanout.iterable is not None
        assert contains_with_either_quotes(fanout.iterable, 'p["topics"]')

    def test_parse_range_based_comprehension(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["results"] = [research_agent(p["topics"][i]) for i in range(len(p["topics"]))]
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 2
        fanout = ops[0]
        assert isinstance(fanout, FanOutCall)
        assert fanout.target_key == "/results"
        assert fanout.pattern == "comprehension"
        assert len(fanout.actor_calls) == 1
        assert fanout.actor_calls[0][0] == "research_agent"
        assert contains_with_either_quotes(fanout.actor_calls[0][1], 'p["topics"][i]')
        assert fanout.iter_var == "i"
        assert fanout.iterable is not None
        assert "range" in fanout.iterable
        assert "len" in fanout.iterable

    def test_parse_fixed_count_comprehension_underscore(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["results"] = [research_agent(p["query"]) for _ in range(10)]
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 2
        fanout = ops[0]
        assert isinstance(fanout, FanOutCall)
        assert fanout.target_key == "/results"
        assert fanout.pattern == "comprehension"
        assert len(fanout.actor_calls) == 1
        assert fanout.actor_calls[0][0] == "research_agent"
        assert contains_with_either_quotes(fanout.actor_calls[0][1], 'p["query"]')
        assert fanout.iter_var == "_"
        assert fanout.iterable == "range(10)"

    def test_parse_await_in_comprehension_element(self):
        source = textwrap.dedent("""
            async def flow(p: dict) -> dict:
                p["results"] = [await research_agent(t) for t in p["topics"]]
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        fanout = ops[0]
        assert isinstance(fanout, FanOutCall)
        assert fanout.pattern == "comprehension"
        assert fanout.actor_calls[0][0] == "research_agent"

    def test_comprehension_preserves_lineno(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["results"] = [research_agent(t) for t in p["topics"]]
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        fanout = ops[0]
        assert isinstance(fanout, FanOutCall)
        assert fanout.lineno == 3

    def test_reject_nested_comprehensions(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["results"] = [agent(x) for t in p["topics"] for x in t["items"]]
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="[Nn]ested"):
            parser.parse()

    def test_reject_comprehension_with_non_actor_element(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["results"] = [t * 2 for t in p["topics"]]
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="[Aa]ctor call"):
            parser.parse()

    def test_reject_comprehension_with_filter(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["results"] = [agent(t) for t in p["topics"] if t["valid"]]
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="[Ff]ilter"):
            parser.parse()


class TestListLiteralFanOut:
    """Test parsing of list literal fan-out syntax."""

    def test_parse_heterogeneous_fanout(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["result"] = [
                    sentiment_analyzer(p["text"]),
                    topic_extractor(p["text"]),
                    entity_recognizer(p["text"]),
                ]
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 2
        fanout = ops[0]
        assert isinstance(fanout, FanOutCall)
        assert fanout.target_key == "/result"
        assert fanout.pattern == "literal"
        assert len(fanout.actor_calls) == 3
        assert fanout.actor_calls[0][0] == "sentiment_analyzer"
        assert fanout.actor_calls[1][0] == "topic_extractor"
        assert fanout.actor_calls[2][0] == "entity_recognizer"
        assert fanout.iter_var is None
        assert fanout.iterable is None

    def test_list_literal_payload_expressions(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["result"] = [
                    agent_a(p["x"]),
                    agent_b(p["y"]),
                ]
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        fanout = ops[0]
        assert isinstance(fanout, FanOutCall)
        assert contains_with_either_quotes(fanout.actor_calls[0][1], 'p["x"]')
        assert contains_with_either_quotes(fanout.actor_calls[1][1], 'p["y"]')

    def test_list_literal_with_await(self):
        source = textwrap.dedent("""
            async def flow(p: dict) -> dict:
                p["result"] = [
                    await sentiment_analyzer(p["text"]),
                    await topic_extractor(p["text"]),
                ]
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        fanout = ops[0]
        assert isinstance(fanout, FanOutCall)
        assert fanout.pattern == "literal"
        assert len(fanout.actor_calls) == 2
        assert fanout.actor_calls[0][0] == "sentiment_analyzer"
        assert fanout.actor_calls[1][0] == "topic_extractor"

    def test_reject_mixed_list_actor_and_nonactor(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["result"] = [
                    sentiment_analyzer(p["text"]),
                    p["text"].upper(),
                ]
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="[Aa]ctor call"):
            parser.parse()

    def test_reject_empty_list_literal(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["result"] = []
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="[Ee]mpty"):
            parser.parse()

    def test_list_literal_preserves_lineno(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["result"] = [
                    agent_a(p["x"]),
                    agent_b(p["y"]),
                ]
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        fanout = ops[0]
        assert isinstance(fanout, FanOutCall)
        assert fanout.lineno == 3


class TestAsyncioGatherFanOut:
    """Test parsing of asyncio.gather fan-out syntax."""

    def test_parse_gather_with_generator(self):
        source = textwrap.dedent("""
            async def flow(p: dict) -> dict:
                p["results"] = await asyncio.gather(*(research_agent(t) for t in p["topics"]))
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 2
        fanout = ops[0]
        assert isinstance(fanout, FanOutCall)
        assert fanout.target_key == "/results"
        assert fanout.pattern == "gather"
        assert len(fanout.actor_calls) == 1
        assert fanout.actor_calls[0][0] == "research_agent"
        assert fanout.actor_calls[0][1] == "t"
        assert fanout.iter_var == "t"
        assert fanout.iterable is not None
        assert contains_with_either_quotes(fanout.iterable, 'p["topics"]')

    def test_parse_gather_with_explicit_args(self):
        source = textwrap.dedent("""
            async def flow(p: dict) -> dict:
                p["results"] = await asyncio.gather(
                    agent_a(p["x"]),
                    agent_b(p["y"]),
                    agent_c(p["z"]),
                )
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 2
        fanout = ops[0]
        assert isinstance(fanout, FanOutCall)
        assert fanout.target_key == "/results"
        assert fanout.pattern == "gather"
        assert len(fanout.actor_calls) == 3
        assert fanout.actor_calls[0][0] == "agent_a"
        assert fanout.actor_calls[1][0] == "agent_b"
        assert fanout.actor_calls[2][0] == "agent_c"
        assert fanout.iter_var is None
        assert fanout.iterable is None

    def test_reject_empty_gather(self):
        source = textwrap.dedent("""
            async def flow(p: dict) -> dict:
                p["results"] = await asyncio.gather()
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="at least one argument"):
            parser.parse()

    def test_gather_preserves_lineno(self):
        source = textwrap.dedent("""
            async def flow(p: dict) -> dict:
                p["results"] = await asyncio.gather(*(agent(t) for t in p["items"]))
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        fanout = ops[0]
        assert isinstance(fanout, FanOutCall)
        assert fanout.lineno == 3


class TestFanOutTargetKey:
    """Test aggregation_key extraction from assignment target."""

    def test_simple_key(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["results"] = [agent(t) for t in p["items"]]
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], FanOutCall)
        assert ops[0].target_key == "/results"

    def test_nested_key(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["output"]["results"] = [agent(t) for t in p["items"]]
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], FanOutCall)
        assert ops[0].target_key == "/output/results"

    def test_target_key_from_list_literal(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["analysis"] = [agent_a(p["x"]), agent_b(p["y"])]
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], FanOutCall)
        assert ops[0].target_key == "/analysis"


class TestNonPayloadSubscriptNotFanOut:
    """Test that list comp/literal on non-payload subscripts stays a Mutation."""

    def test_non_payload_subscript_is_mutation(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                cache = Cache()
                cache["items"] = [agent(t) for t in p["topics"]]
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        from asya_cli.flow.ir import Mutation

        # cache["items"] roots at cache, not p - should be a Mutation
        assert isinstance(ops[0], Mutation)

    def test_nested_payload_subscript_is_fanout(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["config"]["items"] = [agent(t) for t in p["topics"]]
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        # p["config"]["items"] roots at p - IS a fan-out
        assert isinstance(ops[0], FanOutCall)
        assert ops[0].target_key == "/config/items"


class TestFanOutWithOtherOperations:
    """Test fan-out combined with other flow operations."""

    def test_fanout_between_actor_calls(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p = preprocessor(p)
                p["results"] = [agent(t) for t in p["items"]]
                p = postprocessor(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        from asya_cli.flow.ir import ActorCall, Return

        assert len(ops) == 4
        assert isinstance(ops[0], ActorCall)
        assert ops[0].name == "preprocessor"
        assert isinstance(ops[1], FanOutCall)
        assert isinstance(ops[2], ActorCall)
        assert ops[2].name == "postprocessor"
        assert isinstance(ops[3], Return)

    def test_fanout_with_mutations(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["status"] = "processing"
                p["results"] = [agent(t) for t in p["items"]]
                p["status"] = "done"
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        from asya_cli.flow.ir import Mutation, Return

        assert len(ops) == 4
        assert isinstance(ops[0], Mutation)
        assert isinstance(ops[1], FanOutCall)
        assert isinstance(ops[2], Mutation)
        assert isinstance(ops[3], Return)

    def test_fanout_inside_conditional(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                if p["parallel"]:
                    p["results"] = [agent(t) for t in p["items"]]
                else:
                    p = sequential_agent(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        from asya_cli.flow.ir import ActorCall, Condition, Return

        assert len(ops) == 2
        cond = ops[0]
        assert isinstance(cond, Condition)
        assert isinstance(cond.true_branch[0], FanOutCall)
        assert isinstance(cond.false_branch[0], ActorCall)
        assert isinstance(ops[1], Return)

    def test_multiple_sequential_fanouts(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                p["research"] = [research_agent(t) for t in p["topics"]]
                p["reviews"] = [review_agent(r) for r in p["research"]]
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 3
        assert isinstance(ops[0], FanOutCall)
        assert ops[0].target_key == "/research"
        assert isinstance(ops[1], FanOutCall)
        assert ops[1].target_key == "/reviews"


class TestFanOutParameterPreservation:
    """Test that parameter names are preserved in fan-out expressions."""

    def test_state_parameter_preserved_in_comprehension(self):
        source = textwrap.dedent("""
            def flow(state: dict) -> dict:
                state["results"] = [agent(t) for t in state["items"]]
                return state
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        fanout = ops[0]
        assert isinstance(fanout, FanOutCall)
        assert fanout.target_key == "/results"
        assert fanout.iterable is not None
        assert contains_with_either_quotes(fanout.iterable, 'state["items"]')

    def test_payload_parameter_preserved_in_literal(self):
        source = textwrap.dedent("""
            def flow(payload: dict) -> dict:
                payload["result"] = [agent_a(payload["x"]), agent_b(payload["y"])]
                return payload
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        fanout = ops[0]
        assert isinstance(fanout, FanOutCall)
        assert fanout.target_key == "/result"
        assert contains_with_either_quotes(fanout.actor_calls[0][1], 'payload["x"]')
        assert contains_with_either_quotes(fanout.actor_calls[1][1], 'payload["y"]')
