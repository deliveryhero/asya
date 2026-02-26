import os
import sys
import tempfile
from pathlib import Path

import pytest

from asya_cli.flow import FlowCompiler
from asya_cli.flow.ir import ActorCall
from asya_cli.flow.parser import FlowParser


@pytest.fixture
def compile_and_import():
    modules_to_cleanup = []

    def _compile(source_code: str):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_file = Path(tmpdir) / "flow.py"
            source_file.write_text(source_code)
            output_dir = Path(tmpdir) / "output"
            compiler = FlowCompiler()
            compiler.compile_file(str(source_file), str(output_dir))
            sys.path.insert(0, str(output_dir))
            import importlib

            if "routers" in sys.modules:
                del sys.modules["routers"]
            import routers

            importlib.reload(routers)
            modules_to_cleanup.append(str(output_dir))
            return routers

    yield _compile
    for path in modules_to_cleanup:
        if path in sys.path:
            sys.path.remove(path)
    if "routers" in sys.modules:
        del sys.modules["routers"]


def _setup_vfs(tmpdir, prev, next_actors):
    vfs_root = os.path.join(tmpdir, "vfs")
    route_dir = os.path.join(vfs_root, "route")
    os.makedirs(route_dir, exist_ok=True)
    with open(os.path.join(route_dir, "prev"), "w") as f:
        f.write("\n".join(prev))
    with open(os.path.join(route_dir, "next"), "w") as f:
        f.write("\n".join(next_actors))
    return vfs_root


def _read_vfs_next(vfs_root):
    with open(os.path.join(vfs_root, "route", "next")) as f:
        content = f.read()
    return [x for x in content.splitlines() if x]


def test_parse_sequential_async(project_root):
    flow_file = project_root / "examples" / "flows" / "async_sequential.py"
    source = flow_file.read_text()
    parser = FlowParser(source, str(flow_file))
    flow_name, operations = parser.parse()

    assert parser.is_async is True
    assert flow_name == "llm_auditor_flow"
    actor_calls = [op for op in operations if isinstance(op, ActorCall)]
    assert len(actor_calls) == 2
    assert actor_calls[0].name == "critic"
    assert actor_calls[1].name == "reviser"


def test_compile_sequential_async(project_root):
    flow_file = project_root / "examples" / "flows" / "async_sequential.py"
    source = flow_file.read_text()
    compiler = FlowCompiler()
    compiler.compile(source, str(flow_file))

    assert len(compiler.routers) >= 2
    router_names = [r.name for r in compiler.routers]
    assert "start_llm_auditor_flow" in router_names
    assert "end_llm_auditor_flow" in router_names

    start_router = [r for r in compiler.routers if r.name == "start_llm_auditor_flow"][0]
    assert "critic" in start_router.true_branch_actors
    assert "reviser" in start_router.true_branch_actors


def test_execute_sequential_async(project_root, compile_and_import, monkeypatch):
    monkeypatch.setenv("ASYA_HANDLER_CRITIC", "critic")
    monkeypatch.setenv("ASYA_HANDLER_REVISER", "reviser")

    flow_file = project_root / "examples" / "flows" / "async_sequential.py"
    source = flow_file.read_text()
    routers = compile_and_import(source)

    with tempfile.TemporaryDirectory() as tmpdir:
        vfs_root = _setup_vfs(tmpdir, [], [])
        monkeypatch.setattr(routers, "_MSG_ROOT", vfs_root)

        payload = {"text": "test"}
        routers.start_llm_auditor_flow(payload)

        next_actors = _read_vfs_next(vfs_root)
        assert next_actors == ["critic", "reviser"]


def test_compile_react_loop(project_root):
    flow_file = project_root / "examples" / "flows" / "while_react_loop.py"
    source = flow_file.read_text()
    compiler = FlowCompiler()
    code = compiler.compile(source, str(flow_file))

    assert len(compiler.routers) == 4
    router_names = [r.name for r in compiler.routers]
    assert "start_react_agent" in router_names
    assert "end_react_agent" in router_names
    assert any("loop_back" in name for name in router_names)
    assert any("_if" in name for name in router_names)
    assert "llm_call" in code
    assert "execute_tool" in code


def test_execute_react_loop_no_tools(project_root, compile_and_import, monkeypatch):
    monkeypatch.setenv("ASYA_HANDLER_LLM_CALL", "llm_call")
    monkeypatch.setenv("ASYA_HANDLER_EXECUTE_TOOL", "execute_tool")

    flow_file = project_root / "examples" / "flows" / "while_react_loop.py"
    source = flow_file.read_text()
    routers = compile_and_import(source)

    router_names = [name for name in dir(routers) if name.startswith("router_react_agent")]
    if_router_name = [n for n in router_names if "_if" in n][0]
    if_router = getattr(routers, if_router_name)

    with tempfile.TemporaryDirectory() as tmpdir:
        vfs_root = _setup_vfs(tmpdir, [], [])
        monkeypatch.setattr(routers, "_MSG_ROOT", vfs_root)

        payload = {"tool_calls": []}
        if_router(payload)

        next_actors = _read_vfs_next(vfs_root)
        assert "execute-tool" not in next_actors


def test_execute_react_loop_with_tools(project_root, compile_and_import, monkeypatch):
    monkeypatch.setenv("ASYA_HANDLER_LLM_CALL", "llm_call")
    monkeypatch.setenv("ASYA_HANDLER_EXECUTE_TOOL", "execute_tool")

    flow_file = project_root / "examples" / "flows" / "while_react_loop.py"
    source = flow_file.read_text()
    routers = compile_and_import(source)

    router_names = [name for name in dir(routers) if name.startswith("router_react_agent")]
    if_router_name = [n for n in router_names if "_if" in n][0]
    if_router = getattr(routers, if_router_name)

    with tempfile.TemporaryDirectory() as tmpdir:
        vfs_root = _setup_vfs(tmpdir, [], [])
        monkeypatch.setattr(routers, "_MSG_ROOT", vfs_root)

        payload = {"tool_calls": ["some_tool"]}
        if_router(payload)

        next_actors = _read_vfs_next(vfs_root)
        assert "execute-tool" in next_actors
