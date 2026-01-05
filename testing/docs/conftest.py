"""
Pytest configuration for documentation tests.

These tests validate that documentation examples (like quickstart guides)
actually work as written. They run independently of e2e infrastructure.
"""

import logging
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the project root directory."""
    return Path(__file__).parent.parent.parent


def pytest_configure(config):
    """Register custom markers for docs tests."""
    config.addinivalue_line(
        "markers",
        "docs: Documentation validation tests (run independently of e2e infrastructure)",
    )
    config.addinivalue_line(
        "markers",
        "quickstart: Quickstart guide validation tests",
    )
