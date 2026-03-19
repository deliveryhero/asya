import sys
import tempfile
from pathlib import Path

import pytest

from asya_lab.flow import FlowCompiler
from asya_lab.flow.parser import ActorCall, FlowParser

from .conftest import _drive_abi, _make_msg_ctx


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


def test_parse_sequential_async(project_root):
    flow_file = project_root / "examples" / "flows" / "async_sequential.py"
    source = flow_file.read_text()
    parser = FlowParser(source, str(flow_file))
    result = parser.parse()

    assert parser.is_async is True
    assert result.flow_name == "llm_auditor_flow"
    actor_calls = [op for op in result.operations if isinstance(op, ActorCall)]
    assert len(actor_calls) == 2
    assert actor_calls[0].name == "critic"
    assert actor_calls[1].name == "reviser"


def test_execute_sequential_async(project_root, compile_and_import, monkeypatch):
    monkeypatch.setenv("ASYA_HANDLER_CRITIC", "critic")
    monkeypatch.setenv("ASYA_HANDLER_REVISER", "reviser")

    flow_file = project_root / "examples" / "flows" / "async_sequential.py"
    source = flow_file.read_text()
    routers = compile_and_import(source)

    msg_ctx = _make_msg_ctx()
    payload = {"text": "test"}
    _drive_abi(routers.start_llm_auditor_flow(payload), msg_ctx)

    next_actors = msg_ctx["route"]["next"]
    assert next_actors == ["critic", "reviser"]


def _run_react_loop_if_router(project_root, compile_and_import, monkeypatch, payload):
    """Compile the ReAct loop flow, execute the conditional router, return next actors."""
    monkeypatch.setenv("ASYA_HANDLER_LLM_CALL", "llm_call")
    monkeypatch.setenv("ASYA_HANDLER_EXECUTE_TOOL", "execute_tool")

    flow_file = project_root / "examples" / "flows" / "while_react_loop.py"
    source = flow_file.read_text()
    routers = compile_and_import(source)

    router_names = [name for name in dir(routers) if name.startswith("router_react_agent")]
    if_router_name = next(n for n in router_names if "_if" in n)
    if_router = getattr(routers, if_router_name)

    msg_ctx = _make_msg_ctx()
    _drive_abi(if_router(payload), msg_ctx)
    return msg_ctx["route"]["next"]


def test_execute_react_loop_no_tools(project_root, compile_and_import, monkeypatch):
    next_actors = _run_react_loop_if_router(
        project_root, compile_and_import, monkeypatch, {"tool_calls": []}
    )
    assert "execute-tool" not in next_actors


def test_execute_react_loop_with_tools(project_root, compile_and_import, monkeypatch):
    next_actors = _run_react_loop_if_router(
        project_root, compile_and_import, monkeypatch, {"tool_calls": ["some_tool"]}
    )
    assert "execute-tool" in next_actors
