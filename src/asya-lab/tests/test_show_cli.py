"""Tests for the show CLI command."""

from unittest.mock import patch

from asya_lab.show_cli import show
from click.testing import CliRunner


def test_show_help():
    runner = CliRunner()
    result = runner.invoke(show, ["--help"])
    assert result.exit_code == 0
    assert "target" in result.output.lower()
    assert "--context" in result.output


def test_show_missing_flow(tmp_path):
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir()
    (asya_dir / "manifests").mkdir()

    runner = CliRunner()
    with patch("asya_lab.show_cli.find_asya_dir", return_value=asya_dir):
        result = runner.invoke(show, ["nonexistent-flow"])
    assert result.exit_code != 0
    assert "[-]" in result.output
    assert "not found" in result.output.lower()
