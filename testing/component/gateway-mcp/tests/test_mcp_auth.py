"""
MCP Authentication Tests for Asya Gateway.

Tests MCP API key authentication (Phase 2) behavior:
- 401 returned with WWW-Authenticate: Bearer when auth is required and token missing/wrong
- 200 returned with correct Authorization: Bearer <key>
- Public endpoints (/health, /.well-known/agent.json) remain unauthenticated

These tests run only when MCP_API_KEY env var is set (auth docker-compose profile).
When MCP_API_KEY is not set, all tests are skipped automatically.
"""

import os

import pytest
import requests

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8089")
MCP_API_KEY = os.getenv("MCP_API_KEY", "")

pytestmark = pytest.mark.skipif(
    not MCP_API_KEY,
    reason="MCP_API_KEY not set — auth tests require docker-compose.auth.yml",
)

INIT_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "auth-test", "version": "1.0.0"},
    },
}


@pytest.fixture
def session():
    """Unauthenticated HTTP session."""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture
def authed_session():
    """HTTP session with valid MCP API key."""
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {MCP_API_KEY}",
    })
    return s


class TestMCPAuthRequired:
    """Verify that /mcp and /tools/call require auth when ASYA_MCP_API_KEY is set."""

    def test_mcp_no_auth_returns_401(self, session):
        """POST /mcp without credentials returns 401."""
        resp = session.post(f"{GATEWAY_URL}/mcp", json=INIT_REQUEST)
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"

    def test_mcp_wrong_token_returns_401(self, session):
        """POST /mcp with wrong Bearer token returns 401."""
        session.headers["Authorization"] = "Bearer wrong-token"
        resp = session.post(f"{GATEWAY_URL}/mcp", json=INIT_REQUEST)
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"

    def test_mcp_wrong_scheme_returns_401(self, session):
        """POST /mcp with X-API-Key scheme (wrong for MCP) returns 401."""
        session.headers["X-API-Key"] = MCP_API_KEY
        resp = session.post(f"{GATEWAY_URL}/mcp", json=INIT_REQUEST)
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"

    def test_tools_call_no_auth_returns_401(self, session):
        """POST /tools/call without credentials returns 401."""
        resp = session.post(
            f"{GATEWAY_URL}/tools/call",
            json={"name": "echo", "arguments": {"message": "test"}},
        )
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"

    def test_mcp_sse_no_auth_returns_401(self, session):
        """GET /mcp/sse without credentials returns 401."""
        resp = session.get(f"{GATEWAY_URL}/mcp/sse", stream=True, timeout=3)
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


class TestMCPAuthResponse:
    """Verify 401 responses are RFC 6750-compliant."""

    def test_401_includes_www_authenticate_header(self, session):
        """401 response includes WWW-Authenticate: Bearer header per RFC 6750."""
        resp = session.post(f"{GATEWAY_URL}/mcp", json=INIT_REQUEST)
        assert resp.status_code == 401
        www_auth = resp.headers.get("WWW-Authenticate", "")
        assert www_auth.startswith("Bearer"), (
            f"Expected WWW-Authenticate: Bearer, got: {www_auth!r}"
        )

    def test_401_body_is_json_error(self, session):
        """401 response body is a JSON error object."""
        resp = session.post(f"{GATEWAY_URL}/mcp", json=INIT_REQUEST)
        assert resp.status_code == 401
        assert resp.headers.get("Content-Type", "").startswith("application/json"), (
            f"Expected JSON content type, got: {resp.headers.get('Content-Type')}"
        )
        body = resp.json()
        assert "error" in body, f"Expected 'error' key in body: {body}"
        assert body["error"] == "unauthorized"


class TestMCPAuthValid:
    """Verify that correct Bearer token grants access."""

    def test_mcp_valid_token_returns_200(self, authed_session):
        """POST /mcp with correct Bearer token returns 200."""
        resp = authed_session.post(f"{GATEWAY_URL}/mcp", json=INIT_REQUEST)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        result = resp.json()
        assert "result" in result, f"Expected result in response: {result}"
        assert result["result"]["serverInfo"]["name"] == "asya-gateway"

    def test_tools_call_valid_token_returns_200(self, authed_session):
        """POST /tools/call with correct Bearer token executes the tool."""
        resp = authed_session.post(
            f"{GATEWAY_URL}/tools/call",
            json={"name": "echo", "arguments": {"message": "auth-test"}},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        result = resp.json()
        assert "content" in result, f"Expected content in response: {result}"


class TestPublicEndpointsUnaffected:
    """Verify public endpoints remain accessible without authentication."""

    def test_health_is_public(self, session):
        """/health endpoint requires no auth."""
        resp = session.get(f"{GATEWAY_URL}/health")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_agent_card_is_public(self, session):
        """/.well-known/agent.json requires no auth."""
        resp = session.get(f"{GATEWAY_URL}/.well-known/agent.json")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert "name" in body, f"Expected agent card with 'name': {body}"
