"""Pytest configuration for asya-cli tests."""

import subprocess  # nosec B404
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def project_root() -> Path:
    """
    Return the project root directory using git rev-parse.
    """
    result = subprocess.run(  # nosec B603, B607
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())
