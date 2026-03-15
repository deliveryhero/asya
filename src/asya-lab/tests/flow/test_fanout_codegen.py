"""Unit tests for fan-out router code generation."""

from __future__ import annotations

import ast
import copy
import os
import re
import textwrap
from typing import Any

import pytest
from asya_lab.flow.codegen import CodeGenerator
from asya_lab.flow.grouper import OperationGrouper
from asya_lab.flow.ir import ActorCall, FanOutCall, Mutation, Return


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


def _resolve_path(data: dict, path: str) -> Any:
    """Resolve a dotted path on a nested dict. Leading dot is stripped."""
    parts = path.lstrip(".").split(".")
    cur: Any = data
    for p in parts:
        cur = cur[p]
    return cur


def _set_path(data: dict, path: str, value: Any) -> None:
    """Set a value at a dotted path on a nested dict. Leading dot is stripped."""
    parts = path.lstrip(".").split(".")
    cur = data
    last = parts[-1]
    for p in parts[:-1]:
        if p not in cur:
            cur[p] = {}
        cur = cur[p]
    m = re.match(r"^(\w+)\[(-?\d*):(-?\d*)\]$", last)
    if m:
        key = m.group(1)
        start = int(m.group(2)) if m.group(2) else None
        stop = int(m.group(3)) if m.group(3) else None
        cur[key][start:stop] = value
    else:
        cur[last] = value


def _del_path(data: dict, path: str) -> None:
    """Delete a value at a dotted path on a nested dict. Leading dot is stripped."""
    parts = path.lstrip(".").split(".")
    cur = data
    for p in parts[:-1]:
        cur = cur[p]
    del cur[parts[-1]]


class AbiFrame:
    """Represents one output frame collected from an ABI generator."""

    def __init__(self, payload: Any, route_next: list[str], headers: dict[str, Any]):
        self.payload = payload
        self.route_next = list(route_next)
        self.headers = copy.deepcopy(headers)


async def _drive_abi_generator_async(gen, msg_ctx: dict) -> list[AbiFrame]:
    """Drive an async ABI generator, dispatching GET/SET/DEL operations on msg_ctx."""
    frames: list[AbiFrame] = []
    value = None
    try:
        value = await gen.asend(None)
        while True:
            if (
                isinstance(value, tuple)
                and len(value) >= 2
                and isinstance(value[0], str)
                and value[0] in ("GET", "SET", "DEL")
            ):
                op = value[0]
                if op == "GET":
                    result = _resolve_path(msg_ctx, value[1])
                    value = await gen.asend(result)
                elif op == "SET":
                    _set_path(msg_ctx, value[1], value[2])
                    value = await gen.asend(None)
                elif op == "DEL":
                    _del_path(msg_ctx, value[1])
                    value = await gen.asend(None)
            else:
                frames.append(
                    AbiFrame(
                        payload=value,
                        route_next=msg_ctx.get("route", {}).get("next", []),
                        headers=msg_ctx.get("headers", {}),
                    )
                )
                value = await gen.asend(None)
    except StopAsyncIteration:
        pass
    return frames


def _drive_abi_generator(gen, msg_ctx: dict) -> list[AbiFrame]:
    """Drive an ABI generator (sync or async), dispatching GET/SET/DEL operations on msg_ctx.

    msg_ctx is a dict like:
        {"id": "...", "route": {"prev": [...], "next": [...]}, "headers": {...}, "status": {...}}

    Each yielded value is either:
    - ("GET", path) -> respond with resolved value
    - ("SET", path, value) -> set value, respond with None
    - ("DEL", path) -> delete value, respond with None
    - anything else -> a payload frame, snapshot state as AbiFrame
    """
    import asyncio
    import inspect

    if inspect.isasyncgen(gen):
        return asyncio.run(_drive_abi_generator_async(gen, msg_ctx))
    frames: list[AbiFrame] = []
    value = None
    try:
        value = gen.send(None)
        while True:
            if (
                isinstance(value, tuple)
                and len(value) >= 2
                and isinstance(value[0], str)
                and value[0] in ("GET", "SET", "DEL")
            ):
                op = value[0]
                if op == "GET":
                    result = _resolve_path(msg_ctx, value[1])
                    value = gen.send(result)
                elif op == "SET":
                    _set_path(msg_ctx, value[1], value[2])
                    value = gen.send(None)
                elif op == "DEL":
                    _del_path(msg_ctx, value[1])
                    value = gen.send(None)
            else:
                # Payload frame
                frames.append(
                    AbiFrame(
                        payload=value,
                        route_next=msg_ctx.get("route", {}).get("next", []),
                        headers=msg_ctx.get("headers", {}),
                    )
                )
                value = gen.send(None)
    except StopIteration:
        pass
    return frames


def _make_msg_ctx(
    msg_id: str = "test-msg-id",
    route_next: list[str] | None = None,
    route_prev: list[str] | None = None,
    headers: dict[str, Any] | None = None,
    status: dict[str, Any] | None = None,
) -> dict:
    """Create a message context dict for ABI-based tests."""
    ctx: dict[str, Any] = {
        "id": msg_id,
        "route": {
            "prev": route_prev or [],
            "next": route_next or [],
        },
        "headers": headers or {},
    }
    if status is not None:
        ctx["status"] = status
    return ctx


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
        assert "line_42" in fanout_router.name
        assert "myflow" in fanout_router.name

    def test_fanout_true_branch_actors_is_continuation(self):
        """Fan-out router's true_branch_actors = generated fan-in + user actors."""
        ops = [
            _make_fanout_op(),
            ActorCall(lineno=6, name="formatter"),
            Return(lineno=7),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        fanout_router = next(r for r in routers if r.is_fan_out)
        assert "formatter" in fanout_router.true_branch_actors
        assert any(a.startswith("fanin_") for a in fanout_router.true_branch_actors)

    def test_fanout_at_end_of_flow_no_fanin(self):
        """Fan-out at end of flow: generated fan-in present, plus end actors."""
        ops = [_make_fanout_op(), Return(lineno=6)]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        fanout_router = next(r for r in routers if r.is_fan_out)
        # When no explicit continuation, true_branch_actors has generated fan-in and end_flow
        assert any(a.startswith("fanin_") for a in fanout_router.true_branch_actors)
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
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("fanout_")
        ]
        assert len(fanout_funcs) == 1, "Expected exactly one fanout_ function"

        # Check it contains yield statements
        yields = [node for node in ast.walk(fanout_funcs[0]) if isinstance(node, ast.Yield | ast.YieldFrom)]
        assert len(yields) >= 2, "Fan-out function should yield at least 2 messages (parent + slices)"

    def test_fanout_copy_import_generated_once(self):
        """import copy should appear exactly once per file even with multiple fan-outs."""
        ops = [
            _make_fanout_op(target_key="/a", lineno=3),
            ActorCall(lineno=4, name="formatter1"),
            _make_fanout_op(target_key="/b", lineno=5, actor_calls=[("agent_b", "x")], iterable='p["items"]'),
            ActorCall(lineno=6, name="formatter2"),
            Return(lineno=7),
        ]
        code = _generate_code_for_ops("flow", ops)

        count = code.count("import copy")
        assert count == 1, f"copy import should be emitted exactly once, found {count} times"

    def test_fanout_no_resolve_fanin(self):
        """Files with fan-out should not contain _resolve_fanin (removed helper)."""
        ops = [_make_fanout_op(), Return(lineno=6)]
        code = _generate_code_for_ops("flow", ops)

        assert "_resolve_fanin" not in code

    def test_no_fanout_no_copy_import(self):
        """Files without fan-out should not import copy."""
        ops = [ActorCall(lineno=1, name="handler"), Return(lineno=2)]
        code = _generate_code_for_ops("flow", ops)

        assert "import copy" not in code

    def test_fanout_imports_copy(self):
        """Files with fan-out should import copy."""
        ops = [_make_fanout_op(), Return(lineno=6)]
        code = _generate_code_for_ops("flow", ops)

        assert "import copy" in code

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
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("fanout_")
        ]
        assert len(fanout_funcs) == 1

        # Check no for loops that build _slices (enumerate and method calls like .items() are OK)
        for_nodes = [
            node
            for node in ast.walk(fanout_funcs[0])
            if isinstance(node, ast.For)
            and not (
                isinstance(node.iter, ast.Call)
                and (
                    (isinstance(node.iter.func, ast.Name) and node.iter.func.id == "enumerate")
                    or isinstance(node.iter.func, ast.Attribute)
                )
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

    def test_fanout_reads_id_via_abi(self):
        """Fan-out router reads message ID via ABI GET."""
        ops = [_make_fanout_op(), Return(lineno=6)]
        code = _generate_code_for_ops("flow", ops)

        assert 'yield "GET", ".id"' in code

    def test_fanout_reads_route_next_via_abi(self):
        """Fan-out router reads route/next via ABI GET."""
        ops = [_make_fanout_op(), Return(lineno=6)]
        code = _generate_code_for_ops("flow", ops)

        assert 'yield "GET", ".route.next"' in code

    def test_fanout_writes_headers_via_abi(self):
        """Fan-out router writes headers via ABI SET."""
        ops = [_make_fanout_op(), Return(lineno=6)]
        code = _generate_code_for_ops("flow", ops)

        assert 'yield "SET", ".headers.x-asya-fan-in"' in code


# ---------------------------------------------------------------------------
# Test: Generated code execution (VFS-based)
# ---------------------------------------------------------------------------


class TestFanOutCodeExecution:
    """Execute the generated code with ABI driver and verify yielded payloads + message state."""

    def _setup_and_exec(self, code: str, actor_map: dict[str, str]) -> dict:
        """Exec the code with env vars set for resolve()."""
        env_backup = {}
        for actor_name, _queue_name in actor_map.items():
            env_key = f"ASYA_HANDLER_{actor_name.upper().replace('-', '_')}"
            env_backup[env_key] = os.environ.get(env_key)
            os.environ[env_key] = actor_name

        try:
            ns = _exec_code(code)
        finally:
            for env_key, original_val in env_backup.items():
                if original_val is None:
                    os.environ.pop(env_key, None)
                else:
                    os.environ[env_key] = original_val

        return ns

    def _get_fanout_fn(self, ns: dict):
        """Find the fanout function in the executed namespace."""
        fanout_fn_name = next(k for k in ns if k.startswith("fanout_"))
        return ns[fanout_fn_name]

    def test_comprehension_fanout_yields_n_plus_1_payloads(self):
        """With 3 topics, fan-out should yield 4 payloads (1 parent + 3 slices)."""
        ops = [
            FanOutCall(
                lineno=5,
                target_key="/results",
                pattern="comprehension",
                actor_calls=[("research_agent", "t")],
                iter_var="t",
                iterable='p["topics"]',
            ),
            ActorCall(lineno=6, name="formatter"),
            Return(lineno=7),
        ]
        code = _generate_code_for_ops("flow", ops)
        actor_map = {
            "research_agent": "research-agent",
            "formatter": "formatter",
            "fanin_flow_line_5": "fanin-flow-line-5",
            "fanout_flow_line_5": "fanout-flow-line-5",
        }

        ns = self._setup_and_exec(code, actor_map)
        fanout_fn = self._get_fanout_fn(ns)
        msg_ctx = _make_msg_ctx("test-msg-id", route_next=[])
        frames = _drive_abi_generator(fanout_fn({"topics": ["a", "b", "c"]}), msg_ctx)

        assert len(frames) == 4, f"Expected 4 frames (1+3 topics), got {len(frames)}"

    def test_literal_fanout_yields_n_plus_1_payloads(self):
        """Literal fan-out with 2 actors should yield 3 payloads (1 parent + 2 slices)."""
        ops = [
            FanOutCall(
                lineno=5,
                target_key="/result",
                pattern="literal",
                actor_calls=[("sentiment_analyzer", 'p["text"]'), ("topic_extractor", 'p["text"]')],
                iter_var=None,
                iterable=None,
            ),
            ActorCall(lineno=6, name="formatter"),
            Return(lineno=7),
        ]
        code = _generate_code_for_ops("flow", ops)
        actor_map = {
            "sentiment_analyzer": "sentiment-analyzer",
            "topic_extractor": "topic-extractor",
            "formatter": "formatter",
            "fanin_flow_line_5": "fanin-flow-line-5",
            "fanout_flow_line_5": "fanout-flow-line-5",
        }

        ns = self._setup_and_exec(code, actor_map)
        fanout_fn = self._get_fanout_fn(ns)
        msg_ctx = _make_msg_ctx("test-msg-id", route_next=[])
        frames = _drive_abi_generator(fanout_fn({"text": "hello world"}), msg_ctx)

        assert len(frames) == 3, f"Expected 3 frames (1+2 actors), got {len(frames)}"

    def test_parent_payload_is_deep_copy_of_input(self):
        """Index 0 yield should be a deep copy of the input payload."""
        ops = [_make_fanout_op(), ActorCall(lineno=6, name="formatter"), Return(lineno=7)]
        code = _generate_code_for_ops("flow", ops)
        actor_map = {
            "research_agent": "research-agent",
            "formatter": "formatter",
            "fanin_flow_line_5": "fanin-flow-line-5",
            "fanout_flow_line_5": "fanout-flow-line-5",
        }

        input_payload = {"topics": ["x"]}
        ns = self._setup_and_exec(code, actor_map)
        fanout_fn = self._get_fanout_fn(ns)
        msg_ctx = _make_msg_ctx("orig-id", route_next=[])
        frames = _drive_abi_generator(fanout_fn(input_payload), msg_ctx)

        assert frames[0].payload == input_payload
        assert frames[0].payload is not input_payload

    def test_parent_route_points_to_fanin(self):
        """After yielding index 0, route/next should point to the generated fan-in."""
        ops = [_make_fanout_op(), ActorCall(lineno=6, name="formatter"), Return(lineno=7)]
        code = _generate_code_for_ops("flow", ops)
        actor_map = {
            "research_agent": "research-agent",
            "formatter": "formatter",
            "fanin_flow_line_5": "fanin-flow-line-5",
            "fanout_flow_line_5": "fanout-flow-line-5",
        }

        ns = self._setup_and_exec(code, actor_map)
        fanout_fn = self._get_fanout_fn(ns)
        msg_ctx = _make_msg_ctx("orig-id", route_next=["downstream"])
        frames = _drive_abi_generator(fanout_fn({"topics": ["x"]}), msg_ctx)

        route_next = frames[0].route_next
        assert route_next[0] == "fanin-flow-line-5"
        assert "downstream" in route_next

    def test_parent_fan_in_header_slice_index_0(self):
        """After yielding index 0, x-asya-fan-in header should have slice_index=0."""
        ops = [_make_fanout_op(), ActorCall(lineno=6, name="formatter"), Return(lineno=7)]
        code = _generate_code_for_ops("flow", ops)
        actor_map = {
            "research_agent": "research-agent",
            "formatter": "formatter",
            "fanin_flow_line_5": "fanin-flow-line-5",
            "fanout_flow_line_5": "fanout-flow-line-5",
        }

        ns = self._setup_and_exec(code, actor_map)
        fanout_fn = self._get_fanout_fn(ns)
        msg_ctx = _make_msg_ctx("orig-id", route_next=[])
        frames = _drive_abi_generator(fanout_fn({"topics": ["x"]}), msg_ctx)

        fan_in = frames[0].headers.get("x-asya-fan-in")
        assert isinstance(fan_in, dict)
        assert fan_in["slice_index"] == 0

    def test_slice_route_points_to_actor_then_fanin(self):
        """After yielding a slice, route/next should be [sub_agent, generated_fanin]."""
        ops = [_make_fanout_op(), ActorCall(lineno=6, name="formatter"), Return(lineno=7)]
        code = _generate_code_for_ops("flow", ops)
        actor_map = {
            "research_agent": "research-agent",
            "formatter": "formatter",
            "fanin_flow_line_5": "fanin-flow-line-5",
            "fanout_flow_line_5": "fanout-flow-line-5",
        }

        ns = self._setup_and_exec(code, actor_map)
        fanout_fn = self._get_fanout_fn(ns)
        msg_ctx = _make_msg_ctx("orig-id", route_next=[])
        frames = _drive_abi_generator(fanout_fn({"topics": ["a"]}), msg_ctx)

        assert frames[1].route_next == ["research-agent", "fanin-flow-line-5"]

    def test_slice_fan_in_header_increasing_indices(self):
        """Slice yields should have increasing slice_index."""
        ops = [_make_fanout_op(), ActorCall(lineno=6, name="formatter"), Return(lineno=7)]
        code = _generate_code_for_ops("flow", ops)
        actor_map = {
            "research_agent": "research-agent",
            "formatter": "formatter",
            "fanin_flow_line_5": "fanin-flow-line-5",
            "fanout_flow_line_5": "fanout-flow-line-5",
        }

        ns = self._setup_and_exec(code, actor_map)
        fanout_fn = self._get_fanout_fn(ns)
        msg_ctx = _make_msg_ctx("orig-id", route_next=[])
        frames = _drive_abi_generator(fanout_fn({"topics": ["a", "b"]}), msg_ctx)

        indices = [f.headers["x-asya-fan-in"]["slice_index"] for f in frames]
        assert indices == [0, 1, 2]

    def test_fan_in_header_slice_count_equals_n_plus_1(self):
        """x-asya-fan-in.slice_count should be total number of yields."""
        ops = [_make_fanout_op(), ActorCall(lineno=6, name="formatter"), Return(lineno=7)]
        code = _generate_code_for_ops("flow", ops)
        actor_map = {
            "research_agent": "research-agent",
            "formatter": "formatter",
            "fanin_flow_line_5": "fanin-flow-line-5",
            "fanout_flow_line_5": "fanout-flow-line-5",
        }

        ns = self._setup_and_exec(code, actor_map)
        fanout_fn = self._get_fanout_fn(ns)
        msg_ctx = _make_msg_ctx("orig-id", route_next=[])
        frames = _drive_abi_generator(fanout_fn({"topics": ["a", "b", "c"]}), msg_ctx)

        slice_counts = {f.headers["x-asya-fan-in"]["slice_count"] for f in frames}
        assert slice_counts == {4}  # 1 parent + 3 slices

    def test_fan_in_header_aggregation_key(self):
        ops = [_make_fanout_op(target_key="/results"), ActorCall(lineno=6, name="formatter"), Return(lineno=7)]
        code = _generate_code_for_ops("flow", ops)
        actor_map = {
            "research_agent": "research-agent",
            "formatter": "formatter",
            "fanin_flow_line_5": "fanin-flow-line-5",
            "fanout_flow_line_5": "fanout-flow-line-5",
        }

        ns = self._setup_and_exec(code, actor_map)
        fanout_fn = self._get_fanout_fn(ns)
        msg_ctx = _make_msg_ctx("orig-id", route_next=[])
        frames = _drive_abi_generator(fanout_fn({"topics": ["a"]}), msg_ctx)

        for frame in frames:
            assert frame.headers["x-asya-fan-in"]["aggregation_key"] == "/results"

    def test_fan_in_header_origin_id(self):
        """x-asya-fan-in.origin_id should be the original message ID."""
        ops = [_make_fanout_op(), ActorCall(lineno=6, name="formatter"), Return(lineno=7)]
        code = _generate_code_for_ops("flow", ops)
        actor_map = {
            "research_agent": "research-agent",
            "formatter": "formatter",
            "fanin_flow_line_5": "fanin-flow-line-5",
            "fanout_flow_line_5": "fanout-flow-line-5",
        }

        ns = self._setup_and_exec(code, actor_map)
        fanout_fn = self._get_fanout_fn(ns)
        msg_ctx = _make_msg_ctx("my-origin-id-123", route_next=[])
        frames = _drive_abi_generator(fanout_fn({"topics": ["a"]}), msg_ctx)

        for frame in frames:
            assert frame.headers["x-asya-fan-in"]["origin_id"] == "my-origin-id-123"

    def test_slice_payloads_are_individual_items(self):
        """Slice yields should be the individual items from the iterable."""
        ops = [_make_fanout_op(), ActorCall(lineno=6, name="formatter"), Return(lineno=7)]
        code = _generate_code_for_ops("flow", ops)
        actor_map = {
            "research_agent": "research-agent",
            "formatter": "formatter",
            "fanin_flow_line_5": "fanin-flow-line-5",
            "fanout_flow_line_5": "fanout-flow-line-5",
        }

        ns = self._setup_and_exec(code, actor_map)
        fanout_fn = self._get_fanout_fn(ns)
        msg_ctx = _make_msg_ctx("orig-id", route_next=[])
        frames = _drive_abi_generator(fanout_fn({"topics": ["a", "b"]}), msg_ctx)

        assert frames[1].payload == "a"
        assert frames[2].payload == "b"

    def test_existing_headers_preserved(self):
        """Existing headers in message context should be preserved (not overwritten)."""
        ops = [_make_fanout_op(), ActorCall(lineno=6, name="formatter"), Return(lineno=7)]
        code = _generate_code_for_ops("flow", ops)
        actor_map = {
            "research_agent": "research-agent",
            "formatter": "formatter",
            "fanin_flow_line_5": "fanin-flow-line-5",
            "fanout_flow_line_5": "fanout-flow-line-5",
        }

        ns = self._setup_and_exec(code, actor_map)
        fanout_fn = self._get_fanout_fn(ns)
        msg_ctx = _make_msg_ctx("orig-id", route_next=[], headers={"trace_id": "abc123"})
        frames = _drive_abi_generator(fanout_fn({"topics": ["a"]}), msg_ctx)

        # trace_id header should still exist in all frames
        for frame in frames:
            assert frame.headers.get("trace_id") == "abc123"


# ---------------------------------------------------------------------------
# Test: Integration via compiler
# ---------------------------------------------------------------------------


class TestFanOutIntegration:
    """Test fan-out via the FlowParser + OperationGrouper + CodeGenerator pipeline."""

    def _compile_flow(self, source: str) -> str:
        from asya_lab.flow.parser import FlowParser

        source = textwrap.dedent(source)
        parser = FlowParser(source, "test.py")
        flow_name, ops = parser.parse()
        code = _generate_code_for_ops(flow_name, ops)
        return code

    def test_comprehension_flow_compiles_to_valid_python(self):
        code = self._compile_flow(
            """
            def flow(p: dict) -> dict:
                p["results"] = [research_agent(t) for t in p["topics"]]
                return p
        """
        )
        try:
            _parse_code(code)
        except SyntaxError as e:
            pytest.fail(f"Compilation failed: {e}")

    def test_literal_flow_compiles_to_valid_python(self):
        code = self._compile_flow(
            """
            def flow(p: dict) -> dict:
                p["result"] = [
                    sentiment_analyzer(p["text"]),
                    topic_extractor(p["text"]),
                ]
                return p
        """
        )
        try:
            _parse_code(code)
        except SyntaxError as e:
            pytest.fail(f"Compilation failed: {e}")

    def test_gather_flow_compiles_to_valid_python(self):
        code = self._compile_flow(
            """
            async def flow(p: dict) -> dict:
                p["results"] = await asyncio.gather(*(research_agent(t) for t in p["topics"]))
                return p
        """
        )
        try:
            _parse_code(code)
        except SyntaxError as e:
            pytest.fail(f"Compilation failed: {e}")

    def test_list_wrapped_gather_compiles_to_valid_python(self):
        code = self._compile_flow("""
            async def flow(p: dict) -> dict:
                p["analysis"] = list(await asyncio.gather(
                    agent_a(p["text"]),
                    agent_b(p["text"]),
                    agent_c(p["text"]),
                ))
                return p
        """)
        try:
            _parse_code(code)
        except SyntaxError as e:
            pytest.fail(f"Compilation failed: {e}")

    def test_fanout_between_actors_compiles(self):
        code = self._compile_flow(
            """
            def flow(p: dict) -> dict:
                p = preprocessor(p)
                p["results"] = [agent(t) for t in p["items"]]
                p = postprocessor(p)
                return p
        """
        )
        try:
            _parse_code(code)
        except SyntaxError as e:
            pytest.fail(f"Compilation failed: {e}")

    def test_fanout_no_resolve_fanin(self):
        code = self._compile_flow(
            """
            def flow(p: dict) -> dict:
                p["results"] = [research_agent(t) for t in p["topics"]]
                return p
        """
        )
        assert "_resolve_fanin" not in code

    def test_two_fanouts_share_one_copy_import(self):
        code = self._compile_flow(
            """
            def flow(p: dict) -> dict:
                p["research"] = [research_agent(t) for t in p["topics"]]
                p["reviews"] = [review_agent(r) for r in p["research"]]
                return p
        """
        )
        assert code.count("import copy") == 1, "copy import should be emitted exactly once"
