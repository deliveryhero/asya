"""Pytest fixtures for test configuration."""

import pytest

from asya_testing.config import TestConfig, get_config


@pytest.fixture(scope="session")
def test_config() -> TestConfig:
    """
    Provide test configuration for entire test session.

    Returns:
        TestConfig instance loaded from environment variables

    Usage:
        def test_something(test_config):
            if test_config.is_rabbitmq():
                # RabbitMQ-specific test logic
            elif test_config.is_sqs():
                # SQS-specific test logic
    """
    return get_config()


@pytest.fixture(scope="session")
def gateway_url(test_config: TestConfig) -> str:
    """Gateway URL from configuration."""
    return test_config.gateway_url


@pytest.fixture(scope="session")
def s3_endpoint(test_config: TestConfig) -> str:
    """S3/MinIO endpoint from configuration."""
    return test_config.s3_endpoint


@pytest.fixture(scope="session")
def results_bucket(test_config: TestConfig) -> str:
    """Results bucket name from configuration."""
    return test_config.results_bucket


@pytest.fixture(scope="session")
def errors_bucket(test_config: TestConfig) -> str:
    """Errors bucket name from configuration."""
    return test_config.errors_bucket


@pytest.fixture(scope="session")
def namespace(test_config: TestConfig) -> str:
    """Kubernetes namespace from configuration."""
    return test_config.namespace
