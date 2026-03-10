import sys
import tempfile
from pathlib import Path

import pytest

from asya_lab.flow import FlowCompiler
from asya_lab.flow.ir import (
    ActorCall,
    Break,
    Condition,
    Continue,
    FanOutCall,
    Mutation,
    Return,
    TryExcept,
    WhileLoop,
)
from asya_lab.flow.parser import FlowParser

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

    start_router = next(r for r in compiler.routers if r.name == "start_llm_auditor_flow")
    assert "critic" in start_router.true_branch_actors
    assert "reviser" in start_router.true_branch_actors


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


def _collect_ir_nodes(operations):
    """Recursively collect all IR nodes from nested structures."""
    nodes = []
    for op in operations:
        nodes.append(op)
        if isinstance(op, Condition):
            nodes.extend(_collect_ir_nodes(op.true_branch))
            nodes.extend(_collect_ir_nodes(op.false_branch))
        elif isinstance(op, WhileLoop):
            nodes.extend(_collect_ir_nodes(op.body))
        elif isinstance(op, TryExcept):
            nodes.extend(_collect_ir_nodes(op.body))
            for handler in op.handlers:
                nodes.extend(_collect_ir_nodes(handler.body))
            nodes.extend(_collect_ir_nodes(op.finally_body))
    return nodes


def test_parse_auditor_comprehensive(project_root):
    flow_file = project_root / "examples" / "flows" / "adk_llm_auditor.py"
    source = flow_file.read_text()
    parser = FlowParser(source, str(flow_file))
    flow_name, operations = parser.parse()

    assert parser.is_async is True
    assert flow_name == "llm_auditor"

    all_nodes = _collect_ir_nodes(operations)

    actor_calls = [n for n in all_nodes if isinstance(n, ActorCall)]
    assert len(actor_calls) >= 7

    actor_names = {ac.name for ac in actor_calls}
    expected_actors = {
        "extract_claims",
        "llm_generate",
        "fallback_generate",
        "critique",
        "reviser",
        "deep_reviser",
        "finalize",
    }
    assert expected_actors.issubset(actor_names)

    while_loops = [n for n in all_nodes if isinstance(n, WhileLoop)]
    assert len(while_loops) >= 1

    fanouts = [n for n in all_nodes if isinstance(n, FanOutCall)]
    assert len(fanouts) >= 1

    try_excepts = [n for n in all_nodes if isinstance(n, TryExcept)]
    assert len(try_excepts) >= 1


def test_compile_auditor_comprehensive(project_root):
    flow_file = project_root / "examples" / "flows" / "adk_llm_auditor.py"
    source = flow_file.read_text()
    compiler = FlowCompiler()
    code = compiler.compile(source, str(flow_file))

    assert len(compiler.routers) >= 18

    router_names = [r.name for r in compiler.routers]
    assert "start_llm_auditor" in router_names
    assert "end_llm_auditor" in router_names
    assert any("loop_back" in name for name in router_names)
    assert any(name.startswith("fanout_") for name in router_names)

    conditional_routers = [name for name in router_names if "_if" in name]
    assert len(conditional_routers) >= 4

    compile(code, "test.py", "exec")


def test_execute_auditor_init_mutations(project_root, compile_and_import, monkeypatch):
    monkeypatch.setenv("ASYA_HANDLER_EXTRACT_CLAIMS", "extract_claims")

    flow_file = project_root / "examples" / "flows" / "adk_llm_auditor.py"
    source = flow_file.read_text()
    routers = compile_and_import(source)
    monkeypatch.setattr(routers, "resolve", lambda name: name)

    msg_ctx = _make_msg_ctx()
    payload = {"text": "test"}
    payloads = _drive_abi(routers.start_llm_auditor(payload), msg_ctx)
    result = payloads[0]

    assert result["iteration"] == 0
    assert result["status"] == "started"
    assert result["partial"] is True

    next_actors = msg_ctx["route"]["next"]
    assert "extract_claims" in next_actors
    assert "router_llm_auditor_line_37_if" in next_actors


def test_execute_auditor_no_claims_exit(project_root, compile_and_import, monkeypatch):
    monkeypatch.setenv("ASYA_HANDLER_EXTRACT_CLAIMS", "extract_claims")

    flow_file = project_root / "examples" / "flows" / "adk_llm_auditor.py"
    source = flow_file.read_text()
    routers = compile_and_import(source)
    monkeypatch.setattr(routers, "resolve", lambda name: name)

    msg_ctx = _make_msg_ctx()
    payload = {"claims": []}
    _drive_abi(routers.router_llm_auditor_line_37_if(payload), msg_ctx)

    next_actors = msg_ctx["route"]["next"]
    assert "router_llm_auditor_line_38_seq" in next_actors


def test_execute_auditor_with_claims_enters_loop(
    project_root, compile_and_import, monkeypatch
):
    monkeypatch.setenv("ASYA_HANDLER_EXTRACT_CLAIMS", "extract_claims")

    flow_file = project_root / "examples" / "flows" / "adk_llm_auditor.py"
    source = flow_file.read_text()
    routers = compile_and_import(source)
    monkeypatch.setattr(routers, "resolve", lambda name: name)

    msg_ctx = _make_msg_ctx()
    payload = {"claims": ["claim1"]}
    _drive_abi(routers.router_llm_auditor_line_37_if(payload), msg_ctx)

    next_actors = msg_ctx["route"]["next"]
    assert "router_llm_auditor_line_42_loop_back_0" in next_actors


def test_execute_auditor_score_approved(project_root, compile_and_import, monkeypatch):
    monkeypatch.setenv("ASYA_HANDLER_EXTRACT_CLAIMS", "extract_claims")

    flow_file = project_root / "examples" / "flows" / "adk_llm_auditor.py"
    source = flow_file.read_text()
    routers = compile_and_import(source)
    monkeypatch.setattr(routers, "resolve", lambda name: name)

    msg_ctx = _make_msg_ctx()
    payload = {"aggregate_score": 95}
    _drive_abi(routers.router_llm_auditor_line_66_if(payload), msg_ctx)

    next_actors = msg_ctx["route"]["next"]
    assert "router_llm_auditor_line_67_seq" in next_actors


def test_execute_auditor_score_standard_revision(
    project_root, compile_and_import, monkeypatch
):
    monkeypatch.setenv("ASYA_HANDLER_EXTRACT_CLAIMS", "extract_claims")

    flow_file = project_root / "examples" / "flows" / "adk_llm_auditor.py"
    source = flow_file.read_text()
    routers = compile_and_import(source)
    monkeypatch.setattr(routers, "resolve", lambda name: name)

    msg_ctx = _make_msg_ctx()
    payload = {"aggregate_score": 75}
    _drive_abi(routers.router_llm_auditor_line_69_if(payload), msg_ctx)

    next_actors = msg_ctx["route"]["next"]
    assert "critique" in next_actors
    assert "reviser" in next_actors


def test_execute_auditor_score_deep_revision(
    project_root, compile_and_import, monkeypatch
):
    monkeypatch.setenv("ASYA_HANDLER_EXTRACT_CLAIMS", "extract_claims")

    flow_file = project_root / "examples" / "flows" / "adk_llm_auditor.py"
    source = flow_file.read_text()
    routers = compile_and_import(source)
    monkeypatch.setattr(routers, "resolve", lambda name: name)

    msg_ctx = _make_msg_ctx()
    payload = {"aggregate_score": 40}
    _drive_abi(routers.router_llm_auditor_line_69_if(payload), msg_ctx)

    next_actors = msg_ctx["route"]["next"]
    assert "critique" in next_actors
    assert "deep_reviser" in next_actors


def test_execute_auditor_continue_marginal(
    project_root, compile_and_import, monkeypatch
):
    monkeypatch.setenv("ASYA_HANDLER_EXTRACT_CLAIMS", "extract_claims")

    flow_file = project_root / "examples" / "flows" / "adk_llm_auditor.py"
    source = flow_file.read_text()
    routers = compile_and_import(source)
    monkeypatch.setattr(routers, "resolve", lambda name: name)

    msg_ctx = _make_msg_ctx()
    payload = {"aggregate_score": 50, "prev_score": 30}
    _drive_abi(routers.router_llm_auditor_line_61_if(payload), msg_ctx)

    next_actors = msg_ctx["route"]["next"]
    assert "router_llm_auditor_line_62_seq" in next_actors
