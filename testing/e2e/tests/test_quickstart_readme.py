"""
Test that validates shell commands in the quickstart README.

This test extracts and executes bash code blocks from docs/quickstart/README.md
to ensure the quickstart guide actually works.
"""

import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)


@pytest.fixture(scope="function")
def quickstart_cluster():
    """
    Manage Kind cluster lifecycle for quickstart README test.

    Pre: Delete asya-local cluster if exists (test creates it)
    Post: Delete asya-local cluster, restore kubectl context
    """
    cluster_name = "asya-local"  # Matches the name in quickstart README

    # Pre: Delete any existing cluster to ensure clean state
    logger.info(f"[.] Pre-cleanup: Deleting cluster if exists: {cluster_name}")
    subprocess.run(
        ["kind", "delete", "cluster", "--name", cluster_name],
        capture_output=True,
    )
    logger.info(f"[+] Pre-cleanup complete")

    # Test runs and creates the cluster itself as part of validation
    yield cluster_name

    # Post: Always cleanup cluster
    logger.info(f"[.] Post-cleanup: Deleting cluster: {cluster_name}")
    subprocess.run(
        ["kind", "delete", "cluster", "--name", cluster_name],
        capture_output=True,
    )
    logger.info(f"[+] Cluster deleted: {cluster_name}")

    # Restore kubectl context to e2e cluster if running in e2e environment
    if os.getenv("PROFILE"):
        profile = os.getenv("PROFILE")
        original_cluster = f"kind-asya-e2e-{profile}"
        result = subprocess.run(
            ["kubectl", "config", "use-context", original_cluster],
            capture_output=True,
        )
        if result.returncode == 0:
            logger.info(f"[+] Restored kubectl context: {original_cluster}")


def extract_bash_blocks(markdown_file: Path) -> list[str]:
    """Extract all bash code blocks from a markdown file."""
    content = markdown_file.read_text()

    # Pattern to match ```bash...``` blocks
    pattern = r"```bash\n(.*?)```"
    blocks = re.findall(pattern, content, re.DOTALL)

    return [block.strip() for block in blocks if block.strip()]


def extract_file_blocks(markdown_file: Path) -> list[tuple[str, str]]:
    """Extract code blocks with filenames from a markdown file.

    Returns list of (filename, content) tuples for blocks that start with # filename comment.
    Extracts from typed code blocks (```python, ```yaml, ```dockerfile, etc.) but not ```bash.
    """
    content = markdown_file.read_text()

    # Pattern to match typed code blocks (not bash, not untyped)
    pattern = r"```(\w+)\n(.*?)```"
    matches = re.findall(pattern, content, re.DOTALL)

    file_blocks = []
    for lang, block_content in matches:
        # Skip bash blocks (handled separately)
        if lang == "bash":
            continue

        # Skip untyped blocks
        if not block_content.strip():
            continue

        # Check if first line is a filename comment
        lines = block_content.strip().split('\n')
        if not lines:
            continue

        first_line = lines[0].strip()

        # Match comment patterns: # filename.ext or // filename.ext or # Dockerfile
        # Supports filenames with or without extensions
        filename_match = re.match(r'^[#/]+\s+([\w.-]+)$', first_line)
        if filename_match:
            filename = filename_match.group(1)
            # Content is everything after the first line
            file_content = '\n'.join(lines[1:])
            file_blocks.append((filename, file_content))

    return file_blocks


def should_skip_block(block: str) -> tuple[bool, str]:
    """Determine if a block should be skipped during testing."""
    skip_patterns = [
        ("make up", "E2E-specific command"),
        ("make down", "E2E-specific command"),
        ("make trigger-tests", "E2E-specific command"),
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
    ]

    for pattern, reason in skip_patterns:
        if pattern in block:
            return True, reason

    return False, ""


@pytest.mark.docs
@pytest.mark.xdist_group(name="docs")
@pytest.mark.order("last")
@pytest.mark.timeout(900)
def test_quickstart_readme_commands(project_root, quickstart_cluster):
    """Test that bash commands in quickstart README are valid.

    This test deploys infrastructure components (KEDA, LocalStack, Operator, etc.)
    in a dedicated Kind cluster (asya-local) to avoid conflicts with e2e tests.

    Timeout is 900s (15 minutes) to allow for cluster creation + infrastructure deployment.

    Fixtures:
    - quickstart_cluster: Ensures clean cluster state (pre/post cleanup)

    Note: This test is part of the "docs" group which runs LAST (after chaos tests)
    to ensure it doesn't interfere with the shared e2e infrastructure.
    """
    readme_path = project_root / "docs" / "quickstart" / "README.md"

    if not readme_path.exists():
        pytest.skip(f"README not found: {readme_path}")

    # First, create files from code blocks with filenames
    file_blocks = extract_file_blocks(readme_path)
    if file_blocks:
        print(f"\nCreating {len(file_blocks)} files from code blocks:")
        for filename, content in file_blocks:
            print(f"  Creating: {filename}")
            with open(filename, 'w') as f:
                f.write(content)
                f.write('\n')

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
        print(f"  [Running...]")

        # Create temporary file for the command
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write('#!/bin/bash\n')
            f.write('set -x\n')  # Enable bash command tracing
            f.write(block)
            f.write('\n')
            temp_script = f.name

        try:
            # Run the command with real-time output
            # Timeout set to 310s (5min + 10s buffer) to handle longest helm timeout (5min for prometheus)
            import sys
            result = subprocess.run(
                ['bash', temp_script],
                stdout=sys.stdout,
                stderr=sys.stderr,
                text=True,
                timeout=310,
            )

            if result.returncode == 0:
                print(f"  [+] PASSED")
                passed += 1
            else:
                print(f"  [-] FAILED (exit code: {result.returncode})")
                failed_blocks.append({
                    'number': i,
                    'block': block,
                    'returncode': result.returncode,
                    'stdout': '',
                    'stderr': '',
                })
        except subprocess.TimeoutExpired:
            print(f"  [-] TIMEOUT after 310 seconds")
            failed_blocks.append({
                'number': i,
                'block': block,
                'error': 'Command timed out after 310 seconds',
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
            if 'error' in failure:
                print(f"  Error: {failure['error']}")

        pytest.fail(f"{len(failed_blocks)} command blocks failed validation")
