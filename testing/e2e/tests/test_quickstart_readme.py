"""
Test that validates shell commands in the quickstart README.

This test extracts and executes bash code blocks from docs/quickstart/README.md
to ensure the quickstart guide actually works.
"""

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


def should_skip_block(block: str) -> tuple[bool, str]:
    """Determine if a block should be skipped during testing."""
    skip_patterns = [
        ("kind create cluster", "Cluster creation handled separately"),
        ("kubectl config use-context", "Context handled separately"),
        ("make up", "E2E-specific command"),
        ("make down", "E2E-specific command"),
        ("make trigger-tests", "E2E-specific command"),
        ("kind delete cluster", "Cleanup handled separately"),
        ("pip install", "CLI installation not needed for test"),
        ("asya mcp", "Requires gateway and CLI setup"),
        ("kubectl port-forward", "Port forwarding tested separately"),
        ("export ASYA_CLI_MCP_URL", "CLI-specific setup"),
        ("docker build", "Actor build tested separately"),
        ("kind load docker-image", "Actor deployment tested separately"),
        ("kubectl apply -f hello-actor.yaml", "Actor deployment tested separately"),
        ("kubectl get pods -l asya.sh/actor=hello -w", "Watch command"),
        ("kubectl logs", "Logs checked separately"),
        ("POD=", "Interactive command"),
        ("helm repo add asya", "Helm repo not yet published"),
        ("helm install asya-operator asya/", "Requires published Helm repo"),
        ("helm install asya-gateway asya/", "Requires published Helm repo"),
        ("helm install asya-crew asya/", "Requires published Helm repo"),
    ]

    for pattern, reason in skip_patterns:
        if pattern in block:
            return True, reason

    return False, ""


@pytest.mark.skipif(
    os.getenv("SKIP_QUICKSTART_README_TEST") == "1",
    reason="Quickstart README test disabled",
)
def test_quickstart_readme_commands(project_root):
    """Test that bash commands in quickstart README are valid."""
    readme_path = project_root / "docs" / "quickstart" / "README.md"

    if not readme_path.exists():
        pytest.skip(f"README not found: {readme_path}")

    blocks = extract_bash_blocks(readme_path)

    assert len(blocks) > 0, "No bash blocks found in README"

    print(f"\nFound {len(blocks)} bash code blocks in quickstart README")

    passed = 0
    skipped = 0
    failed_blocks = []

    for i, block in enumerate(blocks, 1):
        should_skip, skip_reason = should_skip_block(block)

        if should_skip:
            print(f"\n[{i}/{len(blocks)}] Skipping block (reason: {skip_reason}):")
            print(f"  {block[:80]}...")
            skipped += 1
            continue

        print(f"\n[{i}/{len(blocks)}] Testing block:")
        print(f"  {block[:80]}...")

        # Create temporary file for the command
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write(block)
            f.write('\n')
            temp_script = f.name

        try:
            # Run the command
            result = subprocess.run(
                ['bash', temp_script],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                print(f"  [+] PASSED")
                passed += 1
            else:
                print(f"  [-] FAILED (exit code: {result.returncode})")
                print(f"  stdout: {result.stdout[:200]}")
                print(f"  stderr: {result.stderr[:200]}")
                failed_blocks.append({
                    'number': i,
                    'block': block,
                    'returncode': result.returncode,
                    'stdout': result.stdout,
                    'stderr': result.stderr,
                })
        except subprocess.TimeoutExpired:
            print(f"  [-] TIMEOUT")
            failed_blocks.append({
                'number': i,
                'block': block,
                'error': 'Command timed out after 60 seconds',
            })
        finally:
            # Cleanup temp file
            try:
                os.unlink(temp_script)
            except:
                pass

    # Print summary
    print(f"\n{'='*60}")
    print("Test Summary:")
    print(f"{'='*60}")
    print(f"Total blocks:  {len(blocks)}")
    print(f"Tested:        {passed + len(failed_blocks)}")
    print(f"Passed:        {passed}")
    print(f"Failed:        {len(failed_blocks)}")
    print(f"Skipped:       {skipped}")
    print(f"{'='*60}")

    # Report failures
    if failed_blocks:
        print("\nFailed blocks:")
        for failure in failed_blocks:
            print(f"\nBlock #{failure['number']}:")
            print(f"  Command: {failure['block'][:100]}...")
            if 'returncode' in failure:
                print(f"  Exit code: {failure['returncode']}")
                print(f"  Error: {failure['stderr'][:200]}")

        pytest.fail(f"{len(failed_blocks)} command blocks failed validation")


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
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write(block)
            f.write('\n')
            temp_script = f.name

        try:
            # Syntax check with bash -n
            result = subprocess.run(
                ['bash', '-n', temp_script],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                failed_blocks.append({
                    'number': i,
                    'block': block[:100],
                    'error': result.stderr,
                })
        finally:
            try:
                os.unlink(temp_script)
            except:
                pass

    if failed_blocks:
        print("\nSyntax errors found:")
        for failure in failed_blocks:
            print(f"\nBlock #{failure['number']}:")
            print(f"  {failure['block']}...")
            print(f"  Error: {failure['error']}")

        pytest.fail(f"{len(failed_blocks)} blocks have syntax errors")

    print(f"[+] All {len(blocks)} bash blocks have valid syntax")
