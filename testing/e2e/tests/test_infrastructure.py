#!/usr/bin/env python3
"""
Infrastructure health tests for E2E environment.

These tests verify that the underlying Kubernetes infrastructure is healthy
before running functional E2E tests. They catch pod failures that might not
be detected by functional tests alone.
"""

import logging
import os
import subprocess
import time
from typing import List, Tuple

import pytest

from asya_testing.config import require_env, get_env

log_level = get_env('ASYA_LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

FAILED_STATES = {'CrashLoopBackOff', 'Error', 'ImagePullBackOff', 'ErrImagePull', 'Failed'}

def get_pod_status(namespace: str, label_selector: str) -> List[Tuple[str, str, str, str]]:
    """
    Get pod status for pods matching label selector.

    Returns list of (pod_name, ready_status, phase, reason) tuples.
    The reason field captures CURRENT container waiting reasons like CrashLoopBackOff.
    We only check waiting state, not terminated (lastState), because pods that crashed
    but are now running should not fail this health check.
    """
    result = subprocess.run(
        [
            "kubectl", "get", "pods",
            "-n", namespace,
            "-l", label_selector,
            "-o", "jsonpath={range .items[*]}{.metadata.name}{'|'}{.status.containerStatuses[*].ready}{'|'}{.status.phase}{'|'}{.status.containerStatuses[*].state.waiting.reason}{'\\n'}{end}"
        ],
        capture_output=True,
        text=True,
        check=True
    )

    pods = []
    for line in result.stdout.strip().split('\n'):
        if not line:
            continue
        parts = line.split('|')
        if len(parts) >= 3:
            reason = parts[3] if len(parts) > 3 else ""
            pods.append((parts[0], parts[1], parts[2], reason))

    return pods


def get_pod_logs(namespace: str, pod_name: str, container: str = None, tail: int = 20) -> str:
    """Get recent logs from a pod container."""
    cmd = ["kubectl", "logs", pod_name, "-n", namespace, f"--tail={tail}"]
    if container:
        cmd.extend(["-c", container])

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.stdout


@pytest.mark.core
@pytest.mark.order(1)
def test_actor_pods_healthy():
    """
    Test that actor infrastructure is ready (deployments and KEDA ScaledObjects exist).

    With KEDA scale-to-zero, pods won't exist until messages arrive, so we check:
    1. AsyncActor CRDs exist
    2. Deployments exist (even if scaled to 0)
    3. KEDA ScaledObjects exist and are ready
    4. Any running pods are healthy (no CrashLoopBackOff)
    """
    logger.info("Testing actor infrastructure health")

    namespace = require_env("NAMESPACE")

    logger.info("Checking AsyncActor CRDs...")
    result = subprocess.run(
        ["kubectl", "get", "asyncactors", "-n", namespace, "-o", "jsonpath={.items[*].metadata.name}"],
        capture_output=True,
        text=True,
        check=True
    )
    actors = result.stdout.strip().split()
    assert len(actors) > 0, "No AsyncActor CRDs found"
    logger.info(f"Found {len(actors)} AsyncActor CRDs: {', '.join(actors)}")

    logger.info("Checking at least one deployment exists...")
    result = subprocess.run(
        ["kubectl", "get", "deployment", "test-echo", "-n", namespace, "-o", "jsonpath={.metadata.name}"],
        capture_output=True,
        text=True,
        check=False
    )

    if result.returncode == 0 and result.stdout.strip():
        logger.info(f"Found deployment: {result.stdout.strip()}")
    else:
        logger.warning("test-echo deployment not found - Crossplane may still be creating deployments")

    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")

    logger.info("Checking KEDA ScaledObjects...")
    result = subprocess.run(
        ["kubectl", "get", "scaledobjects", "-n", namespace, "-o", "jsonpath={range .items[*]}{.metadata.name}{'|'}{.status.conditions[?(@.type=='Ready')].status}{'\\n'}{end}"],
        capture_output=True,
        text=True,
        check=True
    )
    scaled_objects = []
    for line in result.stdout.strip().split('\n'):
        if not line:
            continue
        parts = line.split('|')
        if len(parts) >= 2:
            scaled_objects.append((parts[0], parts[1]))

    assert len(scaled_objects) > 0, "No KEDA ScaledObjects found"
    logger.info(f"Found {len(scaled_objects)} KEDA ScaledObjects")

    for so_name, ready_status in scaled_objects:
        if transport == "pubsub":
            # KEDA gcp-pubsub scaler cannot query the emulator for metrics,
            # so ScaledObjects exist but show TriggerError (Ready=False).
            logger.info(f"  ScaledObject {so_name}: Ready={ready_status} (emulator mode, TriggerError expected)")
        else:
            assert ready_status == "True", f"ScaledObject {so_name} not ready (status={ready_status})"
            logger.info(f"  ScaledObject {so_name}: Ready")

    logger.info("Checking any running pods for health issues...")
    label = "app.kubernetes.io/component=actor"
    pods = get_pod_status(namespace, label)

    if not pods:
        logger.info("[+] No actor pods running (KEDA scaled to zero) - this is expected and healthy")
    else:
        logger.info(f"Found {len(pods)} running actor pod(s), checking for failures...")
        terminal_failures = []

        for pod_name, ready_status, phase, reason in pods:
            if "test-timeout" in pod_name:
                logger.info(f"  Skipping {pod_name} (timeout test actor - expected to crash)")
                continue

            if reason and any(failed_state in reason for failed_state in FAILED_STATES):
                terminal_failures.append((pod_name, ready_status, phase, reason))
                logger.error(
                    f"  Pod {pod_name} in terminal failure state: {reason}, phase={phase}"
                )

        if terminal_failures:
            logger.error(f"\n{'='*60}")
            logger.error("TERMINAL POD FAILURES DETECTED")
            logger.error(f"{'='*60}")
            _log_pod_diagnostics(namespace, terminal_failures)
            pytest.fail(
                f"{len(terminal_failures)} pod(s) in terminal failure state. "
                f"Check logs above for details."
            )

        logger.info(f"[+] All checked actor pod(s) are healthy (skipped test-timeout)")

    logger.info("[+] Actor infrastructure is healthy")


def _log_pod_diagnostics(namespace: str, failed_pods: List[Tuple[str, str, str, str]]) -> None:
    """Log diagnostic information for failed pods."""
    for pod_name, ready_status, phase, reason in failed_pods:
        logger.error(f"\nFailed pod: {pod_name}")
        logger.error(f"  Ready status: {ready_status}")
        logger.error(f"  Phase: {phase}")
        logger.error(f"  Reason: {reason or 'N/A'}")

        logger.error("  Runtime container logs (last 20 lines):")
        runtime_logs = get_pod_logs(namespace, pod_name, "asya-runtime", tail=20)
        for line in runtime_logs.split('\n'):
            if line.strip():
                logger.error(f"    {line}")

        logger.error("  Sidecar container logs (last 20 lines):")
        sidecar_logs = get_pod_logs(namespace, pod_name, "sidecar", tail=20)
        for line in sidecar_logs.split('\n'):
            if line.strip():
                logger.error(f"    {line}")


@pytest.mark.core
@pytest.mark.order(2)
def test_injector_pod_healthy():
    """Test that the injector pod is running."""
    logger.info("Testing injector pod health")

    namespace = require_env("SYSTEM_NAMESPACE")
    label = "app.kubernetes.io/name=asya-injector"

    pods = get_pod_status(namespace, label)

    assert len(pods) > 0, "No injector pods found"

    for pod_name, ready_status, phase, reason in pods:
        ready_containers = ready_status.split()
        total_ready = sum(1 for r in ready_containers if r == "true")
        total_containers = len(ready_containers)

        assert phase == "Running", f"Injector pod {pod_name} not Running (phase={phase}, reason={reason})"
        assert total_ready == total_containers, (
            f"Injector pod {pod_name} not all containers ready "
            f"({total_ready}/{total_containers})"
        )

    logger.info(f"[+] Injector pod is healthy")


@pytest.mark.core
@pytest.mark.order(2)
def test_crossplane_pods_healthy():
    """Test that Crossplane provider pods are running."""
    logger.info("Testing Crossplane provider pod health")

    namespace = "crossplane-system"
    label = "pkg.crossplane.io/revision"

    pods = get_pod_status(namespace, label)

    assert len(pods) > 0, "No Crossplane provider pods found"

    healthy_count = 0
    for pod_name, ready_status, phase, reason in pods:
        if phase == "Running":
            healthy_count += 1
            logger.info(f"  Crossplane pod {pod_name}: Running")
        else:
            logger.warning(f"  Crossplane pod {pod_name}: {phase} (reason={reason})")

    assert healthy_count > 0, "No healthy Crossplane provider pods found"
    logger.info(f"[+] {healthy_count} Crossplane provider pod(s) healthy")


@pytest.mark.core
@pytest.mark.order(3)
def test_gateway_pod_healthy():
    """Test that the gateway pod is running."""
    logger.info("Testing gateway pod health")

    namespace = require_env("NAMESPACE")
    label = "app.kubernetes.io/name=asya-gateway"

    all_pods = get_pod_status(namespace, label)

    running_pods = [(name, ready, phase, reason) for name, ready, phase, reason in all_pods if phase == "Running"]

    assert len(running_pods) > 0, "No running gateway pods found"

    for pod_name, ready_status, phase, reason in running_pods:
        ready_containers = ready_status.split()
        total_ready = sum(1 for r in ready_containers if r == "true")
        total_containers = len(ready_containers)

        assert total_ready == total_containers, (
            f"Gateway pod {pod_name} not all containers ready "
            f"({total_ready}/{total_containers})"
        )

    logger.info(f"[+] Gateway pod is healthy")
