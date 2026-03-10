"""Tests for the top-level `asya compile` command."""

from __future__ import annotations

from pathlib import Path

from asya_lab.compile_cli import compile_cmd
from click.testing import CliRunner


def test_compile_help():
    """--help exits 0 and shows usage for all target forms."""
    runner = CliRunner()
    result = runner.invoke(compile_cmd, ["--help"])
    assert result.exit_code == 0
    assert "TARGET" in result.output
    assert "file.py" in result.output
    assert "--flow" in result.output
    assert "--output-dir" in result.output
    assert "--plot" in result.output
    assert "--verbose" in result.output
    assert "--force" in result.output


def test_compile_py_file(tmp_path: Path):
    """Compile a simple sequential flow .py file and verify manifests are created."""
    flow_source = tmp_path / "my_flow.py"
    flow_source.write_text(
        "def my_flow(p: dict) -> dict:\n"
        "    p = actor_a(p)\n"
        "    p = actor_b(p)\n"
        "    return p\n"
        "\n"
        "def actor_a(p: dict) -> dict:\n"
        "    return p\n"
        "\n"
        "def actor_b(p: dict) -> dict:\n"
        "    return p\n"
    )

    output_dir = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(compile_cmd, [str(flow_source), "-o", str(output_dir), "--force"])

    assert result.exit_code == 0, (
        f"stdout: {result.output}\nstderr: {result.stderr if hasattr(result, 'stderr') else ''}"
    )
    assert "[+] Successfully compiled flow" in result.output

    # When -o is given, compiled code goes to the output dir
    routers_file = output_dir / "routers.py"
    assert routers_file.exists()
    router_code = routers_file.read_text()
    assert "my_flow" in router_code or "start_" in router_code
