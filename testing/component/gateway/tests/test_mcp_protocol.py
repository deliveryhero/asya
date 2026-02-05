#!/usr/bin/env python3
"""
Gateway component tests - MCP protocol.

Tests the MCP JSON-RPC 2.0 protocol implementation:
- Initialize handshake
- Health endpoint
"""

import logging
import os

import pytest
import requests
from asya_testing.fixtures import configure_logging
from asya_testing.config import require_env

configure_logging()

logger = logging.getLogger(__name__)


@pytest.fixture
def gateway_url():
    """Gateway base URL."""
    return require_env("ASYA_GATEWAY_URL")


@pytest.fixture
def mcp_url(gateway_url):
    """MCP endpoint URL."""
    return f"{gateway_url}/mcp"


def test_health_endpoint(gateway_url):
    """Test health endpoint returns OK."""
    response = requests.get(f"{gateway_url}/health")

    assert response.status_code == 200


def test_mcp_initialize(mcp_url):
    """Test MCP initialize handshake."""
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "test-client",
                "version": "1.0.0"
            }
        }
    }

    response = requests.post(mcp_url, json=request)

    assert response.status_code == 200
    data = response.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 1
    assert "result" in data
    assert "protocolVersion" in data["result"]
    assert "serverInfo" in data["result"]

# TODO: add test listing routes - should return ones from `shared/compose/configs/gateway-routes.yaml`
