"""Tests for port-forward functionality."""

import socket

from asya_cli.mcp.port_forward import check_port_available, find_free_port


def test_find_free_port():
    """Test that find_free_port returns a valid port."""
    port = find_free_port(start=9000, end=9100)
    assert 9000 <= port < 9100
    assert check_port_available(port)


def test_check_port_available_with_free_port():
    """Test check_port_available with a free port."""
    port = find_free_port(start=9100, end=9200)
    assert check_port_available(port) is True


def test_check_port_available_with_used_port():
    """Test check_port_available with a port in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        assert check_port_available(port) is False
