"""Pytest configuration for gateway-actors integration tests."""

pytest_plugins = ["asya_testing.conftest"]

from asya_testing.fixtures import gateway_helper

__all__ = ["gateway_helper"]
