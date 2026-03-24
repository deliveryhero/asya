"""Tests for the show/render CLI command."""

from unittest.mock import patch

from asya_lab.show_cli import render
from click.testing import CliRunner


def test_render_help():
    runner = CliRunner()
    result = runner.invoke(render, ["--help"])
    assert result.exit_code == 0
    assert "target" in result.output.lower()
    assert "--context" in result.output


def test_render_missing_flow(tmp_path):
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir()
    (asya_dir / "config.yaml").write_text('compiler:\n  manifests: "./compiled/${arg:flow_name}/manifests"\n')

    runner = CliRunner()
    with patch("asya_lab.show_cli.find_asya_dir", return_value=asya_dir):
        result = runner.invoke(render, ["nonexistent-flow"])
    assert result.exit_code != 0
    assert "[-]" in result.output
