"""Tests for the MCP client."""

from unittest.mock import MagicMock, patch

from asya_cli.mcp.client import AsyaGatewayClient


def test_client_initialization():
    """Test that the client initializes correctly."""
    client = AsyaGatewayClient(base_url="http://localhost:8089")
    assert client.base_url == "http://localhost:8089"
    assert client.mcp_session_id is None


def test_client_base_url_stripping():
    """Test that trailing slashes are stripped from base URL."""
    client = AsyaGatewayClient(base_url="http://localhost:8089/")
    assert client.base_url == "http://localhost:8089"


def test_tool_to_dict_basic():
    """Test _tool_to_dict with basic tool info."""
    client = AsyaGatewayClient()
    tool = {
        "name": "echo",
        "description": "Echo a message",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    }
    result = client._tool_to_dict(tool, show_details=False)
    assert result["name"] == "echo"
    assert result["description"] == "Echo a message"


def test_tool_to_dict_with_parameters():
    """Test _tool_to_dict with parameters."""
    client = AsyaGatewayClient()
    tool = {
        "name": "test_tool",
        "description": "Test tool",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to echo"},
                "count": {"type": "integer", "default": 1},
            },
            "required": ["message"],
        },
    }
    result = client._tool_to_dict(tool, show_details=True)
    assert result["name"] == "test_tool"
    assert "parameters" in result
    assert result["parameters"]["message"]["required"] is True
    assert result["parameters"]["count"]["required"] is False
    assert result["parameters"]["message"]["description"] == "Message to echo"
    assert result["parameters"]["count"]["default"] == 1


def test_extract_envelope_id():
    """Test extracting envelope ID from MCP result."""
    client = AsyaGatewayClient()
    mcp_result = {
        "content": [
            {"type": "text", "text": '{"envelope_id": "abc-123", "status": "pending"}'},
        ]
    }
    envelope_id = client._extract_envelope_id(mcp_result)
    assert envelope_id == "abc-123"


def test_extract_envelope_id_direct():
    """Test extracting envelope ID from result with direct field."""
    client = AsyaGatewayClient()
    mcp_result = {"envelope_id": "xyz-789"}
    envelope_id = client._extract_envelope_id(mcp_result)
    assert envelope_id == "xyz-789"


def test_extract_envelope_id_none():
    """Test extracting envelope ID when not present."""
    client = AsyaGatewayClient()
    mcp_result = {"content": [{"type": "text", "text": "no envelope here"}]}
    envelope_id = client._extract_envelope_id(mcp_result)
    assert envelope_id is None


@patch("asya_cli.mcp.client.requests.Session.post")
def test_mcp_request_sets_session_id(mock_post):
    """Test that MCP requests handle session IDs."""
    client = AsyaGatewayClient()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Mcp-Session-Id": "session-123"}
    mock_response.json.return_value = {"result": {"tools": []}}
    mock_post.return_value = mock_response

    client._mcp_request("test/method", {})

    assert client.mcp_session_id == "session-123"


@patch("asya_cli.mcp.client.requests.Session.post")
def test_mcp_request_includes_session_id(mock_post):
    """Test that MCP requests include session ID in headers."""
    client = AsyaGatewayClient()
    client.mcp_session_id = "session-456"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"result": {}}
    mock_post.return_value = mock_response

    client._mcp_request("test/method", {})

    call_args = mock_post.call_args
    headers = call_args[1]["headers"]
    assert headers["Mcp-Session-Id"] == "session-456"
