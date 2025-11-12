"""
Shared test library for Asya framework tests.

Provides reusable components for component, integration, and E2E tests:
- Transport clients (RabbitMQ, SQS, PubSub)
- Test utilities (RabbitMQ mgmt API, S3, Gateway helpers)
- Test handlers (echo, error, timeout, pipeline, edge cases)
- Pytest fixtures for common test setup
- Test configuration (consolidated parameter system)
"""

from .config import (
    ConfigurationError,
    HandlerMode,
    Storage,
    TestConfig,
    Transport,
    get_config,
    get_env,
    require_env,
    reset_config,
)


__version__ = "0.1.0"

__all__ = [
    "ConfigurationError",
    "HandlerMode",
    "Storage",
    "TestConfig",
    "Transport",
    "__version__",
    "get_config",
    "get_env",
    "require_env",
    "reset_config",
]
