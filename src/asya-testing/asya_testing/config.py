"""
Consolidated test configuration for Asya framework tests.

This module provides a single source of truth for test parameters across
component, integration, and E2E tests. Configuration is loaded from environment
variables set by Makefiles and docker-compose.

FAIL-FAST PHILOSOPHY:
All required environment variables MUST be explicitly set. No defaults are
provided for critical configuration to prevent tests from running with
incorrect/misleading values. Tests fail immediately with clear error messages
if required variables are missing.

Usage:
    from asya_testing.config import TestConfig

    config = TestConfig()
    print(f"Transport: {config.transport}")
    print(f"Storage: {config.storage}")
    print(f"Handler mode: {config.handler_mode}")
"""

import logging
import os
from dataclasses import dataclass
from enum import Enum


logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""

    pass


def require_env(var_name: str, valid_values: list | None = None) -> str:
    """
    Get required environment variable with fail-fast validation.

    Args:
        var_name: Environment variable name
        valid_values: Optional list of valid values for validation

    Returns:
        Environment variable value

    Raises:
        ConfigurationError: If variable is not set or has invalid value
    """
    value = os.getenv(var_name)
    if value is None:
        raise ConfigurationError(
            f"Required environment variable '{var_name}' is not set. "
            f"This must be set by Makefile/docker-compose before running tests."
        )

    if valid_values and value not in valid_values:
        raise ConfigurationError(f"Invalid value for '{var_name}': '{value}'. Valid values: {', '.join(valid_values)}")

    return value


def get_env(var_name: str, default: str) -> str:
    """
    Get optional environment variable with explicit default.

    Use this ONLY for truly optional configuration like log levels.
    For test parameters (transport, storage, mode), use require_env().

    Args:
        var_name: Environment variable name
        default: Default value (must be explicit, not None)

    Returns:
        Environment variable value or default
    """
    return os.getenv(var_name, default)


class Transport(str, Enum):
    """Supported message transport backends."""

    RABBITMQ = "rabbitmq"
    SQS = "sqs"


class Storage(str, Enum):
    """Supported object storage backends."""

    MINIO = "minio"
    S3 = "s3"


class HandlerMode(str, Enum):
    """Supported handler modes."""

    PAYLOAD = "payload"
    ENVELOPE = "envelope"


@dataclass
class TestConfig:
    """
    Consolidated test configuration loaded from environment variables.

    Environment Variables:
        ASYA_TRANSPORT: Transport backend (rabbitmq, sqs)
        ASYA_STORAGE: Storage backend (minio, s3)
        ASYA_HANDLER_MODE: Handler mode (payload, envelope)
        ASYA_GATEWAY_URL: Gateway URL (default: http://gateway:8080)
        ASYA_S3_ENDPOINT: S3/MinIO endpoint (default: http://minio:9000)
        ASYA_LOG_LEVEL: Log level (default: INFO)
        NAMESPACE: Kubernetes namespace for E2E tests (default: asya-e2e)
        RABBITMQ_URL: RabbitMQ connection URL
        ASYA_SQS_ENDPOINT: SQS endpoint for LocalStack
    """

    # Test parameters
    transport: Transport
    storage: Storage
    handler_mode: HandlerMode

    # Service URLs
    gateway_url: str
    s3_endpoint: str
    rabbitmq_url: str | None
    sqs_endpoint: str | None

    # Test configuration
    log_level: str
    namespace: str
    results_bucket: str
    errors_bucket: str

    @classmethod
    def from_env(cls) -> "TestConfig":
        """
        Load configuration from environment variables with fail-fast validation.

        All required variables must be set by Makefile/docker-compose.
        Tests fail immediately with clear error if configuration is missing.

        Returns:
            TestConfig instance with values from environment

        Raises:
            ConfigurationError: If required variables are not set or invalid
        """
        # Required: Transport configuration
        transport_str = require_env("ASYA_TRANSPORT", valid_values=["rabbitmq", "sqs"]).lower()
        transport = Transport(transport_str)

        # Required: Storage configuration
        storage_str = require_env("ASYA_STORAGE", valid_values=["minio", "s3"]).lower()
        storage = Storage(storage_str)

        # Required: Handler mode
        mode_str = require_env("ASYA_HANDLER_MODE", valid_values=["payload", "envelope"]).lower()
        handler_mode = HandlerMode(mode_str)

        # Required: Service URLs
        gateway_url = require_env("ASYA_GATEWAY_URL")
        s3_endpoint = require_env("ASYA_S3_ENDPOINT")

        # Transport-specific URLs (conditionally required)
        rabbitmq_url = None
        sqs_endpoint = None
        if transport == Transport.RABBITMQ:
            rabbitmq_url = require_env("RABBITMQ_URL")
        elif transport == Transport.SQS:
            sqs_endpoint = require_env("ASYA_SQS_ENDPOINT")

        # Optional: Logging (truly optional, has sensible default)
        log_level = get_env("ASYA_LOG_LEVEL", "INFO").upper()

        # Optional: Namespace (for E2E tests, has sensible default)
        namespace = get_env("NAMESPACE", "asya-e2e")

        # Optional: S3 buckets (have standard defaults)
        results_bucket = get_env("ASYA_RESULTS_BUCKET", "asya-results")
        errors_bucket = get_env("ASYA_ERRORS_BUCKET", "asya-errors")

        return cls(
            transport=transport,
            storage=storage,
            handler_mode=handler_mode,
            gateway_url=gateway_url,
            s3_endpoint=s3_endpoint,
            rabbitmq_url=rabbitmq_url,
            sqs_endpoint=sqs_endpoint,
            log_level=log_level,
            namespace=namespace,
            results_bucket=results_bucket,
            errors_bucket=errors_bucket,
        )

    def is_rabbitmq(self) -> bool:
        """Check if using RabbitMQ transport."""
        return self.transport == Transport.RABBITMQ

    def is_sqs(self) -> bool:
        """Check if using SQS transport."""
        return self.transport == Transport.SQS

    def is_minio(self) -> bool:
        """Check if using MinIO storage."""
        return self.storage == Storage.MINIO

    def is_s3(self) -> bool:
        """Check if using S3 storage."""
        return self.storage == Storage.S3

    def is_payload_mode(self) -> bool:
        """Check if using payload handler mode."""
        return self.handler_mode == HandlerMode.PAYLOAD

    def is_envelope_mode(self) -> bool:
        """Check if using envelope handler mode."""
        return self.handler_mode == HandlerMode.ENVELOPE

    def get_transport_url(self) -> str | None:
        """Get transport connection URL based on active transport."""
        if self.is_rabbitmq():
            return self.rabbitmq_url
        elif self.is_sqs():
            return self.sqs_endpoint
        return None

    def __str__(self) -> str:
        """String representation for logging."""
        return (
            f"TestConfig(transport={self.transport.value}, "
            f"storage={self.storage.value}, "
            f"mode={self.handler_mode.value}, "
            f"namespace={self.namespace})"
        )


# Global configuration instance
_config: TestConfig | None = None


def get_config() -> TestConfig:
    """
    Get or create global test configuration instance.

    Returns:
        TestConfig singleton instance
    """
    global _config
    if _config is None:
        _config = TestConfig.from_env()
        logger.debug(f"Loaded test configuration: {_config}")
    return _config


def reset_config():
    """Reset global configuration (useful for testing)."""
    global _config
    _config = None
