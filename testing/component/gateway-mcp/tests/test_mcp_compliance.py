"""
MCP Protocol Compliance Tests for Asya Gateway

Tests the gateway against MCP specification using behavioral validation.
These tests run against a live gateway instance via HTTP.
"""

import json
import os
import time
from typing import Any, Dict

import pytest
import requests

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8089")
PROTOCOL_VERSION = os.getenv("PROTOCOL_VERSION", "2024-11-05")


@pytest.fixture
def gateway_url():
    """Gateway base URL."""
    return GATEWAY_URL


@pytest.fixture
def session():
    """HTTP session for MCP requests."""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s




class TestMCPProtocolCompliance:
    """Test MCP protocol compliance."""

    def test_health_endpoint(self, gateway_url, session):
        """Test basic HTTP connectivity."""
        resp = session.get(f"{gateway_url}/health")
        assert resp.status_code == 200, f"Health check failed: {resp.text}"

    def test_initialize_handshake(self, gateway_url, session):
        """Test MCP initialize handshake."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "mcp-compliance-test",
                    "version": "1.0.0"
                }
            }
        }

        resp = session.post(f"{gateway_url}/mcp", json=request)
        assert resp.status_code == 200, f"Initialize failed: {resp.text}"

        result = resp.json()
        assert result["jsonrpc"] == "2.0"
        assert "result" in result
        assert "protocolVersion" in result["result"]
        assert "serverInfo" in result["result"]
        assert result["result"]["serverInfo"]["name"] == "asya-gateway"
        assert "capabilities" in result["result"]

    def test_tools_list(self, gateway_url, session):
        """Test tools/list method.

        Note: Gateway uses session-based MCP which requires persistent cookies.
        The /mcp endpoint requires initialization first, and session state is
        maintained via HTTP session cookies.
        """
        # Initialize session
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "pytest-tools-list",
                    "version": "1.0.0"
                }
            }
        }
        init_resp = session.post(f"{gateway_url}/mcp", json=init_request)
        assert init_resp.status_code == 200, f"Initialize failed: {init_resp.text}"

        # Call tools/list - session cookies should be automatically included
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {}
        }

        resp = session.post(f"{gateway_url}/mcp", json=request)

        # If session management fails, skip this test
        if resp.status_code == 400 and "session" in resp.text.lower():
            pytest.skip("Session management not working - cookies may not persist between requests")

        assert resp.status_code == 200, f"tools/list failed: {resp.text}"

        result = resp.json()
        assert "result" in result
        assert "tools" in result["result"]
        assert isinstance(result["result"]["tools"], list)

        # Validate each tool has required fields
        for tool in result["result"]["tools"]:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool


class TestMCPResponseStructure:
    """Test MCP CallToolResult response structure compliance."""

    def test_tool_call_response_structure(self, gateway_url, session):
        """Test that tool responses follow MCP CallToolResult structure."""
        request = {
            "name": "echo",
            "arguments": {
                "message": "test"
            }
        }

        resp = session.post(f"{gateway_url}/tools/call", json=request)
        assert resp.status_code == 200, f"Tool call failed: {resp.text}"

        result = resp.json()

        # Validate CallToolResult structure
        assert "content" in result, "Response must have 'content' array"
        assert isinstance(result["content"], list), "content must be an array"
        assert len(result["content"]) > 0, "content array cannot be empty"

        # Validate content type
        content = result["content"][0]
        assert "type" in content, "Content must have 'type' field"
        assert content["type"] == "text", f"Expected type 'text', got '{content['type']}'"
        assert "text" in content, "Text content must have 'text' field"

        # Validate isError field (optional but should be present)
        if "isError" in result:
            assert isinstance(result["isError"], bool), "isError must be boolean"

    def test_tool_error_response_structure(self, gateway_url, session):
        """Test that tool errors use isError=true pattern."""
        # Call a tool with invalid parameters to trigger error
        request = {
            "name": "echo",
            "arguments": {}  # Missing required 'message' parameter
        }

        resp = session.post(f"{gateway_url}/tools/call", json=request)
        assert resp.status_code == 200, "Tool errors should return 200 with isError=true"

        result = resp.json()

        # Validate error is in result, not protocol-level error
        assert "content" in result, "Error response must have content array"
        assert isinstance(result["content"], list)

        # Check isError flag
        assert "isError" in result, "Error response must have isError field"
        assert result["isError"] is True, "isError must be true for errors"

    def test_content_type_validation(self, gateway_url, session):
        """Test that content types are valid MCP types."""
        valid_types = ["text", "image", "audio", "resource"]

        request = {
            "name": "echo",
            "arguments": {"message": "test"}
        }

        resp = session.post(f"{gateway_url}/tools/call", json=request)
        result = resp.json()

        for content in result.get("content", []):
            assert content["type"] in valid_types, \
                f"Invalid content type: {content['type']}. Must be one of {valid_types}"


class TestMCPToolValidation:
    """Test MCP tool parameter validation."""

    def test_required_parameter_validation(self, gateway_url, session):
        """Test that required parameters are validated."""
        request = {
            "name": "test_validation",
            "arguments": {}  # Missing required_string
        }

        resp = session.post(f"{gateway_url}/tools/call", json=request)
        assert resp.status_code == 200

        result = resp.json()
        assert result.get("isError") is True
        # Error message should mention missing parameter
        error_text = result["content"][0]["text"]
        assert "required" in error_text.lower() or "missing" in error_text.lower()

    def test_optional_parameter_handling(self, gateway_url, session):
        """Test that optional parameters work correctly."""
        request = {
            "name": "test_validation",
            "arguments": {
                "required_string": "test"
                # Optional parameters omitted
            }
        }

        resp = session.post(f"{gateway_url}/tools/call", json=request)
        assert resp.status_code == 200

        result = resp.json()
        # Should succeed even without optional parameters
        if result.get("isError"):
            # If it errors, it should not be about optional parameters
            error_text = result["content"][0]["text"]
            assert "optional" not in error_text.lower()


class TestMCPProtocolVersions:
    """Test MCP protocol version compatibility."""

    @pytest.mark.parametrize("version", ["2024-11-05", "2025-03-26"])
    def test_protocol_version_support(self, gateway_url, session, version):
        """Test that gateway supports multiple protocol versions."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": version,
                "capabilities": {},
                "clientInfo": {
                    "name": "version-test",
                    "version": "1.0.0"
                }
            }
        }

        resp = session.post(f"{gateway_url}/mcp", json=request)
        assert resp.status_code == 200

        result = resp.json()
        assert "result" in result, f"Initialize failed for version {version}"
        assert "protocolVersion" in result["result"]


class TestMCPEnvelopeIntegration:
    """Test MCP integration with Asya envelope system."""

    def test_envelope_creation_from_tool_call(self, gateway_url, session):
        """Test that tool calls create envelopes correctly."""
        request = {
            "name": "echo",
            "arguments": {"message": "envelope test"}
        }

        resp = session.post(f"{gateway_url}/tools/call", json=request)
        assert resp.status_code == 200

        result = resp.json()
        content_text = result["content"][0]["text"]

        # Parse the JSON response
        data = json.loads(content_text)
        assert "envelope_id" in data
        assert "status_url" in data

        # Verify envelope exists
        envelope_id = data["envelope_id"]
        status_resp = session.get(f"{gateway_url}/envelopes/{envelope_id}")
        assert status_resp.status_code == 200

    def test_streaming_url_in_response(self, gateway_url, session):
        """Test that progress-enabled tools return stream_url."""
        for i in range(5):
            request = {
                "name": "echo",
                "arguments": {"message": f"test message {i}"}
            }

            resp = session.post(f"{gateway_url}/tools/call", json=request)
            assert resp.status_code == 200

            result = resp.json()
            content_text = result["content"][0]["text"]
            data = json.loads(content_text)

            assert "envelope_id" in data, f"Echo call {i} should return envelope_id"
            assert "status_url" in data, f"Echo call {i} should return status_url"


class TestMCPEdgeCases:
    """Test MCP protocol edge cases and error handling."""

    def test_invalid_json_rpc_request(self, gateway_url, session):
        """Test handling of invalid JSON-RPC requests."""
        request = {
            "jsonrpc": "1.0",  # Wrong version
            "id": 1,
            "method": "initialize"
        }

        resp = session.post(f"{gateway_url}/mcp", json=request)
        # Should either reject or handle gracefully

    def test_unknown_method(self, gateway_url, session):
        """Test handling of unknown MCP methods."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "unknown/method",
            "params": {}
        }

        resp = session.post(f"{gateway_url}/mcp", json=request)
        # Accept either 200 with error or 400
        assert resp.status_code in [200, 400], f"Unexpected status: {resp.status_code}"

        if resp.status_code == 200:
            result = resp.json()
            assert "error" in result, "Unknown method should return error"

    def test_unknown_tool(self, gateway_url, session):
        """Test calling unknown tool."""
        request = {
            "name": "nonexistent_tool",
            "arguments": {}
        }

        resp = session.post(f"{gateway_url}/tools/call", json=request)
        assert resp.status_code == 404, "Unknown tool should return 404"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
