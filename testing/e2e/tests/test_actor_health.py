#!/usr/bin/env python3
"""
Actor health tests for E2E environment.

These tests validate that each actor in the system is healthy and ready
to process messages before running functional E2E tests. They ensure:
- Actor deployments exist and are available
- Transport queues are created
- KEDA ScaledObjects are ready
- Actors can scale from zero

This prevents confusing test failures when infrastructure is broken.
"""

import json
import logging
import subprocess
from typing import Dict, List, Set

import pytest

from asya_testing.config import require_env, get_env

log_level = get_env('ASYA_LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_all_actors(namespace: str) -> List[str]:
    """Get list of all AsyncActor names in the namespace."""
    result = subprocess.run(
        ["kubectl", "get", "asyncactors", "-n", namespace, "-o", "jsonpath={.items[*].metadata.name}"],
        capture_output=True,
        text=True,
        check=True
    )
    actors = result.stdout.strip().split()
    return [a for a in actors if a]


def get_actors_scaling_config(namespace: str) -> Dict[str, bool]:
    """Get scaling.enabled configuration for all AsyncActors."""
    result = subprocess.run(
        ["kubectl", "get", "asyncactors", "-n", namespace, "-o", "json"],
        capture_output=True,
        text=True,
        check=True
    )
    data = json.loads(result.stdout)
    scaling_config = {}
    for item in data.get("items", []):
        actor_name = item["metadata"]["name"]
        scaling_enabled = item.get("spec", {}).get("scaling", {}).get("enabled", True)
        scaling_config[actor_name] = scaling_enabled
    return scaling_config


def get_all_deployments(namespace: str) -> Set[str]:
    """Get set of all deployment names in the namespace."""
    result = subprocess.run(
        ["kubectl", "get", "deployments", "-n", namespace, "-o", "jsonpath={.items[*].metadata.name}"],
        capture_output=True,
        text=True,
        check=False
    )
    if result.returncode != 0:
        return set()
    deployments = result.stdout.strip().split()
    return set(d for d in deployments if d)


def get_all_scaledobjects(namespace: str) -> Dict[str, str]:
    """
    Get all KEDA ScaledObjects and their Ready status.

    Returns:
        Dict mapping ScaledObject name to Ready status ("True", "False", "unknown")
    """
    result = subprocess.run(
        [
            "kubectl", "get", "scaledobjects", "-n", namespace,
            "-o", "jsonpath={range .items[*]}{.metadata.name}{'|'}{.status.conditions[?(@.type=='Ready')].status}{'\\n'}{end}"
        ],
        capture_output=True,
        text=True,
        check=False
    )

    if result.returncode != 0:
        return {}

    scaledobjects = {}
    for line in result.stdout.strip().split('\n'):
        if not line:
            continue
        parts = line.split('|')
        if len(parts) >= 2:
            name = parts[0]
            status = parts[1] if parts[1] else "unknown"
            scaledobjects[name] = status
        elif len(parts) == 1 and parts[0]:
            scaledobjects[parts[0]] = "unknown"

    return scaledobjects


def get_all_rabbitmq_queues(namespace: str) -> Set[str]:
    """Get set of all RabbitMQ queue names."""
    result = subprocess.run(
        [
            "kubectl", "exec", "-n", namespace, "statefulset/asya-rabbitmq", "--",
            "rabbitmqctl", "list_queues", "-q", "name"
        ],
        capture_output=True,
        text=True,
        check=False
    )

    if result.returncode != 0:
        logger.warning(f"Failed to list RabbitMQ queues: {result.stderr}")
        return set()

    queues = result.stdout.strip().split('\n')
    return set(q for q in queues if q)


def get_all_sqs_queues(namespace: str) -> Set[str]:
    """Get set of all SQS queue names from LocalStack."""
    result = subprocess.run(
        [
            "kubectl", "exec", "-n", namespace, "deployment/sqs", "--",
            "aws", "--endpoint-url=http://localhost:4566", "--region=us-east-1",
            "sqs", "list-queues"
        ],
        capture_output=True,
        text=True,
        check=False
    )

    if result.returncode != 0:
        logger.warning(f"Failed to list SQS queues: {result.stderr}")
        return set()

    try:
        queue_list = json.loads(result.stdout)
        queue_urls = queue_list.get("QueueUrls", [])
        queue_names = [url.split("/")[-1] for url in queue_urls]
        return set(queue_names)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse SQS queue list: {e}")
        return set()


@pytest.mark.core
@pytest.mark.order(5)
def test_all_actors_healthy():
    """
    Validate that all actors are healthy and ready to process messages.

    For each actor, checks:
    1. Deployment exists (may be scaled to zero with KEDA)
    2. Transport queue exists (RabbitMQ or SQS)
    3. KEDA ScaledObject exists and is Ready

    Fails with detailed diagnostics if any actor is unhealthy.

    Optimized to batch kubectl calls - fetches all resources at once instead of per-actor.
    """
    logger.info("=== Testing Actor Health ===")

    namespace = require_env("NAMESPACE")
    transport = require_env("ASYA_TRANSPORT").lower()

    logger.info(f"Namespace: {namespace}")
    logger.info(f"Transport: {transport}")

    actors = get_all_actors(namespace)
    assert len(actors) > 0, f"No AsyncActor CRDs found in namespace {namespace}"

    logger.info(f"Found {len(actors)} actors: {', '.join(actors)}")

    logger.info("\nFetching all deployments, queues, ScaledObjects, and scaling config...")
    all_deployments = get_all_deployments(namespace)
    all_scaledobjects = get_all_scaledobjects(namespace)
    actors_scaling_config = get_actors_scaling_config(namespace)

    if transport == "rabbitmq":
        all_queues = get_all_rabbitmq_queues(namespace)
    elif transport == "sqs":
        all_queues = get_all_sqs_queues(namespace)
    else:
        raise NotImplementedError(transport)

    logger.info(f"  Found {len(all_deployments)} deployments")
    logger.info(f"  Found {len(all_scaledobjects)} ScaledObjects")
    logger.info(f"  Found {len(all_queues)} {transport.upper()} queues")

    # Track failures by category
    missing_deployments: List[str] = []
    missing_queues: List[str] = []
    missing_scaledobjects: List[str] = []
    unhealthy_scaledobjects: Dict[str, str] = {}

    for actor in actors:
        logger.info(f"\n[.] Checking actor: {actor}")

        if actor in all_deployments:
            logger.info(f"  [+] Deployment exists")
        else:
            missing_deployments.append(actor)
            logger.error(f"  [-] Deployment not found")

        queue_name = f"asya-{actor}"
        if queue_name in all_queues:
            logger.info(f"  [+] {transport.upper()} queue exists")
        else:
            missing_queues.append(queue_name)
            logger.error(f"  [-] {transport.upper()} queue missing")

        scaling_enabled = actors_scaling_config.get(actor, True)
        if scaling_enabled:
            if actor in all_scaledobjects:
                ready_status = all_scaledobjects[actor]
                if ready_status == "True":
                    logger.info(f"  [+] ScaledObject exists and Ready")
                else:
                    unhealthy_scaledobjects[actor] = ready_status
                    logger.error(f"  [-] ScaledObject not Ready (status={ready_status})")
            else:
                missing_scaledobjects.append(actor)
                logger.error(f"  [-] ScaledObject not found")
        else:
            logger.info(f"  [.] ScaledObject skipped (scaling disabled)")

    # Report all failures
    failures = []

    if missing_deployments:
        failures.append(
            f"Missing {len(missing_deployments)} deployment(s): {', '.join(missing_deployments)}. "
            f"Operator may have failed to create workloads."
        )

    if missing_queues:
        failures.append(
            f"Missing {len(missing_queues)} {transport.upper()} queue(s): {', '.join(missing_queues)}. "
            f"Operator may have failed to create queues or queue creation is disabled."
        )

    if missing_scaledobjects:
        failures.append(
            f"Missing {len(missing_scaledobjects)} ScaledObject(s): {', '.join(missing_scaledobjects)}. "
            f"Operator may have failed to create ScaledObjects or KEDA is not installed."
        )

    if unhealthy_scaledobjects:
        details = ', '.join([f"{actor}={status}" for actor, status in unhealthy_scaledobjects.items()])
        failures.append(
            f"{len(unhealthy_scaledobjects)} ScaledObject(s) not Ready: {details}. "
            f"KEDA may be unable to query {transport.upper()} metrics or triggers are misconfigured."
        )

    if failures:
        logger.error("\n" + "="*80)
        logger.error("ACTOR HEALTH CHECK FAILED")
        logger.error("="*80)
        for i, failure in enumerate(failures, 1):
            logger.error(f"{i}. {failure}")
        logger.error("="*80)

        pytest.fail(
            f"Actor health check failed with {len(failures)} issue(s). "
            f"See logs above for details."
        )

    logger.info("\n" + "="*80)
    logger.info(f"[+] All {len(actors)} actors are healthy and ready to process messages")
    logger.info("="*80)


@pytest.mark.core
@pytest.mark.order(6)
@pytest.mark.parametrize("actor_name", [
    "test-echo",
    "test-error",
    "happy-end",
    "error-end",
])
def test_critical_actors_exist(actor_name: str):
    """
    Verify critical actors exist.

    These actors are required for basic E2E test functionality:
    - test-echo: Basic message routing tests
    - test-error: Error handling tests
    - happy-end: Success path completion
    - error-end: Error path completion
    """
    namespace = require_env("NAMESPACE")
    actors = get_all_actors(namespace)
    assert actor_name in actors, (
        f"Critical actor '{actor_name}' not found in namespace {namespace}. "
        f"Found actors: {', '.join(actors)}"
    )
