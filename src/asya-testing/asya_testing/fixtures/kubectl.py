"""Kubectl fixture for E2E tests."""

import shlex
import subprocess
from typing import NamedTuple

import pytest


class KubectlResult(NamedTuple):
    """Result from kubectl command execution."""

    stdout: str
    stderr: str
    returncode: int


class KubectlHelper:
    """Helper class for executing kubectl commands."""

    def run(self, command: str, check: bool = True) -> KubectlResult:
        """
        Execute a kubectl command.

        Args:
            command: kubectl command arguments as string (e.g., "get pods -n default")
            check: Raise exception if command fails

        Returns:
            KubectlResult with stdout, stderr, and returncode
        """
        cmd = ["kubectl", *shlex.split(command)]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
            timeout=120,
        )

        return KubectlResult(
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )

    def wait_for_replicas(self, deployment: str, namespace: str, replicas: int, timeout: int = 30) -> None:
        """
        Wait for deployment to reach desired replica count.

        Args:
            deployment: Deployment name
            namespace: Namespace name
            replicas: Expected replica count
            timeout: Timeout in seconds
        """
        self.run(
            f"wait --for=jsonpath='{{.spec.replicas}}'={replicas} "
            f"deployment/{deployment} -n {namespace} --timeout={timeout}s"
        )


@pytest.fixture(scope="session")
def kubectl() -> KubectlHelper:
    """Provide kubectl helper for E2E tests."""
    return KubectlHelper()
