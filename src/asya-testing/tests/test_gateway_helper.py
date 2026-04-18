"""Unit tests for GatewayTestHelper.call_mcp_tool MCP adapter path."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import urlparse

import pytest

from asya_testing.utils.gateway import GatewayTestHelper


class FakeMCPHandler(BaseHTTPRequestHandler):
    """Minimal MCP adapter stub: serves POST /mcp returning task_id in _meta."""

    task_id = "test-task-abc123"
    recorded_requests: list = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        FakeMCPHandler.recorded_requests.append(json.loads(body))

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [{"type": "text", "text": '{"value": 42}'}],
                "_meta": {"task_id": self.task_id},
            },
        }
        self.wfile.write(json.dumps(response).encode())

    def log_message(self, *args):
        pass  # suppress output


@pytest.fixture
def fake_mcp_server():
    FakeMCPHandler.recorded_requests = []
    server = HTTPServer(("127.0.0.1", 0), FakeMCPHandler)
    port = server.server_address[1]
    t = Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", FakeMCPHandler
    server.shutdown()


def test_call_mcp_tool_uses_mcp_adapter(fake_mcp_server):
    base_url, handler_cls = fake_mcp_server

    helper = GatewayTestHelper(
        gateway_url="http://unused:8080",
        mcp_url=base_url,
    )

    result = helper.call_mcp_tool("test_echo", {"message": "hi"})

    # Returns correct task_id from _meta
    assert result["result"]["task_id"] == "test-task-abc123"
    assert result["result"]["id"] == "test-task-abc123"

    # Sent exactly one request to /mcp
    assert len(handler_cls.recorded_requests) == 1
    req = handler_cls.recorded_requests[0]
    assert req["method"] == "tools/call"
    assert req["params"]["name"] == "test_echo"
    assert req["params"]["arguments"] == {"message": "hi"}


def test_call_mcp_tool_url_has_mcp_suffix(fake_mcp_server):
    base_url, _ = fake_mcp_server

    helper = GatewayTestHelper(
        gateway_url="http://unused:8080",
        mcp_url=base_url,
    )
    # /mcp suffix must be appended
    assert helper.mcp_url == base_url + "/mcp"


def test_call_mcp_tool_no_task_id_raises(fake_mcp_server):
    base_url, handler_cls = fake_mcp_server

    # Override to return response without task_id
    original_task_id = handler_cls.task_id
    handler_cls.task_id = None

    class NoMetaHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "content": [{"type": "text", "text": "done"}],
                    # no _meta
                },
            }
            self.wfile.write(json.dumps(response).encode())

        def log_message(self, *args):
            pass

    no_meta_server = HTTPServer(("127.0.0.1", 0), NoMetaHandler)
    port = no_meta_server.server_address[1]
    t = Thread(target=no_meta_server.serve_forever, daemon=True)
    t.start()

    try:
        helper = GatewayTestHelper(
            gateway_url="http://unused:8080",
            mcp_url=f"http://127.0.0.1:{port}",
        )
        with pytest.raises(RuntimeError, match="no task_id in _meta"):
            helper.call_mcp_tool("test_echo", {})
    finally:
        no_meta_server.shutdown()
        handler_cls.task_id = original_task_id
