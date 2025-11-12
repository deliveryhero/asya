#!/usr/bin/env python3
"""
Integration test suite for socket reconnect scenarios.

Tests sidecar-runtime socket reconnection resilience:
- Runtime crashes and restarts while sidecar stays alive
- Sidecar restarts and reconnects to existing runtime
- Socket file removal and recovery

NOTE: These tests require docker CLI and are skipped in CI environments.
Run them manually from the host machine.
"""

import json
import logging
import os
import shutil
import subprocess
import time

import pytest

from asya_testing.config import get_env

logger = logging.getLogger(__name__)


# Skip all tests in this module if docker command is not available
pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="docker CLI not available - reconnect tests require docker command"
)


class DockerComposeHelper:
    """Helper to control Docker Compose services from within tests."""

    def __init__(self, project_name: str, compose_file: str):
        self.project_name = project_name
        self.compose_file = compose_file

    def restart_service(self, service_name: str) -> bool:
        """Restart a Docker Compose service."""
        try:
            logger.info(f"Restarting service: {service_name}")
            cmd = [
                "docker", "compose",
                "-f", self.compose_file,
                "-p", self.project_name,
                "restart", service_name
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            logger.debug(f"Restart output: {result.stdout}")
            return result.returncode == 0
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to restart {service_name}: {e.stderr}")
            return False

    def stop_service(self, service_name: str) -> bool:
        """Stop a Docker Compose service."""
        try:
            logger.info(f"Stopping service: {service_name}")
            cmd = [
                "docker", "compose",
                "-f", self.compose_file,
                "-p", self.project_name,
                "stop", service_name
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            logger.debug(f"Stop output: {result.stdout}")
            return result.returncode == 0
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to stop {service_name}: {e.stderr}")
            return False

    def start_service(self, service_name: str) -> bool:
        """Start a Docker Compose service."""
        try:
            logger.info(f"Starting service: {service_name}")
            cmd = [
                "docker", "compose",
                "-f", self.compose_file,
                "-p", self.project_name,
                "start", service_name
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            logger.debug(f"Start output: {result.stdout}")
            return result.returncode == 0
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to start {service_name}: {e.stderr}")
            return False

    def wait_for_healthy(self, service_name: str, timeout: int = 30) -> bool:
        """Wait for a service to become healthy."""
        logger.info(f"Waiting for {service_name} to become healthy (timeout={timeout}s)...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                cmd = [
                    "docker", "compose",
                    "-f", self.compose_file,
                    "-p", self.project_name,
                    "ps", "--format", "json", service_name
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)

                for line in result.stdout.strip().split('\n'):
                    if not line:
                        continue
                    service_info = json.loads(line)
                    health = service_info.get("Health", "")
                    state = service_info.get("State", "")

                    logger.debug(f"{service_name}: state={state}, health={health}")

                    if health == "healthy" or (state == "running" and not health):
                        logger.info(f"{service_name} is healthy")
                        return True

            except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
                logger.debug(f"Health check error: {e}")

            time.sleep(1)  # Wait before retrying health check

        logger.warning(f"{service_name} did not become healthy within {timeout}s")
        return False


@pytest.fixture(scope="function")
def docker_helper():
    """Create Docker Compose helper for controlling services."""
    transport = get_env("ASYA_TRANSPORT", "rabbitmq")
    handler_mode = get_env("ASYA_HANDLER_MODE", "payload")

    project_name = f"int-sidecar-runtime-{handler_mode}-{transport}"

    test_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    compose_file = os.path.join(test_dir, "profiles", f"{transport}.yml")

    logger.info(f"Docker helper: project={project_name}, compose={compose_file}")

    return DockerComposeHelper(project_name, compose_file)


def test_runtime_restart_reconnects(transport_helper, docker_helper):
    """
    Test sidecar reconnects when runtime crashes and restarts.

    Scenario:
    1. Send message - should succeed
    2. Restart runtime container
    3. Wait for runtime to be healthy
    4. Send message - should succeed after sidecar reconnects
    """
    logger.info("=== Testing runtime restart reconnection ===")

    logger.info("Step 1: Send message before runtime restart")
    message_before = {
        "id": "test-reconnect-before-1",
        "route": {"actors": ["test-echo"], "current": 0},
        "payload": {"test": "before_runtime_restart", "data": "initial"},
    }
    transport_helper.publish_message("asya-test-echo", message_before)

    result_before = transport_helper.assert_message_in_queue("asya-happy-end", timeout=10)
    assert result_before is not None, "Initial message failed before runtime restart"
    logger.info("[+] Message processed successfully before restart")

    logger.info("Step 2: Restart runtime container")
    assert docker_helper.restart_service("asya-echo-runtime"), "Failed to restart runtime"

    logger.info("Step 3: Wait for runtime to become healthy")
    assert docker_helper.wait_for_healthy("asya-echo-runtime", timeout=30), \
        "Runtime did not become healthy after restart"

    time.sleep(2)  # Brief pause for sidecar to reconnect

    logger.info("Step 4: Send message after runtime restart")
    message_after = {
        "id": "test-reconnect-after-1",
        "route": {"actors": ["test-echo"], "current": 0},
        "payload": {"test": "after_runtime_restart", "data": "reconnected"},
    }
    transport_helper.publish_message("asya-test-echo", message_after)

    result_after = transport_helper.assert_message_in_queue("asya-happy-end", timeout=15)
    assert result_after is not None, "Message failed after runtime restart - sidecar did not reconnect"

    payload = result_after.get("payload", {})
    assert payload.get("test") == "after_runtime_restart", \
        f"Wrong payload after reconnect: {payload}"

    logger.info("[+] Runtime restart reconnection: PASSED")


def test_sidecar_restart_reconnects(transport_helper, docker_helper):
    """
    Test sidecar reconnects to runtime after sidecar restarts.

    Scenario:
    1. Send message - should succeed
    2. Restart sidecar container (runtime stays alive)
    3. Wait for sidecar to start
    4. Send message - should succeed after sidecar reconnects
    """
    logger.info("=== Testing sidecar restart reconnection ===")

    logger.info("Step 1: Send message before sidecar restart")
    message_before = {
        "id": "test-sidecar-restart-before-1",
        "route": {"actors": ["test-echo"], "current": 0},
        "payload": {"test": "before_sidecar_restart", "data": "initial"},
    }
    transport_helper.publish_message("asya-test-echo", message_before)

    result_before = transport_helper.assert_message_in_queue("asya-happy-end", timeout=10)
    assert result_before is not None, "Initial message failed before sidecar restart"
    logger.info("[+] Message processed successfully before restart")

    logger.info("Step 2: Restart sidecar container")
    assert docker_helper.restart_service("asya-echo-sidecar"), "Failed to restart sidecar"

    logger.info("Step 3: Wait for sidecar to start")
    time.sleep(5)  # Wait for sidecar to start and reconnect

    logger.info("Step 4: Send message after sidecar restart")
    message_after = {
        "id": "test-sidecar-restart-after-1",
        "route": {"actors": ["test-echo"], "current": 0},
        "payload": {"test": "after_sidecar_restart", "data": "reconnected"},
    }
    transport_helper.publish_message("asya-test-echo", message_after)

    result_after = transport_helper.assert_message_in_queue("asya-happy-end", timeout=15)
    assert result_after is not None, "Message failed after sidecar restart - sidecar did not reconnect"

    payload = result_after.get("payload", {})
    assert payload.get("test") == "after_sidecar_restart", \
        f"Wrong payload after reconnect: {payload}"

    logger.info("[+] Sidecar restart reconnection: PASSED")


def test_runtime_crash_during_processing(transport_helper, docker_helper):
    """
    Test sidecar handles runtime crash during message processing.

    Scenario:
    1. Send message to timeout handler (takes 5s)
    2. After 1s, restart runtime container (simulates crash during processing)
    3. Message should fail or retry depending on sidecar behavior
    4. Send new message - should succeed after runtime recovers
    """
    logger.info("=== Testing runtime crash during processing ===")

    logger.info("Step 1: Send slow message (5s sleep)")
    message_slow = {
        "id": "test-crash-during-processing-1",
        "route": {"actors": ["test-timeout"], "current": 0},
        "payload": {"test": "slow_processing", "sleep": 2},
    }
    transport_helper.publish_message("asya-test-timeout", message_slow)

    logger.info("Step 2: Wait 1s then crash runtime during processing")
    time.sleep(1)  # Wait for processing to start
    assert docker_helper.restart_service("asya-timeout-runtime"), "Failed to restart runtime"

    logger.info("Step 3: Wait for runtime to recover")
    assert docker_helper.wait_for_healthy("asya-timeout-runtime", timeout=30), \
        "Runtime did not recover after crash"

    time.sleep(3)  # Wait for sidecar to reconnect

    logger.info("Step 4: Send new message after recovery")
    message_new = {
        "id": "test-after-crash-1",
        "route": {"actors": ["test-timeout"], "current": 0},
        "payload": {"test": "after_crash", "sleep": 0},
    }
    transport_helper.publish_message("asya-test-timeout", message_new)

    result = transport_helper.assert_message_in_queue("asya-happy-end", timeout=15)
    assert result is not None, "Message failed after runtime crash recovery"

    payload = result.get("payload", {})
    assert payload.get("test") == "after_crash", \
        f"Wrong payload after crash recovery: {payload}"

    logger.info("[+] Runtime crash during processing handled gracefully: PASSED")


def test_both_restart_reconnects(transport_helper, docker_helper):
    """
    Test full recovery when both sidecar and runtime restart.

    Scenario:
    1. Send message - should succeed
    2. Restart both runtime and sidecar
    3. Wait for both to become healthy
    4. Send message - should succeed
    """
    logger.info("=== Testing both sidecar and runtime restart ===")

    logger.info("Step 1: Send message before restart")
    message_before = {
        "id": "test-both-restart-before-1",
        "route": {"actors": ["test-echo"], "current": 0},
        "payload": {"test": "before_both_restart"},
    }
    transport_helper.publish_message("asya-test-echo", message_before)

    result_before = transport_helper.assert_message_in_queue("asya-happy-end", timeout=10)
    assert result_before is not None, "Initial message failed"
    logger.info("[+] Message processed successfully before restart")

    logger.info("Step 2: Restart both runtime and sidecar")
    assert docker_helper.restart_service("asya-echo-runtime"), "Failed to restart runtime"
    assert docker_helper.restart_service("asya-echo-sidecar"), "Failed to restart sidecar"

    logger.info("Step 3: Wait for runtime to become healthy")
    assert docker_helper.wait_for_healthy("asya-echo-runtime", timeout=30), \
        "Runtime did not become healthy"

    time.sleep(5)  # Wait for sidecar to start and connect

    logger.info("Step 4: Send message after both restart")
    message_after = {
        "id": "test-both-restart-after-1",
        "route": {"actors": ["test-echo"], "current": 0},
        "payload": {"test": "after_both_restart"},
    }
    transport_helper.publish_message("asya-test-echo", message_after)

    result_after = transport_helper.assert_message_in_queue("asya-happy-end", timeout=15)
    assert result_after is not None, "Message failed after both components restart"

    payload = result_after.get("payload", {})
    assert payload.get("test") == "after_both_restart", \
        f"Wrong payload after reconnect: {payload}"

    logger.info("[+] Both components restart reconnection: PASSED")
