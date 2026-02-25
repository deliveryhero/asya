"""Unit tests for fan-out router code generation."""

from __future__ import annotations

import ast
import textwrap
import uuid

import pytest
from asya_cli.flow.codegen import CodeGenerator
from asya_cli.flow.grouper import OperationGrouper
from asya_cli.flow.ir import ActorCall, FanOutCall, Mutation, Return


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fanout_op(
    target_key: str = "/results",
    pattern: str = "comprehension",
    actor_calls: list[tuple[str, str]] | None = None,
    iter_var: str | None = "t",
    iterable: str | None = 'p["topics"]',
    lineno: int = 5,
) -> FanOutCall:
    if actor_calls is None:
        actor_calls = [("research_agent", "t")]
    return FanOutCall(
        lineno=lineno,
        target_key=target_key,
        pattern=pattern,
        actor_calls=actor_calls,
        iter_var=iter_var,
        iterable=iterable,
    )


def _generate_code_for_ops(flow_name: str, ops: list) -> str:
    grouper = OperationGrouper(flow_name, ops)
    routers = grouper.group()
    codegen = CodeGenerator(flow_name, routers, "test.py")
    return codegen.generate()


def _parse_code(code: str):
    """Compile and return AST tree (raises SyntaxError if invalid)."""
    return ast.parse(code)


def _exec_code(code: str) -> dict:
    """Execute generated code in a fresh namespace and return the namespace dict."""
    ns: dict = {}
    exec(compile(code, "<generated>", "exec"), ns)  # nosec B102
    return ns


def _make_test_message(route_curr: str = "fanout_flow_L5", route_next: list | None = None) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "route": {
            "prev": [],
            "curr": route_curr,
            "next": route_next or [],
        },
        "headers": {},
        "payload": {"topics": ["topic_a", "topic_b", "topic_c"]},
    }


# ---------------------------------------------------------------------------
# Test: Grouper creates fan-out router
# ---------------------------------------------------------------------------


class TestGrouperFanOut:
    def test_fanout_creates_is_fan_out_router(self):
        ops = [
            _make_fanout_op(),
            Return(lineno=6),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        fanout_routers = [r for r in routers if r.is_fan_out]
        assert len(fanout_routers) == 1, f"Expected 1 fan-out router, got {len(fanout_routers)}"

    def test_fanout_router_has_fan_out_op(self):
        fan_out = _make_fanout_op()
        ops = [fan_out, Return(lineno=6)]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        fanout_router = next(r for r in routers if r.is_fan_out)
        assert fanout_router.fan_out_op is fan_out

    def test_fanout_router_name_contains_lineno(self):
        ops = [_make_fanout_op(lineno=42), Return(lineno=43)]
        grouper = OperationGrouper("myflow", ops)
        routers = grouper.group()

        fanout_router = next(r for r in routers if r.is_fan_out)
        assert "L42" in fanout_router.name
        assert "myflow" in fanout_router.name

    def test_fanout_true_branch_actors_is_continuation(self):
        """Fan-out router's true_branch_actors = aggregator + after-aggregator."""
        ops = [
            _make_fanout_op(),
            ActorCall(lineno=6, name="aggregator"),
            Return(lineno=7),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        fanout_router = next(r for r in routers if r.is_fan_out)
        assert "aggregator" in fanout_router.true_branch_actors

    def test_fanout_at_end_of_flow_no_aggregator(self):
        """Fan-out at end of flow: no explicit aggregator, true_branch_actors points to end."""
        ops = [_make_fanout_op(), Return(lineno=6)]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        fanout_router = next(r for r in routers if r.is_fan_out)
        # When no continuation, true_branch_actors points to end_flow
        assert any(a.startswith("end_") for a in fanout_router.true_branch_actors)

    def test_two_sequential_fanouts(self):
        ops = [
            _make_fanout_op(target_key="/research", lineno=3),
            _make_fanout_op(
                target_key="/reviews", lineno=4, actor_calls=[("review_agent", "r")], iterable='p["research"]'
            ),
            Return(lineno=5),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        fanout_routers = [r for r in routers if r.is_fan_out]
        assert len(fanout_routers) == 2

    def test_fanout_with_preceding_mutation(self):
        ops = [
            Mutation(lineno=3, code='p["status"] = "processing"'),
            _make_fanout_op(lineno=4),
            Return(lineno=5),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        fanout_routers = [r for r in routers if r.is_fan_out]
        assert len(fanout_routers) == 1

    def test_fanout_counter_increments_for_multiple_fanouts(self):
        ops = [
            _make_fanout_op(target_key="/a", lineno=3),
            _make_fanout_op(target_key="/b", lineno=4),
            Return(lineno=5),
        ]
        grouper = OperationGrouper("flow", ops)
        grouper.group()
        assert grouper._fanout_counter == 2


# ---------------------------------------------------------------------------
# Test: Code generation validity
# ---------------------------------------------------------------------------


class TestFanOutCodeValidity:
    def test_comprehension_fanout_generates_valid_python(self):
        ops = [_make_fanout_op(pattern="comprehension"), Return(lineno=6)]
        code = _generate_code_for_ops("flow", ops)

        try:
            _parse_code(code)
        except SyntaxError as e:
            pytest.fail(f"Generated code is not valid Python: {e}")

    def test_literal_fanout_generates_valid_python(self):
        ops = [
            FanOutCall(
                lineno=5,
                target_key="/result",
                pattern="literal",
                actor_calls=[
                    ("sentiment_analyzer", 'p["text"]'),
                    ("topic_extractor", 'p["text"]'),
                ],
                iter_var=None,
                iterable=None,
            ),
            Return(lineno=6),
        ]
        code = _generate_code_for_ops("flow", ops)

        try:
            _parse_code(code)
        except SyntaxError as e:
            pytest.fail(f"Generated code is not valid Python: {e}")

    def test_gather_fanout_generates_valid_python(self):
        ops = [
            FanOutCall(
                lineno=5,
                target_key="/results",
                pattern="gather",
                actor_calls=[("research_agent", "t")],
                iter_var="t",
                iterable='p["topics"]',
            ),
            Return(lineno=6),
        ]
        code = _generate_code_for_ops("flow", ops)

        try:
            _parse_code(code)
        except SyntaxError as e:
            pytest.fail(f"Generated code is not valid Python: {e}")

    def test_gather_explicit_fanout_generates_valid_python(self):
        ops = [
            FanOutCall(
                lineno=5,
                target_key="/results",
                pattern="gather",
                actor_calls=[
                    ("agent_a", 'p["x"]'),
                    ("agent_b", 'p["y"]'),
                ],
                iter_var=None,
                iterable=None,
            ),
            Return(lineno=6),
        ]
        code = _generate_code_for_ops("flow", ops)

        try:
            _parse_code(code)
        except SyntaxError as e:
            pytest.fail(f"Generated code is not valid Python: {e}")

    def test_fanout_router_is_generator_function(self):
        """The fan-out function must use `yield` (be a generator)."""
        ops = [_make_fanout_op(), Return(lineno=6)]
        code = _generate_code_for_ops("flow", ops)
        tree = _parse_code(code)

        fanout_funcs = [
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name.startswith("fanout_")
        ]
        assert len(fanout_funcs) == 1, "Expected exactly one fanout_ function"

        # Check it contains yield statements
        yields = [node for node in ast.walk(fanout_funcs[0]) if isinstance(node, ast.Yield | ast.YieldFrom)]
        assert len(yields) >= 2, "Fan-out function should yield at least 2 messages (parent + slices)"

    def test_resolve_aggregator_helper_generated_once(self):
        """_resolve_aggregator should appear exactly once per file even with multiple fan-outs."""
        ops = [
            _make_fanout_op(target_key="/a", lineno=3),
            ActorCall(lineno=4, name="agg1"),
            _make_fanout_op(target_key="/b", lineno=5, actor_calls=[("agent_b", "x")], iterable='p["items"]'),
            ActorCall(lineno=6, name="agg2"),
            Return(lineno=7),
        ]
        code = _generate_code_for_ops("flow", ops)

        # The helper block emits 'import json as _json' exactly once per file.
        # 'def _resolve_aggregator' appears twice (once in if-branch, once in else-branch of
        # the FANIN_SHARDS conditional) — both are part of the single helper block.
        count = code.count("import json as _json")
        assert count == 1, f"Fan-out helper block should be emitted exactly once, found {count} times"

    def test_no_fanout_no_resolve_aggregator(self):
        """Files without fan-out should not contain _resolve_aggregator."""
        ops = [ActorCall(lineno=1, name="handler"), Return(lineno=2)]
        code = _generate_code_for_ops("flow", ops)

        assert "_resolve_aggregator" not in code

    def test_no_fanout_no_json_import(self):
        """Files without fan-out should not import json for fan-out purposes."""
        ops = [ActorCall(lineno=1, name="handler"), Return(lineno=2)]
        code = _generate_code_for_ops("flow", ops)

        # The resolve function at module level doesn't import json either
        # _json is the fan-out specific alias
        assert "_json" not in code

    def test_fanout_imports_json(self):
        """Files with fan-out should import json (as _json)."""
        ops = [_make_fanout_op(), Return(lineno=6)]
        code = _generate_code_for_ops("flow", ops)

        assert "_json" in code

    def test_fanout_sub_agents_in_all_handlers(self):
        """Sub-agent names from fan_out_op.actor_calls must be in all_handlers."""
        ops = [
            FanOutCall(
                lineno=5,
                target_key="/result",
                pattern="literal",
                actor_calls=[("sentiment_analyzer", 'p["text"]'), ("topic_extractor", 'p["text"]')],
                iter_var=None,
                iterable=None,
            ),
            Return(lineno=6),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()
        codegen = CodeGenerator("flow", routers, "test.py")
        codegen._collect_handlers()

        assert "sentiment_analyzer" in codegen.all_handlers
        assert "topic_extractor" in codegen.all_handlers


# ---------------------------------------------------------------------------
# Test: Generated code structure
# ---------------------------------------------------------------------------


class TestFanOutCodeStructure:
    def test_comprehension_uses_for_loop(self):
        ops = [
            FanOutCall(
                lineno=5,
                target_key="/results",
                pattern="comprehension",
                actor_calls=[("research_agent", "t")],
                iter_var="t",
                iterable='p["topics"]',
            ),
            Return(lineno=6),
        ]
        code = _generate_code_for_ops("flow", ops)

        # The generated code should have a for loop over the iterable
        assert 'for t in p["topics"]' in code or "for t in p['topics']" in code

    def test_literal_pattern_no_for_loop(self):
        ops = [
            FanOutCall(
                lineno=5,
                target_key="/result",
                pattern="literal",
                actor_calls=[("agent_a", 'p["x"]'), ("agent_b", 'p["y"]')],
                iter_var=None,
                iterable=None,
            ),
            Return(lineno=6),
        ]
        code = _generate_code_for_ops("flow", ops)

        # Find the fanout function
        tree = _parse_code(code)
        fanout_funcs = [
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name.startswith("fanout_")
        ]
        assert len(fanout_funcs) == 1

        # Check no for loops inside (only enumerate is OK)
        for_nodes = [
            node
            for node in ast.walk(fanout_funcs[0])
            if isinstance(node, ast.For)
            and not (
                # allow the `for _i, (_actor, _payload) in enumerate(...)` loop
                isinstance(node.iter, ast.Call)
                and isinstance(node.iter.func, ast.Name)
                and node.iter.func.id == "enumerate"
            )
        ]
        assert len(for_nodes) == 0, "Literal pattern should not use for loop to build slices"

    def test_fan_in_header_contains_target_key(self):
        ops = [_make_fanout_op(target_key="/my_results"), Return(lineno=6)]
        code = _generate_code_for_ops("flow", ops)

        assert "/my_results" in code

    def test_slice_count_field_in_generated_code(self):
        ops = [_make_fanout_op(), Return(lineno=6)]
        code = _generate_code_for_ops("flow", ops)

        assert "slice_count" in code

    def test_slice_index_field_in_generated_code(self):
        ops = [_make_fanout_op(), Return(lineno=6)]
        code = _generate_code_for_ops("flow", ops)

        assert "slice_index" in code

    def test_origin_id_field_in_generated_code(self):
        ops = [_make_fanout_op(), Return(lineno=6)]
        code = _generate_code_for_ops("flow", ops)

        assert "origin_id" in code

    def test_x_asya_fan_in_header_name(self):
        ops = [_make_fanout_op(), Return(lineno=6)]
        code = _generate_code_for_ops("flow", ops)

        assert "x-asya-fan-in" in code

    def test_parent_id_field_for_slices(self):
        """Sub-agent slices should have parent_id set to origin_id."""
        ops = [_make_fanout_op(), Return(lineno=6)]
        code = _generate_code_for_ops("flow", ops)

        assert "parent_id" in code

    def test_route_manually_shifted_for_index0(self):
        """Parent message (index 0) must manually shift route: prev+[curr], curr=aggregator."""
        ops = [
            _make_fanout_op(),
            ActorCall(lineno=6, name="aggregator"),
            Return(lineno=7),
        ]
        code = _generate_code_for_ops("flow", ops)

        # The generated code must have manual route shifting for index 0
        assert "r['prev'] + [r['curr']]" in code or 'r["prev"] + [r["curr"]]' in code

    def test_slices_have_fresh_route_starting_from_empty_prev(self):
        """Sub-agent slices get fresh routes with empty prev."""
        ops = [_make_fanout_op(), ActorCall(lineno=6, name="aggregator"), Return(lineno=7)]
        code = _generate_code_for_ops("flow", ops)

        # Slice routes should have empty prev
        assert "'prev': []" in code or '"prev": []' in code


# ---------------------------------------------------------------------------
# Test: Generated code execution
# ---------------------------------------------------------------------------


class TestFanOutCodeExecution:
    """Execute the generated code (with mocked resolve) and verify yielded messages."""

    def _setup_ns_with_mock_resolve(self, code: str, actor_map: dict[str, str]) -> dict:
        """Exec the code with env vars set for resolve()."""
        import os

        # Set up env vars for all actors
        env_backup = {}
        for actor_name, _queue_name in actor_map.items():
            env_key = f"ASYA_HANDLER_{actor_name.upper().replace('-', '_')}"
            env_backup[env_key] = os.environ.get(env_key)
            os.environ[env_key] = actor_name  # handler name = actor name for simplicity

        try:
            ns = _exec_code(code)
        finally:
            for env_key, original_val in env_backup.items():
                if original_val is None:
                    os.environ.pop(env_key, None)
                else:
                    os.environ[env_key] = original_val

        return ns

    def test_comprehension_fanout_yields_n_plus_1_messages(self):
        """With 3 topics, fan-out should yield 4 messages (1 parent + 3 slices)."""
        ops = [
            FanOutCall(
                lineno=5,
                target_key="/results",
                pattern="comprehension",
                actor_calls=[("research_agent", "t")],
                iter_var="t",
                iterable='p["topics"]',
            ),
            ActorCall(lineno=6, name="aggregator"),
            Return(lineno=7),
        ]
        code = _generate_code_for_ops("flow", ops)

        ns = self._setup_ns_with_mock_resolve(
            code,
            {
                "research_agent": "research-agent",
                "aggregator": "aggregator",
                "fanout_flow_L5": "fanout-flow-l5",
            },
        )

        # Find the fanout function
        fanout_fn_name = next(k for k in ns if k.startswith("fanout_"))
        fanout_fn = ns[fanout_fn_name]

        msg = {
            "id": "test-msg-id",
            "route": {"prev": [], "curr": "fanout-flow-l5", "next": []},
            "headers": {},
            "payload": {"topics": ["a", "b", "c"]},
        }

        messages = list(fanout_fn(msg))
        assert len(messages) == 4, f"Expected 4 messages (1+3 topics), got {len(messages)}"

    def test_literal_fanout_yields_n_plus_1_messages(self):
        """Literal fan-out with 2 actors should yield 3 messages (1 parent + 2 slices)."""
        ops = [
            FanOutCall(
                lineno=5,
                target_key="/result",
                pattern="literal",
                actor_calls=[("sentiment_analyzer", 'p["text"]'), ("topic_extractor", 'p["text"]')],
                iter_var=None,
                iterable=None,
            ),
            ActorCall(lineno=6, name="aggregator"),
            Return(lineno=7),
        ]
        code = _generate_code_for_ops("flow", ops)

        ns = self._setup_ns_with_mock_resolve(
            code,
            {
                "sentiment_analyzer": "sentiment-analyzer",
                "topic_extractor": "topic-extractor",
                "aggregator": "aggregator",
                "fanout_flow_L5": "fanout-flow-l5",
            },
        )

        fanout_fn_name = next(k for k in ns if k.startswith("fanout_"))
        fanout_fn = ns[fanout_fn_name]

        msg = {
            "id": "test-msg-id",
            "route": {"prev": [], "curr": "fanout-flow-l5", "next": []},
            "headers": {},
            "payload": {"text": "hello world"},
        }

        messages = list(fanout_fn(msg))
        assert len(messages) == 3, f"Expected 3 messages (1+2 actors), got {len(messages)}"

    def test_parent_message_has_slice_index_0(self):
        ops = [
            _make_fanout_op(),
            ActorCall(lineno=6, name="aggregator"),
            Return(lineno=7),
        ]
        code = _generate_code_for_ops("flow", ops)

        ns = self._setup_ns_with_mock_resolve(
            code,
            {
                "research_agent": "research-agent",
                "aggregator": "aggregator",
                "fanout_flow_L5": "fanout-flow-l5",
            },
        )

        fanout_fn_name = next(k for k in ns if k.startswith("fanout_"))
        msg = {
            "id": "orig-id",
            "route": {"prev": [], "curr": "fanout-flow-l5", "next": []},
            "headers": {},
            "payload": {"topics": ["x"]},
        }

        messages = list(ns[fanout_fn_name](msg))
        parent = messages[0]
        assert parent["headers"]["x-asya-fan-in"]["slice_index"] == 0

    def test_slice_messages_have_increasing_slice_indices(self):
        ops = [
            _make_fanout_op(),
            ActorCall(lineno=6, name="aggregator"),
            Return(lineno=7),
        ]
        code = _generate_code_for_ops("flow", ops)

        ns = self._setup_ns_with_mock_resolve(
            code,
            {
                "research_agent": "research-agent",
                "aggregator": "aggregator",
                "fanout_flow_L5": "fanout-flow-l5",
            },
        )

        fanout_fn_name = next(k for k in ns if k.startswith("fanout_"))
        msg = {
            "id": "orig-id",
            "route": {"prev": [], "curr": "fanout-flow-l5", "next": []},
            "headers": {},
            "payload": {"topics": ["a", "b"]},
        }

        messages = list(ns[fanout_fn_name](msg))
        indices = [m["headers"]["x-asya-fan-in"]["slice_index"] for m in messages]
        assert indices == [0, 1, 2]

    def test_parent_message_route_manually_shifted(self):
        """Index 0 message must have prev+[curr], curr=aggregator, next=[]."""
        ops = [
            _make_fanout_op(),
            ActorCall(lineno=6, name="aggregator"),
            Return(lineno=7),
        ]
        code = _generate_code_for_ops("flow", ops)

        ns = self._setup_ns_with_mock_resolve(
            code,
            {
                "research_agent": "research-agent",
                "aggregator": "aggregator",
                "fanout_flow_L5": "fanout-flow-l5",
            },
        )

        fanout_fn_name = next(k for k in ns if k.startswith("fanout_"))
        msg = {
            "id": "orig-id",
            "route": {"prev": ["start-flow"], "curr": "fanout-flow-l5", "next": ["downstream"]},
            "headers": {},
            "payload": {"topics": ["x"]},
        }

        messages = list(ns[fanout_fn_name](msg))
        parent_route = messages[0]["route"]

        assert "start-flow" in parent_route["prev"]
        assert "fanout-flow-l5" in parent_route["prev"]
        assert parent_route["curr"] == "aggregator"
        assert "downstream" in parent_route["next"]

    def test_slice_messages_have_fresh_routes(self):
        """Slice messages (indices 1+) should have empty prev and fresh curr/next."""
        ops = [
            _make_fanout_op(),
            ActorCall(lineno=6, name="aggregator"),
            Return(lineno=7),
        ]
        code = _generate_code_for_ops("flow", ops)

        ns = self._setup_ns_with_mock_resolve(
            code,
            {
                "research_agent": "research-agent",
                "aggregator": "aggregator",
                "fanout_flow_L5": "fanout-flow-l5",
            },
        )

        fanout_fn_name = next(k for k in ns if k.startswith("fanout_"))
        msg = {
            "id": "orig-id",
            "route": {"prev": ["before"], "curr": "fanout-flow-l5", "next": []},
            "headers": {},
            "payload": {"topics": ["a"]},
        }

        messages = list(ns[fanout_fn_name](msg))
        slice_msg = messages[1]  # First sub-agent slice

        assert slice_msg["route"]["prev"] == []
        assert slice_msg["route"]["curr"] == "research-agent"
        assert slice_msg["route"]["next"] == ["aggregator"]

    def test_fan_in_header_slice_count_equals_n_plus_1(self):
        """x-asya-fan-in.slice_count should be total number of messages."""
        ops = [
            _make_fanout_op(),
            ActorCall(lineno=6, name="aggregator"),
            Return(lineno=7),
        ]
        code = _generate_code_for_ops("flow", ops)

        ns = self._setup_ns_with_mock_resolve(
            code,
            {
                "research_agent": "research-agent",
                "aggregator": "aggregator",
                "fanout_flow_L5": "fanout-flow-l5",
            },
        )

        fanout_fn_name = next(k for k in ns if k.startswith("fanout_"))
        msg = {
            "id": "orig-id",
            "route": {"prev": [], "curr": "fanout-flow-l5", "next": []},
            "headers": {},
            "payload": {"topics": ["a", "b", "c"]},  # 3 topics
        }

        messages = list(ns[fanout_fn_name](msg))
        # All messages should agree on slice_count
        slice_counts = {m["headers"]["x-asya-fan-in"]["slice_count"] for m in messages}
        assert slice_counts == {4}  # 1 parent + 3 slices

    def test_fan_in_header_aggregation_key(self):
        ops = [
            _make_fanout_op(target_key="/results"),
            ActorCall(lineno=6, name="aggregator"),
            Return(lineno=7),
        ]
        code = _generate_code_for_ops("flow", ops)

        ns = self._setup_ns_with_mock_resolve(
            code,
            {
                "research_agent": "research-agent",
                "aggregator": "aggregator",
                "fanout_flow_L5": "fanout-flow-l5",
            },
        )

        fanout_fn_name = next(k for k in ns if k.startswith("fanout_"))
        msg = {
            "id": "orig-id",
            "route": {"prev": [], "curr": "fanout-flow-l5", "next": []},
            "headers": {},
            "payload": {"topics": ["a"]},
        }

        messages = list(ns[fanout_fn_name](msg))
        for m in messages:
            assert m["headers"]["x-asya-fan-in"]["aggregation_key"] == "/results"

    def test_parent_id_set_on_slices(self):
        """Sub-agent slice messages should have parent_id = origin message id."""
        ops = [
            _make_fanout_op(),
            ActorCall(lineno=6, name="aggregator"),
            Return(lineno=7),
        ]
        code = _generate_code_for_ops("flow", ops)

        ns = self._setup_ns_with_mock_resolve(
            code,
            {
                "research_agent": "research-agent",
                "aggregator": "aggregator",
                "fanout_flow_L5": "fanout-flow-l5",
            },
        )

        fanout_fn_name = next(k for k in ns if k.startswith("fanout_"))
        origin_id = "my-origin-id-123"
        msg = {
            "id": origin_id,
            "route": {"prev": [], "curr": "fanout-flow-l5", "next": []},
            "headers": {},
            "payload": {"topics": ["a"]},
        }

        messages = list(ns[fanout_fn_name](msg))
        # Slices (index 1+) should have parent_id = origin_id
        for slice_msg in messages[1:]:
            assert slice_msg.get("parent_id") == origin_id

    def test_parent_message_preserves_existing_headers(self):
        """Existing headers on incoming message should be preserved in all yielded messages."""
        ops = [
            _make_fanout_op(),
            ActorCall(lineno=6, name="aggregator"),
            Return(lineno=7),
        ]
        code = _generate_code_for_ops("flow", ops)

        ns = self._setup_ns_with_mock_resolve(
            code,
            {
                "research_agent": "research-agent",
                "aggregator": "aggregator",
                "fanout_flow_L5": "fanout-flow-l5",
            },
        )

        fanout_fn_name = next(k for k in ns if k.startswith("fanout_"))
        msg = {
            "id": "orig-id",
            "route": {"prev": [], "curr": "fanout-flow-l5", "next": []},
            "headers": {"trace_id": "abc123", "priority": "high"},
            "payload": {"topics": ["a"]},
        }

        messages = list(ns[fanout_fn_name](msg))
        for m in messages:
            assert m["headers"].get("trace_id") == "abc123"
            assert m["headers"].get("priority") == "high"


# ---------------------------------------------------------------------------
# Test: Integration via compiler
# ---------------------------------------------------------------------------


class TestFanOutIntegration:
    """Test fan-out via the FlowParser + OperationGrouper + CodeGenerator pipeline."""

    def _compile_flow(self, source: str) -> str:
        from asya_cli.flow.parser import FlowParser

        source = textwrap.dedent(source)
        parser = FlowParser(source, "test.py")
        flow_name, ops = parser.parse()
        code = _generate_code_for_ops(flow_name, ops)
        return code

    def test_comprehension_flow_compiles_to_valid_python(self):
        code = self._compile_flow("""
            def flow(p: dict) -> dict:
                p["results"] = [research_agent(t) for t in p["topics"]]
                return p
        """)
        try:
            _parse_code(code)
        except SyntaxError as e:
            pytest.fail(f"Compilation failed: {e}")

    def test_literal_flow_compiles_to_valid_python(self):
        code = self._compile_flow("""
            def flow(p: dict) -> dict:
                p["result"] = [
                    sentiment_analyzer(p["text"]),
                    topic_extractor(p["text"]),
                ]
                return p
        """)
        try:
            _parse_code(code)
        except SyntaxError as e:
            pytest.fail(f"Compilation failed: {e}")

    def test_gather_flow_compiles_to_valid_python(self):
        code = self._compile_flow("""
            async def flow(p: dict) -> dict:
                p["results"] = await asyncio.gather(*(research_agent(t) for t in p["topics"]))
                return p
        """)
        try:
            _parse_code(code)
        except SyntaxError as e:
            pytest.fail(f"Compilation failed: {e}")

    def test_fanout_between_actors_compiles(self):
        code = self._compile_flow("""
            def flow(p: dict) -> dict:
                p = preprocessor(p)
                p["results"] = [agent(t) for t in p["items"]]
                p = postprocessor(p)
                return p
        """)
        try:
            _parse_code(code)
        except SyntaxError as e:
            pytest.fail(f"Compilation failed: {e}")

    def test_fanout_contains_resolve_aggregator(self):
        code = self._compile_flow("""
            def flow(p: dict) -> dict:
                p["results"] = [research_agent(t) for t in p["topics"]]
                return p
        """)
        assert "_resolve_aggregator" in code

    def test_two_fanouts_share_one_resolve_aggregator(self):
        code = self._compile_flow("""
            def flow(p: dict) -> dict:
                p["research"] = [research_agent(t) for t in p["topics"]]
                p["reviews"] = [review_agent(r) for r in p["research"]]
                return p
        """)
        # The fan-out helper block is emitted once per file. Check via the json import marker.
        assert code.count("import json as _json") == 1, "Fan-out helper block emitted more than once"
