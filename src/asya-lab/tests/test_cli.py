"""Tests for the main CLI entry point."""

import subprocess  # nosec B404
import sys


def test_asya_lab_version():
    """Test that the main CLI shows version."""
    result = subprocess.run(  # nosec B603
        [sys.executable, "-m", "asya_lab.cli", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "v" in result.stdout


def test_asya_lab_help():
    """Test that the main CLI shows help."""
    result = subprocess.run(  # nosec B603
        [sys.executable, "-m", "asya_lab.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    output = result.stdout.lower()
    assert "asya" in output
    for subcmd in ("compile", "config", "expose", "flow", "init", "show", "status", "unexpose"):
        assert subcmd in output, f"Expected '{subcmd}' in help output"
