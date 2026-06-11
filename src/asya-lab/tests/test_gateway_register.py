"""Tests for flow → gateway registration (split gateway, shared registry CMs)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import yaml
from asya_lab.gateway_register import (
    A2A_AGENTS_CM,
    EXPOSE_FILENAME,
    MCP_TOOLS_CM,
    build_flow_expose,
    register_flow_with_gateway,
)


def test_build_flow_expose_a2a_and_mcp():
    intent = build_flow_expose(
        "text-improver",
        "start-text-improver",
        "Improve text",
        120,
        mcp=True,
        a2a=True,
        input_schema={"type": "object"},
    )
    assert intent["flow"] == "text-improver"

    agent = intent["a2a"]
    assert agent == {
        "name": "text-improver",
        "description": "Improve text",
        "actor": "start-text-improver",
        "timeout": 120,
        "streaming": True,
        "skills": [{"id": "text-improver", "name": "text-improver", "description": "Improve text"}],
        "inputModes": ["text/plain", "application/json"],
        "outputModes": ["text/plain", "application/json"],
    }

    tool = intent["mcp"]
    assert tool == {
        "name": "text-improver",
        "description": "Improve text",
        "actor": "start-text-improver",
        "timeout": 120,
        "inputSchema": {"type": "object"},
        "progress": True,
    }


def test_build_flow_expose_a2a_only_omits_mcp():
    intent = build_flow_expose("f", "start-f", "d", None, mcp=False, a2a=True)
    assert "mcp" not in intent
    assert "timeout" not in intent["a2a"]


class FakeRunner:
    """Minimal KubeRunner stand-in backed by an in-memory ConfigMap store."""

    def __init__(self, cms: dict):
        self.cms = cms

    def kubectl(self, *args, **kwargs):
        if args[:2] == ("get", "cm"):
            name = args[2]
            if name not in self.cms:
                return SimpleNamespace(returncode=1, stdout="", stderr="NotFound")
            return SimpleNamespace(returncode=0, stdout=json.dumps(self.cms[name]), stderr="")
        if args[:2] == ("patch", "cm"):
            name = args[2]
            payload = json.loads(args[args.index("-p") + 1])
            self.cms.setdefault(name, {"data": {}}).setdefault("data", {}).update(payload["data"])
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def _write_intent(overlay: Path, intent: dict) -> None:
    overlay.mkdir(parents=True, exist_ok=True)
    (overlay / EXPOSE_FILENAME).write_text(yaml.dump(intent, sort_keys=False))


def test_register_upserts_a2a_and_is_idempotent(tmp_path: Path):
    overlay = tmp_path / "overlays" / "dev"
    intent = build_flow_expose("hello", "start-hello", "Hi", 60, mcp=False, a2a=True)
    _write_intent(overlay, intent)

    cms = {A2A_AGENTS_CM: {"data": {"agents.yaml": "agents: []\n"}}}
    runner = FakeRunner(cms)

    register_flow_with_gateway(runner, overlay, tmp_path)
    agents = yaml.safe_load(cms[A2A_AGENTS_CM]["data"]["agents.yaml"])["agents"]
    assert [a["name"] for a in agents] == ["hello"]
    assert agents[0]["actor"] == "start-hello"

    # Re-registering the same flow does not duplicate the entry.
    register_flow_with_gateway(runner, overlay, tmp_path)
    agents = yaml.safe_load(cms[A2A_AGENTS_CM]["data"]["agents.yaml"])["agents"]
    assert [a["name"] for a in agents] == ["hello"]


def test_register_upserts_mcp_into_tools_cm(tmp_path: Path):
    overlay = tmp_path / "overlays" / "dev"
    intent = build_flow_expose("echo", "start-echo", "Echo", None, mcp=True, a2a=False)
    _write_intent(overlay, intent)

    cms = {MCP_TOOLS_CM: {"data": {"tools.yaml": "tools: []\n"}}}
    register_flow_with_gateway(FakeRunner(cms), overlay, tmp_path)

    tools = yaml.safe_load(cms[MCP_TOOLS_CM]["data"]["tools.yaml"])["tools"]
    assert [t["name"] for t in tools] == ["echo"]


def test_register_noop_without_intent(tmp_path: Path):
    overlay = tmp_path / "overlays" / "dev"
    overlay.mkdir(parents=True)
    cms: dict = {A2A_AGENTS_CM: {"data": {"agents.yaml": "agents: []\n"}}}
    runner = FakeRunner(cms)
    # No flow-expose.yaml present -> no changes.
    register_flow_with_gateway(runner, overlay, tmp_path)
    assert yaml.safe_load(cms[A2A_AGENTS_CM]["data"]["agents.yaml"])["agents"] == []
