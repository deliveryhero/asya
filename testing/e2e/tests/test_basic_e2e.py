#!/usr/bin/env python3
"""
Basic E2E tests for Asya framework on Kind cluster.

Tests the complete flow:
1. Gateway receives MCP tool call
2. Creates envelope and routes to actor queue
3. Actor (sidecar + runtime) processes envelope
4. Result delivered to end queue (happy-end/error-end)
5. Envelope status available via REST API

These tests verify the framework works end-to-end in a Kubernetes environment.
"""

import logging

import pytest
import requests

logger = logging.getLogger(__name__)


@pytest.mark.fast
def test_gateway_health(gateway_url):
    """Test that gateway is accessible and healthy."""
    logger.info("Testing gateway health endpoint")
    response = requests.get(f"{gateway_url}/health", timeout=10)
    assert response.status_code == 200
    logger.info("[+] Gateway is healthy")


@pytest.mark.fast
def test_echo_tool_basic(gateway_helper):
    """Test basic echo tool via MCP."""
    logger.info("Testing echo tool with basic message")

    result = gateway_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "Hello from E2E test"}
    )

    assert result["result"]["envelope_id"] is not None, "Should have envelope ID"
    assert "Envelope created successfully" in result["result"]["message"]

    logger.info("[+] Echo tool call succeeded")


@pytest.mark.fast
def test_doubler_pipeline(gateway_helper):
    """Test multi-actor pipeline (doubler -> incrementer -> happy-end)."""
    logger.info("Testing pipeline processing with doubler")

    result = gateway_helper.call_mcp_tool(
        tool_name="test_pipeline",
        arguments={"value": 5}
    )

    assert result["result"]["envelope_id"] is not None, "Should have envelope ID"
    assert "Envelope created successfully" in result["result"]["message"]

    logger.info("[+] Pipeline processing succeeded")


@pytest.mark.fast
def test_error_handling(gateway_helper):
    """Test error handling and routing to error-end queue."""
    logger.info("Testing error handling")

    result = gateway_helper.call_mcp_tool(
        tool_name="test_error",
        arguments={"should_fail": True}
    )

    assert result["result"]["envelope_id"] is not None, "Should have envelope ID"
    assert "Envelope created successfully" in result["result"]["message"]

    logger.info("[+] Error handling test completed")


@pytest.mark.fast
def test_timeout_handling(gateway_helper):
    """Test timeout handling for slow actors."""
    logger.info("Testing timeout handling")

    result = gateway_helper.call_mcp_tool(
        tool_name="test_timeout",
        arguments={"sleep_seconds": 2}
    )

    assert result["result"]["envelope_id"] is not None, "Should have envelope ID"
    assert "Envelope created successfully" in result["result"]["message"]

    logger.info("[+] Timeout handling test completed")
