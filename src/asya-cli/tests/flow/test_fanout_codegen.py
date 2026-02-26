"""Unit tests for fan-out router code generation."""

from __future__ import annotations

import ast
import json
import os
import tempfile
import textwrap
from contextlib import contextmanager
from typing import Any

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


@contextmanager
def _vfs_tmpdir(msg_id: str, route_next: list[str] | None = None, headers: dict | None = None):
    """Create a temporary VFS directory populated with message metadata.

    Sets ASYA_MSG_ROOT so generated code reads/writes the tmpdir.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Write id
        with open(os.path.join(tmpdir, "id"), "w") as f:
            f.write(msg_id)
        # Write route/next
        route_dir = os.path.join(tmpdir, "route")
        os.makedirs(route_dir, exist_ok=True)
        with open(os.path.join(route_dir, "next"), "w") as f:
            f.write("\n".join(route_next or []))
        # Write headers
        headers_dir = os.path.join(tmpdir, "headers")
        os.makedirs(headers_dir, exist_ok=True)
        if headers:
            for k, v in headers.items():
                with open(os.path.join(headers_dir, k), "w") as f:
                    if isinstance(v, dict | list):
                        f.write(json.dumps(v))
                    else:
                        f.write(str(v))

        old_env = os.environ.get("ASYA_MSG_ROOT")
        os.environ["ASYA_MSG_ROOT"] = tmpdir
        try:
            yield tmpdir
        finally:
            if old_env is None:
                os.environ.pop("ASYA_MSG_ROOT", None)
            else:
                os.environ["ASYA_MSG_ROOT"] = old_env


def _read_vfs_route_next(tmpdir: str) -> list[str]:
    """Read current route/next from VFS tmpdir."""
    with open(os.path.join(tmpdir, "route", "next")) as f:
        content = f.read()
    return content.splitlines() if content else []


def _read_vfs_header(tmpdir: str, name: str) -> dict[str, Any] | str:
    """Read a header from VFS tmpdir, parsing JSON if possible."""
    path = os.path.join(tmpdir, "headers", name)
    with open(path) as f:
        content = f.read()
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content


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
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name.startswith("fanout_")
        ]
        assert len(fanout_funcs) == 1, "Expected exactly one fanout_ function"

        # Check it contains yield statements
        yields = [node for node in ast.walk(fanout_funcs[0]) if isinstance(node, ast.Yield | ast.YieldFrom)]
        assert len(yields) >= 2, "Fan-out function should yield at least 2 messages (parent + slices)"

    def test_fanout_json_import_generated_once(self):
        """import json as _json should appear exactly once per file even with multiple fan-outs."""
        ops = [
            _make_fanout_op(target_key="/a", lineno=3),
            ActorCall(lineno=4, name="formatter1"),
            _make_fanout_op(target_key="/b", lineno=5, actor_calls=[("agent_b", "x")], iterable='p["items"]'),
            ActorCall(lineno=6, name="formatter2"),
            Return(lineno=7),
        ]
        code = _generate_code_for_ops("flow", ops)

        count = code.count("import json as _json")
        assert count == 1, f"json import should be emitted exactly once, found {count} times"

    def test_fanout_no_resolve_fanin(self):
        """Files with fan-out should not contain _resolve_fanin (removed helper)."""
        ops = [_make_fanout_op(), Return(lineno=6)]
        code = _generate_code_for_ops("flow", ops)

        assert "_resolve_fanin" not in code

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

        assert "import json as _json" in code

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

    def test_fanout_reads_id_from_vfs(self):
        """Fan-out router reads message ID from VFS."""
        ops = [_make_fanout_op(), Return(lineno=6)]
        code = _generate_code_for_ops("flow", ops)

        assert "_MSG_ROOT}/id" in code

    def test_fanout_reads_route_next_from_vfs(self):
        """Fan-out router reads route/next from VFS."""
        ops = [_make_fanout_op(), Return(lineno=6)]
        code = _generate_code_for_ops("flow", ops)

        assert "_MSG_ROOT}/route/next" in code

    def test_fanout_writes_headers_via_vfs(self):
        """Fan-out router writes headers to VFS files."""
        ops = [_make_fanout_op(), Return(lineno=6)]
        code = _generate_code_for_ops("flow", ops)

        assert "_MSG_ROOT}/headers/x-asya-fan-in" in code


# ---------------------------------------------------------------------------
# Test: Generated code execution (VFS-based)
# ---------------------------------------------------------------------------


class TestFanOutCodeExecution:
    """Execute the generated code with a VFS tmpdir and verify yielded payloads + VFS state."""

    def _setup_and_exec(self, code: str, actor_map: dict[str, str]) -> dict:
        """Exec the code with env vars set for resolve(). Must be called inside _vfs_tmpdir."""
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

        with _vfs_tmpdir("test-msg-id", route_next=[]):
            ns = self._setup_and_exec(code, actor_map)
            fanout_fn = self._get_fanout_fn(ns)
            payloads = list(fanout_fn({"topics": ["a", "b", "c"]}))

        assert len(payloads) == 4, f"Expected 4 payloads (1+3 topics), got {len(payloads)}"

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

        with _vfs_tmpdir("test-msg-id", route_next=[]):
            ns = self._setup_and_exec(code, actor_map)
            fanout_fn = self._get_fanout_fn(ns)
            payloads = list(fanout_fn({"text": "hello world"}))

        assert len(payloads) == 3, f"Expected 3 payloads (1+2 actors), got {len(payloads)}"

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
        with _vfs_tmpdir("orig-id", route_next=[]):
            ns = self._setup_and_exec(code, actor_map)
            fanout_fn = self._get_fanout_fn(ns)
            gen = fanout_fn(input_payload)
            parent_payload = next(gen)

        assert parent_payload == input_payload
        assert parent_payload is not input_payload

    def test_parent_vfs_route_points_to_fanin(self):
        """After yielding index 0, VFS route/next should point to the generated fan-in."""
        ops = [_make_fanout_op(), ActorCall(lineno=6, name="formatter"), Return(lineno=7)]
        code = _generate_code_for_ops("flow", ops)
        actor_map = {
            "research_agent": "research-agent",
            "formatter": "formatter",
            "fanin_flow_line_5": "fanin-flow-line-5",
            "fanout_flow_line_5": "fanout-flow-line-5",
        }

        with _vfs_tmpdir("orig-id", route_next=["downstream"]) as tmpdir:
            ns = self._setup_and_exec(code, actor_map)
            fanout_fn = self._get_fanout_fn(ns)
            gen = fanout_fn({"topics": ["x"]})
            next(gen)  # yield parent

            route_next = _read_vfs_route_next(tmpdir)
            assert route_next[0] == "fanin-flow-line-5"
            assert "downstream" in route_next

    def test_parent_vfs_fan_in_header_slice_index_0(self):
        """After yielding index 0, VFS x-asya-fan-in header should have slice_index=0."""
        ops = [_make_fanout_op(), ActorCall(lineno=6, name="formatter"), Return(lineno=7)]
        code = _generate_code_for_ops("flow", ops)
        actor_map = {
            "research_agent": "research-agent",
            "formatter": "formatter",
            "fanin_flow_line_5": "fanin-flow-line-5",
            "fanout_flow_line_5": "fanout-flow-line-5",
        }

        with _vfs_tmpdir("orig-id", route_next=[]) as tmpdir:
            ns = self._setup_and_exec(code, actor_map)
            fanout_fn = self._get_fanout_fn(ns)
            gen = fanout_fn({"topics": ["x"]})
            next(gen)  # yield parent

            fan_in = _read_vfs_header(tmpdir, "x-asya-fan-in")
            assert isinstance(fan_in, dict)
            assert fan_in["slice_index"] == 0

    def test_slice_vfs_route_points_to_actor_then_fanin(self):
        """After yielding a slice, VFS route/next should be [sub_agent, generated_fanin]."""
        ops = [_make_fanout_op(), ActorCall(lineno=6, name="formatter"), Return(lineno=7)]
        code = _generate_code_for_ops("flow", ops)
        actor_map = {
            "research_agent": "research-agent",
            "formatter": "formatter",
            "fanin_flow_line_5": "fanin-flow-line-5",
            "fanout_flow_line_5": "fanout-flow-line-5",
        }

        with _vfs_tmpdir("orig-id", route_next=[]) as tmpdir:
            ns = self._setup_and_exec(code, actor_map)
            fanout_fn = self._get_fanout_fn(ns)
            gen = fanout_fn({"topics": ["a"]})
            next(gen)  # skip parent
            next(gen)  # yield first slice

            route_next = _read_vfs_route_next(tmpdir)
            assert route_next == ["research-agent", "fanin-flow-line-5"]

    def test_slice_vfs_fan_in_header_increasing_indices(self):
        """Slice yields should have increasing slice_index in VFS."""
        ops = [_make_fanout_op(), ActorCall(lineno=6, name="formatter"), Return(lineno=7)]
        code = _generate_code_for_ops("flow", ops)
        actor_map = {
            "research_agent": "research-agent",
            "formatter": "formatter",
            "fanin_flow_line_5": "fanin-flow-line-5",
            "fanout_flow_line_5": "fanout-flow-line-5",
        }

        with _vfs_tmpdir("orig-id", route_next=[]) as tmpdir:
            ns = self._setup_and_exec(code, actor_map)
            fanout_fn = self._get_fanout_fn(ns)
            gen = fanout_fn({"topics": ["a", "b"]})

            indices = []
            for _ in gen:
                fan_in = _read_vfs_header(tmpdir, "x-asya-fan-in")
                assert isinstance(fan_in, dict)
                indices.append(fan_in["slice_index"])

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

        with _vfs_tmpdir("orig-id", route_next=[]) as tmpdir:
            ns = self._setup_and_exec(code, actor_map)
            fanout_fn = self._get_fanout_fn(ns)

            slice_counts = set()
            for _ in fanout_fn({"topics": ["a", "b", "c"]}):
                fan_in = _read_vfs_header(tmpdir, "x-asya-fan-in")
                assert isinstance(fan_in, dict)
                slice_counts.add(fan_in["slice_count"])

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

        with _vfs_tmpdir("orig-id", route_next=[]) as tmpdir:
            ns = self._setup_and_exec(code, actor_map)
            fanout_fn = self._get_fanout_fn(ns)

            for _ in fanout_fn({"topics": ["a"]}):
                fan_in = _read_vfs_header(tmpdir, "x-asya-fan-in")
                assert isinstance(fan_in, dict)
                assert fan_in["aggregation_key"] == "/results"

    def test_fan_in_header_origin_id(self):
        """x-asya-fan-in.origin_id should be the original message ID from VFS."""
        ops = [_make_fanout_op(), ActorCall(lineno=6, name="formatter"), Return(lineno=7)]
        code = _generate_code_for_ops("flow", ops)
        actor_map = {
            "research_agent": "research-agent",
            "formatter": "formatter",
            "fanin_flow_line_5": "fanin-flow-line-5",
            "fanout_flow_line_5": "fanout-flow-line-5",
        }

        with _vfs_tmpdir("my-origin-id-123", route_next=[]) as tmpdir:
            ns = self._setup_and_exec(code, actor_map)
            fanout_fn = self._get_fanout_fn(ns)

            for _ in fanout_fn({"topics": ["a"]}):
                fan_in = _read_vfs_header(tmpdir, "x-asya-fan-in")
                assert isinstance(fan_in, dict)
                assert fan_in["origin_id"] == "my-origin-id-123"

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

        with _vfs_tmpdir("orig-id", route_next=[]):
            ns = self._setup_and_exec(code, actor_map)
            fanout_fn = self._get_fanout_fn(ns)
            payloads = list(fanout_fn({"topics": ["a", "b"]}))

        assert payloads[1] == "a"
        assert payloads[2] == "b"

    def test_existing_headers_preserved(self):
        """Existing headers in VFS should be preserved (not overwritten)."""
        ops = [_make_fanout_op(), ActorCall(lineno=6, name="formatter"), Return(lineno=7)]
        code = _generate_code_for_ops("flow", ops)
        actor_map = {
            "research_agent": "research-agent",
            "formatter": "formatter",
            "fanin_flow_line_5": "fanin-flow-line-5",
            "fanout_flow_line_5": "fanout-flow-line-5",
        }

        with _vfs_tmpdir("orig-id", route_next=[], headers={"trace_id": "abc123"}) as tmpdir:
            ns = self._setup_and_exec(code, actor_map)
            fanout_fn = self._get_fanout_fn(ns)
            list(fanout_fn({"topics": ["a"]}))

            # trace_id header should still exist
            trace_id = _read_vfs_header(tmpdir, "trace_id")
            assert trace_id == "abc123"


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

    def test_fanout_no_resolve_fanin(self):
        code = self._compile_flow("""
            def flow(p: dict) -> dict:
                p["results"] = [research_agent(t) for t in p["topics"]]
                return p
        """)
        assert "_resolve_fanin" not in code

    def test_two_fanouts_share_one_json_import(self):
        code = self._compile_flow("""
            def flow(p: dict) -> dict:
                p["research"] = [research_agent(t) for t in p["topics"]]
                p["reviews"] = [review_agent(r) for r in p["research"]]
                return p
        """)
        assert code.count("import json as _json") == 1, "json import should be emitted exactly once"
