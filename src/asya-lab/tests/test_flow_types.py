"""Tests for flow compiler type definitions."""

from pathlib import Path

from asya_lab.flow.result_types import ActorInfo, FlowInfo


class TestActorInfo:
    def test_basic_fields(self):
        actor = ActorInfo(
            name="handler-a",
            handler="handler_a",
            image="ghcr.io/team/actors:latest",
            flow_role="actor",
        )
        assert actor.name == "handler-a"
        assert actor.is_generated is False
        assert actor.manifest_path is None

    def test_router_actor(self):
        actor = ActorInfo(
            name="start-my-flow",
            handler="routers.start_my_flow",
            image="python:3.13-slim",
            flow_role="entry",
            is_generated=True,
        )
        assert actor.is_generated is True
        assert actor.flow_role == "entry"

    def test_env_defaults_to_empty(self):
        actor = ActorInfo(name="a", handler="a", image="img", flow_role="actor")
        assert actor.env == []


class TestFlowInfo:
    def test_basic_fields(self):
        info = FlowInfo(
            flow_name="my-flow",
            flow_function="my_flow",
            routers_path=Path("routers.py"),
            manifests_dir=Path("manifests"),
            graph={"nodes": [], "edges": []},
            dot="digraph {}",
            mermaid="flowchart LR",
            svg=None,
            actors=[],
            warnings=[],
        )
        assert info.flow_name == "my-flow"
        assert info.svg is None
        assert info.actors == []


def test_sdk_compile_function(tmp_path):
    """Test the top-level compile() SDK function."""
    from asya_lab.flow import compile as flow_compile

    source = tmp_path / "simple_flow.py"
    source.write_text("""
from asya_lab.flow import flow

async def step_a(payload: dict) -> dict:
    return payload

@flow
async def simple(payload: dict) -> dict:
    payload = await step_a(payload)
    return payload
""")

    result = flow_compile(str(source), output_dir=str(tmp_path / "out"))
    assert isinstance(result, FlowInfo)
    assert result.routers_path.exists()
