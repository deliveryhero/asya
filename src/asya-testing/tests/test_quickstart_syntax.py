"""
Syntax validation for bash code blocks in quickstart documentation.

This is a smoke test that validates bash syntax in docs/quickstart/README.md
without requiring any environment setup or fixtures.
"""

import contextlib
import os
import re
import subprocess
import tempfile
from pathlib import Path

import pytest


def extract_bash_blocks(markdown_file: Path) -> list[str]:
    """Extract all bash code blocks from a markdown file."""
    content = markdown_file.read_text()

    # Pattern to match ```bash...``` blocks
    pattern = r"```bash\n(.*?)```"
    blocks = re.findall(pattern, content, re.DOTALL)

    return [block.strip() for block in blocks if block.strip()]


@pytest.mark.smoke
def test_quickstart_readme_syntax():
    """Basic syntax check for quickstart README bash blocks."""
    project_root = Path(__file__).parent.parent.parent.parent
    readme_path = project_root / "docs" / "quickstart" / "README.md"

    if not readme_path.exists():
        pytest.skip(f"README not found: {readme_path}")

    blocks = extract_bash_blocks(readme_path)

    assert len(blocks) > 0, "No bash blocks found in README"

    # Check each block for basic syntax errors
    failed_blocks = []

    for i, block in enumerate(blocks, 1):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write(block)
            f.write("\n")
            temp_script = f.name

        try:
            # Syntax check with bash -n
            result = subprocess.run(
                ["bash", "-n", temp_script],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                failed_blocks.append(
                    {
                        "number": i,
                        "block": block[:100],
                        "error": result.stderr,
                    }
                )
        finally:
            with contextlib.suppress(Exception):
                os.unlink(temp_script)

    if failed_blocks:
        print("\nSyntax errors found:")
        for failure in failed_blocks:
            print(f"\nBlock #{failure['number']}:")
            print(f"  {failure['block']}...")
            print(f"  Error: {failure['error']}")

        pytest.fail(f"{len(failed_blocks)} blocks have syntax errors")

    print(f"[+] All {len(blocks)} bash blocks have valid syntax")
