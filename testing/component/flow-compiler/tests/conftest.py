"""Pytest configuration for flow-compiler component tests."""

import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def project_root() -> Path:
    """
    Return the project root directory using git rev-parse.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())
