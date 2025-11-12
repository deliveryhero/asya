"""Pytest configuration for E2E tests."""

pytest_plugins = ["asya_testing.conftest"]

from asya_testing.fixtures import (
    test_config,
    gateway_url,
    gateway_helper,
    s3_endpoint,
    results_bucket,
    errors_bucket,
    rabbitmq_client,
    rabbitmq_url,
    namespace,
    transport_timeouts,
    TransportTimeouts,
    e2e_helper,
    kubectl,
)

__all__ = [
    "test_config",
    "gateway_url",
    "gateway_helper",
    "s3_endpoint",
    "results_bucket",
    "errors_bucket",
    "rabbitmq_client",
    "rabbitmq_url",
    "namespace",
    "transport_timeouts",
    "TransportTimeouts",
    "e2e_helper",
    "kubectl",
]
