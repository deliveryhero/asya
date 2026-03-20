"""Tests for CodeGenerator metadata output."""

from asya_lab.flow.codegen import CodeGenerator, CodegenMeta
from asya_lab.flow.parser import FlowParser


def _parse(source):
    parser = FlowParser(source, "test.py", "test")
    return parser.parse()


class TestCodegenMeta:
    def test_sequential_flow_metadata(self):
        source = """
from asya_lab.flow import flow

@flow
def my_flow(p: dict) -> dict:
    p = handler_a(p)
    p = handler_b(p)
    return p
"""
        result = _parse(source)
        gen = CodeGenerator(result, "test.py")
        gen.generate()
        meta = gen.get_meta()

        assert isinstance(meta, CodegenMeta)
        assert any(n.startswith("start_") for n in meta.router_names)
        assert "handler_a" in meta.all_handler_names
        assert "handler_b" in meta.all_handler_names
        for router_name in meta.router_names:
            refs = meta.router_refs.get(router_name, [])
            assert len(refs) > 0

    def test_conditional_flow_metadata(self):
        source = """
from asya_lab.flow import flow

@flow
def cond_flow(p: dict) -> dict:
    p = handler_a(p)
    if p.get("flag"):
        p = handler_b(p)
    else:
        p = handler_c(p)
    return p
"""
        result = _parse(source)
        gen = CodeGenerator(result, "test.py")
        gen.generate()
        meta = gen.get_meta()

        assert len(meta.router_names) >= 2
        for name in ("handler_a", "handler_b", "handler_c"):
            assert name in meta.all_handler_names

    def test_single_actor_flow_has_no_routers(self):
        source = """
from asya_lab.flow import flow

@flow
def simple(p: dict) -> dict:
    p = handler_a(p)
    return p
"""
        result = _parse(source)
        gen = CodeGenerator(result, "test.py")
        gen.generate()
        meta = gen.get_meta()

        assert meta.router_names == []
        assert meta.single_actor == "handler_a"
