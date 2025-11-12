"""Logging configuration fixture for tests."""

import logging

from asya_testing.config import get_env


def configure_logging():
    """
    Configure logging for tests based on ASYA_LOG_LEVEL environment variable.

    Call this function in conftest.py at module level to set up logging.
    Default level: INFO
    """
    log_level = get_env("ASYA_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logging.getLogger("pika").setLevel(logging.WARNING)
