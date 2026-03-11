"""Tests for asya serve API routes."""

import json
import subprocess  # nosec B404

import pytest


fastapi = pytest.importorskip("fastapi", reason="fastapi not installed (install with asya-lab[ui])")

from asya_lab.config.project import AsyaProject  # noqa: E402
from asya_lab.serve.app import create_app  # noqa: E402


@pytest.fixture
def project_with_flow(tmp_path):
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir()
    (asya_dir / "config.yaml").write_text(
        "readonly: false\ncompiler:\n  flows: .asya/flows\n  manifests: .asya/manifests\n"
    )
    flows_dir = asya_dir / "flows" / "test_flow"
    flows_dir.mkdir(parents=True)
    graph = {
        "flow": "test_flow",
        "nodes": [{"id": "a", "type": "actor", "role": "processor", "label": "a"}],
        "edges": [],
        "groups": [],
    }
    (flows_dir / "graph.json").write_text(json.dumps(graph))
    subprocess.run(  # nosec B603, B607
        ["git", "init", str(tmp_path)], capture_output=True, check=False
    )
    return AsyaProject.from_dir(tmp_path)


@pytest.fixture
def client(project_with_flow):
    from fastapi.testclient import TestClient

    app = create_app(project_with_flow)
    return TestClient(app)


def test_get_config(client):
    resp = client.get("/api/config")
    assert resp.status_code == 200


def test_list_flows(client):
    resp = client.get("/api/flows")
    assert resp.status_code == 200
    assert "test_flow" in resp.json()


def test_get_flow_graph(client):
    resp = client.get("/api/flows/test_flow/graph")
    assert resp.status_code == 200
    data = resp.json()
    assert data["flow"] == "test_flow"


def test_get_flow_graph_not_found(client):
    resp = client.get("/api/flows/nonexistent/graph")
    assert resp.status_code == 404


def test_compile_readonly_returns_403(tmp_path):
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir()
    (asya_dir / "config.yaml").write_text("readonly: true\n")
    subprocess.run(  # nosec B603, B607
        ["git", "init", str(tmp_path)], capture_output=True, check=False
    )
    project = AsyaProject.from_dir(tmp_path)
    from fastapi.testclient import TestClient

    app = create_app(project)
    client = TestClient(app)
    resp = client.post("/api/flows/test/compile")
    assert resp.status_code == 403


def test_gateway_no_config_returns_404(client):
    """Gateway endpoints return 404 when no gateway is configured."""
    resp = client.get("/api/gateway")
    assert resp.status_code == 404
    resp = client.post("/api/gateway/call", json={"tool": "test"})
    assert resp.status_code == 404


def test_actor_logs_returns_501(client):
    """Actor logs endpoint returns 501 (needs kubernetes client)."""
    resp = client.get("/api/actors/test-actor/logs")
    assert resp.status_code == 501
