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
    for subcmd in ("config", "flow", "init", "mcp"):
        assert subcmd in output, f"Expected '{subcmd}' in help output"


def test_asya_mcp_help():
    """Test that asya mcp subcommand shows help."""
    result = subprocess.run(  # nosec B603
        [sys.executable, "-m", "asya_lab.cli", "mcp", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    output = result.stdout.lower() + result.stderr.lower()
    assert "mcp" in output
    assert "call" in output


def test_asya_mcp_call_help():
    """Test that asya mcp call subcommand shows help."""
    result = subprocess.run(  # nosec B603
        [sys.executable, "-m", "asya_lab.cli", "mcp", "call", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "call" in result.stdout.lower()
    assert "tool" in result.stdout.lower()


def test_asya_mcp_list_help():
    """Test that asya mcp list subcommand shows help."""
    result = subprocess.run(  # nosec B603
        [sys.executable, "-m", "asya_lab.cli", "mcp", "list", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "list" in result.stdout.lower()


def test_asya_mcp_show_help():
    """Test that asya mcp show subcommand shows help."""
    result = subprocess.run(  # nosec B603
        [sys.executable, "-m", "asya_lab.cli", "mcp", "show", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "show" in result.stdout.lower()
    assert "tool" in result.stdout.lower()


def test_asya_mcp_status_help():
    """Test that asya mcp status subcommand shows help."""
    result = subprocess.run(  # nosec B603
        [sys.executable, "-m", "asya_lab.cli", "mcp", "status", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "status" in result.stdout.lower()
    assert "task" in result.stdout.lower()


def test_asya_mcp_stream_help():
    """Test that asya mcp stream subcommand shows help."""
    result = subprocess.run(  # nosec B603
        [sys.executable, "-m", "asya_lab.cli", "mcp", "stream", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "stream" in result.stdout.lower()
    assert "task" in result.stdout.lower()


def test_asya_mcp_port_forward_help():
    """Test that asya mcp port-forward subcommand shows help."""
    result = subprocess.run(  # nosec B603
        [sys.executable, "-m", "asya_lab.cli", "mcp", "port-forward", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "port-forward" in result.stdout.lower() or "kubectl" in result.stdout.lower()
    assert "namespace" in result.stdout.lower()
