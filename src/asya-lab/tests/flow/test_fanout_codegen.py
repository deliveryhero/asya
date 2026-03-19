"""Unit tests for fan-out router code generation."""

from __future__ import annotations

import ast
import re
import textwrap
from typing import Any

from asya_lab.flow.compiler import FlowCompiler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compile(source: str) -> str:
    """Compile flow source and return generated code."""
    compiler = FlowCompiler()
    return compiler.compile(textwrap.dedent(source), "test.py")


def _func_names(code: str) -> list[str]:
    """Extract all function names from generated code."""
    tree = ast.parse(code)
    return [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)]


def _get_func_source(code: str, func_name: str) -> str:
    """Extract source of a specific function from generated code."""
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == func_name:
            return ast.unparse(node)
    raise ValueError(f"Function {func_name} not found")


# ---------------------------------------------------------------------------
# ABI driver helpers
# ---------------------------------------------------------------------------


def _resolve_path(data: dict, path: str) -> Any:
    """Resolve a dotted path on a nested dict."""
    parts = path.lstrip(".").split(".")
    cur: Any = data
    for p in parts:
        cur = cur[p]
    return cur


def _set_path(data: dict, path: str, value: Any) -> None:
    """Set a value at a dotted path on a nested dict."""
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


async def _drive_abi_async(gen, msg_ctx: dict) -> list:
    """Drive an async ABI generator, collecting all yielded payloads."""
    payloads = []
    value = await gen.asend(None)
    while True:
        try:
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
                    value = await gen.asend(None)
            else:
                payloads.append(value)
                value = await gen.asend(None)
        except StopAsyncIteration:
            break
    return payloads


def _drive_abi(gen, msg_ctx: dict) -> list:
    """Drive an ABI generator (sync or async), collecting all yielded payloads."""
    import asyncio
    import inspect

    if inspect.isasyncgen(gen):
        return asyncio.run(_drive_abi_async(gen, msg_ctx))

    payloads = []
    value = gen.send(None)
    while True:
        try:
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
                    value = gen.send(None)
            else:
                payloads.append(value)
                value = gen.send(None)
        except StopIteration:
            break
    return payloads


class TestFanOutCodeGeneration:
    """Fan-out code generation produces valid, correct code."""

    def test_comprehension_fanout_valid_python(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p["results"] = [research_agent(t) for t in p["topics"]]
                return p
        """)
        ast.parse(code)

    def test_literal_fanout_valid_python(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p["results"] = [
                    agent_a(p["x"]),
                    agent_b(p["y"]),
                    agent_c(p["z"]),
                ]
                return p
        """)
        ast.parse(code)

    def test_gather_fanout_valid_python(self):
        code = _compile("""
            @flow
            async def my_flow(p: dict) -> dict:
                p["results"] = await asyncio.gather(*(research_agent(t) for t in p["topics"]))
                return p
        """)
        ast.parse(code)

    def test_fanout_creates_fanout_router(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p["results"] = [research_agent(t) for t in p["topics"]]
                return p
        """)
        funcs = _func_names(code)
        assert any("fanout" in f for f in funcs)

    def test_fanout_imports_copy(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p["results"] = [research_agent(t) for t in p["topics"]]
                return p
        """)
        assert "import copy" in code


class TestFanOutRouterStructure:
    """Fan-out routers have the right structure."""

    def test_comprehension_fanout_has_loop(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p["results"] = [research_agent(t) for t in p["topics"]]
                return p
        """)
        funcs = _func_names(code)
        fanout_routers = [f for f in funcs if "fanout" in f]
        assert len(fanout_routers) >= 1
        fanout_source = _get_func_source(code, fanout_routers[0])
        assert "research_agent" in fanout_source

    def test_literal_fanout_has_all_actors(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p["results"] = [
                    agent_a(p["x"]),
                    agent_b(p["y"]),
                ]
                return p
        """)
        funcs = _func_names(code)
        fanout_routers = [f for f in funcs if "fanout" in f]
        assert len(fanout_routers) >= 1
        fanout_source = _get_func_source(code, fanout_routers[0])
        assert "agent_a" in fanout_source
        assert "agent_b" in fanout_source

    def test_fanout_has_aggregation_key(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p["results"] = [research_agent(t) for t in p["topics"]]
                return p
        """)
        funcs = _func_names(code)
        fanout_routers = [f for f in funcs if "fanout" in f]
        fanout_source = _get_func_source(code, fanout_routers[0])
        assert "/results" in fanout_source

    def test_fanout_creates_aggregator_reference(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p["results"] = [research_agent(t) for t in p["topics"]]
                return p
        """)
        assert "fanin_" in code

    def test_fanout_reads_origin_id(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p["results"] = [research_agent(t) for t in p["topics"]]
                return p
        """)
        funcs = _func_names(code)
        fanout_routers = [f for f in funcs if "fanout" in f]
        fanout_source = _get_func_source(code, fanout_routers[0])
        assert ".id" in fanout_source


class TestFanOutIntegration:
    """Integration tests: compile + execute fan-out code via ABI driver."""

    def test_comprehension_fanout_produces_multiple_envelopes(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p["results"] = [research_agent(t) for t in p["topics"]]
                return p
        """)
        # Execute the fanout router
        ns: dict[str, Any] = {}
        exec(code, ns)  # nosec B102

        fanout_fn_name = next(n for n in ns if "fanout" in n and callable(ns.get(n)))
        fanout_fn = ns[fanout_fn_name]

        # Mock resolve to return actor name as-is
        ns["resolve"] = lambda name: name

        payload = {"topics": ["AI", "ML", "NLP"]}
        msg_ctx = {
            "id": "test-123",
            "route": {"prev": [], "next": ["downstream"]},
            "headers": {},
        }

        gen = fanout_fn(payload)
        payloads = _drive_abi(gen, msg_ctx)

        # Should produce: 1 parent payload + N sub-agent payloads
        # 3 topics + 1 parent = 4 payloads
        assert len(payloads) == 4

    def test_literal_fanout_produces_correct_count(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p["results"] = [
                    agent_a(p["x"]),
                    agent_b(p["y"]),
                ]
                return p
        """)
        ns: dict[str, Any] = {}
        exec(code, ns)  # nosec B102

        fanout_fn_name = next(n for n in ns if "fanout" in n and callable(ns.get(n)))
        fanout_fn = ns[fanout_fn_name]
        ns["resolve"] = lambda name: name

        payload = {"x": "hello", "y": "world"}
        msg_ctx = {
            "id": "test-456",
            "route": {"prev": [], "next": []},
            "headers": {},
        }

        gen = fanout_fn(payload)
        payloads = _drive_abi(gen, msg_ctx)

        # 2 agents + 1 parent = 3 payloads
        assert len(payloads) == 3

    def test_fanout_sets_fan_in_headers(self):
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p["results"] = [research_agent(t) for t in p["topics"]]
                return p
        """)
        ns: dict[str, Any] = {}
        exec(code, ns)  # nosec B102

        fanout_fn_name = next(n for n in ns if "fanout" in n and callable(ns.get(n)))
        fanout_fn = ns[fanout_fn_name]
        ns["resolve"] = lambda name: name

        payload = {"topics": ["AI", "ML"]}
        msg_ctx = {
            "id": "test-789",
            "route": {"prev": [], "next": []},
            "headers": {},
        }

        gen = fanout_fn(payload)
        _drive_abi(gen, msg_ctx)

        # Fan-in header should be set
        assert "x-asya-fan-in" in msg_ctx["headers"]
        fan_in = msg_ctx["headers"]["x-asya-fan-in"]  # type: ignore[index]
        assert "origin_id" in fan_in
        assert "slice_count" in fan_in
        assert "aggregation_key" in fan_in
        assert fan_in["aggregation_key"] == "/results"

    def test_fanout_with_continuation(self):
        """Fanout followed by more actors should include them in route."""
        code = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                p["results"] = [research_agent(t) for t in p["topics"]]
                p = finalizer(p)
                return p
        """)
        ast.parse(code)
        assert "finalizer" in code
