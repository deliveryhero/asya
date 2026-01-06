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
    Pre: Clean up any KEDA CRDs from previous test runs
    Post: Delete asya-local cluster
    """
    cluster_name = "asya-local"  # Matches the name in quickstart README

    print(f"\n{'='*80}")
    print(f"DOCS TEST SETUP: {cluster_name}")
    print(f"{'='*80}")

    # Pre: Delete any existing cluster to ensure clean state
    print(f"[.] Pre-cleanup: Deleting cluster if exists: {cluster_name}")
    subprocess.run(
        ["kind", "delete", "cluster", "--name", cluster_name],
        capture_output=True,
    )

    # Wait for cluster to be fully deleted
    import time
    max_wait = 30
    waited = 0
    while waited < max_wait:
        result = subprocess.run(
            ["kind", "get", "clusters"],
            capture_output=True,
            text=True,
        )
        if cluster_name not in result.stdout:
            break
        time.sleep(1)  # Poll for cluster deletion
        waited += 1

    print(f"[+] Pre-cleanup complete")

    # Pre: Clean up KEDA CRDs from previous runs
    print(f"[.] Pre-cleanup: Removing KEDA CRDs if present")
    subprocess.run(
        ["kubectl", "delete", "crd", "-l", "app.kubernetes.io/part-of=keda-operator"],
        capture_output=True,
    )
    print(f"[+] KEDA CRD cleanup complete\n")

    # Test runs and creates the cluster itself as part of validation
    yield cluster_name

    # Post: Always cleanup cluster
    print(f"\n{'='*80}")
    print(f"DOCS TEST TEARDOWN: {cluster_name}")
    print(f"{'='*80}")
    print(f"[.] Post-cleanup: Deleting cluster: {cluster_name}")
    subprocess.run(
        ["kind", "delete", "cluster", "--name", cluster_name],
        capture_output=True,
    )
    print(f"[+] Cluster deleted: {cluster_name}")
    print(f"{'='*80}\n")


def extract_bash_blocks(markdown_file: Path) -> list[tuple[str, list[str]]]:
    """Extract all bash code blocks from a markdown file.

    Returns list of (block, test_commands) tuples where test_commands is a list of
    commands extracted from <!-- TEST: command --> HTML comments immediately after bash blocks.
    """
    content = markdown_file.read_text()

    # Split content into sections starting with ```bash
    blocks_with_tests = []

    # Find all bash blocks
    bash_pattern = r"```bash\n(.*?)```"
    bash_matches = re.finditer(bash_pattern, content, re.DOTALL)

    for match in bash_matches:
        block = match.group(1).strip()
        block_end = match.end()

        # Look for TEST commands after this block
        test_commands = []
        remaining_content = content[block_end:]

        # Find all consecutive TEST comments (allow multiple newlines/blank lines)
        test_pattern = r"^\s*<!-- TEST: (.*?) -->"
        while True:
            test_match = re.match(test_pattern, remaining_content)
            if test_match:
                test_commands.append(test_match.group(1).strip())
                remaining_content = remaining_content[test_match.end():]
            else:
                break

        blocks_with_tests.append((block, test_commands))

    return blocks_with_tests


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
        # ("make up", "E2E-specific command"),
        # ("make down", "E2E-specific command"),
        ("make trigger-tests", "E2E-specific command"),
        ("pip install", "CLI installation not needed for test"),
        ("asya mcp", "Requires gateway and CLI setup"),
        ("kubectl port-forward", "Port forwarding tested separately"),
        ("export ASYA_CLI_MCP_URL", "CLI-specific setup"),
        ("POD=", "Interactive command"),
    ]

    for pattern, reason in skip_patterns:
        if pattern in block:
            return True, reason

    return False, ""


@pytest.mark.docs
@pytest.mark.quickstart
@pytest.mark.timeout(900)
def test_quickstart_readme_commands(project_root, quickstart_cluster):
    """Test that bash commands in quickstart README are valid.

    This test deploys infrastructure components (KEDA, LocalStack, Operator, etc.)
    in a dedicated Kind cluster (asya-local) to validate the quickstart guide.

    Timeout is 900s (15 minutes) to allow for cluster creation + infrastructure deployment.

    Fixtures:
    - project_root: Path to project root directory
    - quickstart_cluster: Manages Kind cluster lifecycle (pre/post cleanup)

    Note: This test runs independently of e2e infrastructure and creates its own Kind cluster.
    """
    readme_path = project_root / "docs" / "quickstart" / "README.md"

    if not readme_path.exists():
        pytest.skip(f"README not found: {readme_path}")

    # Create a temporary directory for test files
    with tempfile.TemporaryDirectory(prefix="quickstart-test-") as temp_dir:
        original_cwd = os.getcwd()
        try:
            # Change to temp directory for file creation and command execution
            os.chdir(temp_dir)
            print(f"\n[.] Working directory: {temp_dir}")

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

            for i, (block, test_commands) in enumerate(blocks, 1):
                should_skip, skip_reason = should_skip_block(block)

                if should_skip:
                    print(f"\n[{i}/{len(blocks)}] Skipping block (reason: {skip_reason}):")
                    print(f"  {block[:80]}...")
                    skipped += 1
                    continue

                print(f"\n[{i}/{len(blocks)}] Testing block:")
                print(f"  {block[:80]}...")
                print(f"  [Running...]")

                # Append test commands if present
                processed_block_str = block
                if test_commands:
                    print(f"  [TEST commands will execute: {len(test_commands)} command(s)]")
                    test_script_parts = []
                    for cmd in test_commands:
                        # Escape the command for safe echo output (replace ' with '\'' for bash)
                        escaped_cmd = cmd.replace("'", "'\"'\"'")
                        test_script_parts.append(f"echo '[TEST] Executing: {escaped_cmd}'")
                        test_script_parts.append(cmd)
                    processed_block_str = f"{block}\n" + "\n".join(test_script_parts)

                # Build complete script with bash options
                full_script = f"#!/bin/bash\nset -x\n{processed_block_str}\n"

                try:
                    # Run the command with real-time output
                    # Timeout set to 310s (5min + 10s buffer) to handle longest helm timeout (5min for prometheus)
                    import sys
                    result = subprocess.run(
                        ['bash', '-c', full_script],
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
                        print(f"\n{'='*60}")
                        print("FAILURE DIAGNOSTICS:")
                        print(f"{'='*60}")

                        # Show cluster state for debugging
                        print("\nChecking cluster state...")
                        subprocess.run(['kubectl', 'get', 'pods', '--all-namespaces'], check=False)
                        print("\nChecking services...")
                        subprocess.run(['kubectl', 'get', 'svc', '--all-namespaces'], check=False)
                        print(f"{'='*60}\n")

                        pytest.fail(
                            f"Block #{i} failed with exit code {result.returncode}\n"
                            f"Command: {block[:100]}..."
                        )
                except subprocess.TimeoutExpired:
                    print(f"  [-] TIMEOUT after 310 seconds")
                    pytest.fail(
                        f"Block #{i} timed out after 310 seconds\n"
                        f"Command: {block[:100]}..."
                    )

            # Print summary
            print(f"\n{'='*60}")
            print("Test Summary:")
            print(f"{'='*60}")
            print(f"Total blocks:  {len(blocks)}")
            print(f"Tested:        {passed}")
            print(f"Passed:        {passed}")
            print(f"Skipped:       {skipped}")
            print(f"{'='*60}")
        finally:
            # Restore original working directory
            os.chdir(original_cwd)
