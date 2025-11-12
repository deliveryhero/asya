"""Integration tests for gateway health check functionality."""

import requests


def test_gateway_health_check_get(gateway_helper):
    """Test that gateway responds to GET health check requests."""
    response = requests.get(f"{gateway_helper.gateway_url}/health", timeout=5.0)

    assert response.status_code == 200
    assert response.text.strip() == "OK"


def test_gateway_health_check_head(gateway_helper):
    """Test that gateway responds to HEAD health check requests."""
    response = requests.head(f"{gateway_helper.gateway_url}/health", timeout=5.0)

    assert response.status_code == 200
