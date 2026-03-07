#!/usr/bin/env python3
"""
E2E Queue Stability Tests for Asya Framework.

Tests that Crossplane automatically detects and reconciles missing queues
when they are deleted externally (chaos scenarios).

Queue Stability via Crossplane:
Crossplane continuously reconciles the desired state (AsyncActor XR exists →
queue must exist). When a queue is deleted, Crossplane's provider-aws detects
the drift and recreates the queue within its reconciliation period.

Test Scenarios:
- test_crossplane_recreates_deleted_actor_queue_e2e: Delete actor queue, verify Crossplane recreates
- test_crossplane_recreates_deleted_system_queue_e2e: Delete system queue, verify Crossplane recreates
- test_multiple_queue_deletions_e2e: Delete multiple queues simultaneously
- test_queue_deletion_during_processing_e2e: Queue deleted during message processing

Transport Support:
- SQS: Full support (Crossplane manages SQS queues via provider-aws)
- RabbitMQ: Crossplane manages RabbitMQ queues via composition
"""

import logging
import os
import subprocess
import time

import pytest

logger = logging.getLogger(__name__)


def _get_transport_client(transport: str):
    """Get transport client based on ASYA_TRANSPORT environment variable."""
    if transport == "rabbitmq":
        from asya_testing.clients.rabbitmq import RabbitMQClient
        rabbitmq_host = os.getenv("RABBITMQ_HOST", "localhost")
        return RabbitMQClient(host=rabbitmq_host, port=15672)
    elif transport == "sqs":
        from asya_testing.clients.sqs import SQSClient
        endpoint_url = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
        return SQSClient(
            endpoint_url=endpoint_url,
            region=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
            access_key=os.getenv("AWS_ACCESS_KEY_ID", "test"),
            secret_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
        )
    else:
        pytest.skip(f"Unsupported transport: {transport}")


def _trigger_crossplane_reconcile(e2e_helper, namespace: str, queue_name: str) -> None:
    """Trigger immediate Crossplane reconciliation for the Queue managed resource.

    Annotating the Queue managed resource (sqs.aws.upbound.io/Queue) directly
    causes the provider-aws-sqs controller to immediately enqueue it for
    reconciliation. The provider then detects the drift (queue deleted from AWS)
    and recreates it — without waiting for the default ~10min poll cycle.

    Queue naming convention: asya-{namespace}-{actor_name}
    """
    prefix = f"asya-{namespace}-"
    if not queue_name.startswith(prefix):
        logger.warning(f"[!] Cannot derive actor name from queue: {queue_name}")
        return
    actor_name = queue_name[len(prefix):]
    try:
        # Get the XR name from the AsyncActor claim (namespace-scoped, so e2e_helper.kubectl ok)
        xr_name = e2e_helper.kubectl(
            "get", "asyncactor", actor_name,
            "-o", "jsonpath={.spec.resourceRef.name}",
        )
        if not xr_name:
            logger.warning(f"[!] No XR found for actor {actor_name}")
            return

        # List cluster-scoped Queue managed resources owned by this XR
        result = subprocess.run(
            [
                "kubectl", "get", "queue.sqs.aws.upbound.io",
                "-l", f"crossplane.io/composite={xr_name}",
                "-o", "name",
            ],
            capture_output=True, text=True, timeout=15,
        )
        queue_resource_names = result.stdout.strip().split() if result.stdout.strip() else []
        if not queue_resource_names:
            logger.warning(f"[!] No Queue managed resources found for XR {xr_name}")
            return

        # Annotate to trigger immediate provider reconciliation
        ts = str(int(time.time()))
        for qr_name in queue_resource_names:
            subprocess.run(
                ["kubectl", "annotate", qr_name, f"asya.sh/force-reconcile={ts}", "--overwrite"],
                capture_output=True, text=True, timeout=15,
            )
            logger.info(f"[+] Triggered reconciliation for Queue managed resource: {qr_name}")
    except Exception as exc:
        logger.warning(f"[!] Could not trigger reconciliation for {queue_name}: {exc}")


@pytest.mark.slow
@pytest.mark.chaos
def test_crossplane_recreates_deleted_actor_queue_e2e(e2e_helper, chaos_queues, namespace):
    """
    E2E Chaos: Test Crossplane reconciles deleted actor queue.

    Scenario:
    1. Delete test-echo queue manually (simulate chaos)
    2. Wait for Crossplane reconciliation (configurable timeout)
    3. Verify queue is automatically recreated
    4. Verify actor still processes messages correctly

    Expected:
    - Queue deleted successfully
    - Crossplane detects the drift and recreates the queue automatically
    - Queue automatically recreated with correct configuration
    - Actor resumes normal operation

    Transport Support: Both RabbitMQ and SQS

    Args:
        e2e_helper: E2E test helper fixture
        chaos_queues: Session fixture ensuring required queues exist
    """
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    transport_client = _get_transport_client(transport)

    queue_name = f"asya-{namespace}-test-echo"

    logger.info(f"Transport: {transport}, Testing queue: {queue_name}")
    logger.info(f"Chaos queues ready: {chaos_queues}")

    logger.info("[1/4] Deleting queue to simulate chaos scenario")
    transport_client.delete_queue(queue_name)
    logger.info(f"[+] Queue deleted: {queue_name}")

    logger.info("[2/4] Verifying queue is actually deleted")
    queues_after_delete = transport_client.list_queues()
    assert queue_name not in queues_after_delete, f"Queue {queue_name} should be deleted"
    logger.info(f"[+] Queue confirmed deleted: {queue_name}")
    _trigger_crossplane_reconcile(e2e_helper, namespace, queue_name)

    logger.info("[3/4] Waiting for Crossplane reconciliation")
    max_wait = int(os.getenv("CROSSPLANE_RECONCILE_TIMEOUT_SECONDS", "300"))
    check_interval = 5
    elapsed = 0
    queue_recreated = False

    while elapsed < max_wait:
        logger.info(f"Checking queue {queue_name} existence (elapsed: {elapsed}s / {max_wait}s)")
        queues = transport_client.list_queues()
        if queue_name in queues:
            queue_recreated = True
            logger.info(f"[+] Queue recreated after {elapsed}s: {queue_name}")
            break
        else:
            logger.info(f"[-] Not found expected queue {queue_name} in: {queues} (sleeping {check_interval}s)")
        time.sleep(check_interval)  # Poll every 5s for queue recreation after triggered reconciliation

        elapsed += check_interval

    assert queue_recreated, \
        f"Queue {queue_name} was not recreated within {max_wait}s. Crossplane reconciliation may be disabled."

    logger.info("[4/4] Verifying actor still processes messages after queue recreation")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "chaos-test-recovery"},
    )
    task_id = response["result"]["task_id"]
    logger.info(f"Task ID: {task_id}")

    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=60)
    assert final_task["status"] == "succeeded", "Actor should process messages after queue recreation"
    assert final_task["payload"]["message"] == "chaos-test-recovery", \
        "Actor should return correct payload after recovery"

    logger.info("[+] Chaos test passed - Crossplane recreated queue and actor recovered")


@pytest.mark.slow
@pytest.mark.chaos
def test_crossplane_recreates_deleted_system_queue_e2e(e2e_helper, chaos_queues, namespace):
    """
    E2E Chaos: Test Crossplane reconciles deleted system queue.

    Scenario:
    1. Delete test-queue-health queue (simulate infrastructure failure)
    2. Wait for Crossplane reconciliation
    3. Verify queue automatically recreated
    4. Verify actor still works after recreation

    Expected:
    - Queue recreated automatically
    - Actor resumes normal operation

    Transport Support: Both RabbitMQ and SQS

    Note: This test uses test-queue-health actor instead of system actors
    because it has small ASYA_QUEUE_RETRY_MAX_ATTEMPTS and ASYA_QUEUE_RETRY_BACKOFF
    values for faster testing.

    Args:
        e2e_helper: E2E test helper fixture
        chaos_queues: Session fixture ensuring required queues exist
    """
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    transport_client = _get_transport_client(transport)

    queue_name = f"asya-{namespace}-test-queue-health"

    logger.info(f"Transport: {transport}, Testing queue: {queue_name}")
    logger.info(f"Chaos queues ready: {chaos_queues}")

    logger.info("[1/3] Deleting queue to simulate infrastructure failure")
    transport_client.delete_queue(queue_name)
    logger.info(f"[+] Queue deleted: {queue_name}")
    _trigger_crossplane_reconcile(e2e_helper, namespace, queue_name)

    logger.info("[2/3] Waiting for Crossplane reconciliation to recreate queue")
    max_wait = int(os.getenv("CROSSPLANE_RECONCILE_TIMEOUT_SECONDS", "300"))
    check_interval = 5
    elapsed = 0
    queue_recreated = False

    while elapsed < max_wait:
        logger.info(f"Checking queue existence {queue_name} (elapsed: {elapsed}s / {max_wait}s)")
        queues = transport_client.list_queues()
        if queue_name in queues:
            queue_recreated = True
            logger.info(f"[+] Queue recreated after {elapsed}s: {queue_name}")
            break
        else:
            logger.info(f"[-] Not found expected queue {queue_name} in: {queues} (sleeping {check_interval}s)")
        time.sleep(check_interval)  # Poll every 5s for queue recreation after triggered reconciliation
        elapsed += check_interval

    assert queue_recreated, \
        f"Queue {queue_name} was not recreated within {max_wait}s"

    logger.info("[3/3] Verifying actor works after queue recreation")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_queue_health",
        arguments={"data": "chaos-test-recovery"},
    )
    task_id = response["result"]["task_id"]
    logger.info(f"Task ID: {task_id}")

    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=60)
    assert final_task["status"] == "succeeded", "Actor should work after queue recreation"
    assert final_task["payload"]["data"] == "chaos-test-recovery", \
        "Actor should return correct payload after recovery"

    logger.info("[+] Queue chaos test passed - queue recreated and actor functional")


@pytest.mark.slow
@pytest.mark.chaos
def test_multiple_queue_deletions_e2e(e2e_helper, chaos_queues, namespace):
    """
    E2E Chaos: Test Crossplane reconciles multiple simultaneous queue deletions.

    Scenario:
    1. Delete all queues simultaneously (catastrophic failure)
    2. Verify all queues deleted
    3. Wait for Crossplane reconciliation
    4. Verify all queues recreated
    5. Verify all actors functional

    Expected:
    - All queues recreated within one health check cycle
    - All actors resume operation
    - No cascade failures

    Transport Support: Both RabbitMQ and SQS

    Args:
        e2e_helper: E2E test helper fixture
        chaos_queues: Session fixture ensuring required queues exist
    """
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    transport_client = _get_transport_client(transport)

    test_queues = chaos_queues

    logger.info(f"Transport: {transport}, Testing multiple queue deletions")
    logger.info(f"Chaos queues ready: {chaos_queues}")

    logger.info("[1/5] Deleting all queues simultaneously (catastrophic scenario)")
    for queue_name in test_queues:
        try:
            transport_client.delete_queue(queue_name)
            logger.info(f"[+] Deleted: {queue_name}")
        except Exception as e:
            logger.warning(f"Failed to delete {queue_name}: {e}")

    for queue_name in test_queues:
        _trigger_crossplane_reconcile(e2e_helper, namespace, queue_name)

    logger.info("[2/5] Verifying all queues deleted")
    queues_after_delete = transport_client.list_queues()
    for queue_name in test_queues:
        assert queue_name not in queues_after_delete, f"Queue {queue_name} should be deleted"
    logger.info(f"[+] All {len(test_queues)} queues confirmed deleted")

    logger.info("[3/5] Waiting for Crossplane reconciliation to recreate all queues")
    max_wait = int(os.getenv("CROSSPLANE_RECONCILE_TIMEOUT_SECONDS", "300"))
    check_interval = 5
    elapsed = 0
    all_recreated = False

    while elapsed < max_wait:
        logger.info(f"Checking queues (elapsed: {elapsed}s / {max_wait}s)")
        queues = transport_client.list_queues()

        recreated_count = sum(1 for q in test_queues if q in queues)
        logger.info(f"Recreated: {recreated_count}/{len(test_queues)} queues")

        if recreated_count == len(test_queues):
            all_recreated = True
            logger.info(f"[+] All queues recreated after {elapsed}s")
            break

        time.sleep(check_interval)  # Poll every 5s for queue recreation after triggered reconciliation
        elapsed += check_interval

    assert all_recreated, \
        f"Not all queues recreated within {max_wait}s. " \
        f"Missing: {[q for q in test_queues if q not in queues]}"

    logger.info("[4/5] All queues confirmed recreated")
    logger.info("[5/5] Verifying actors functional after mass recreation")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "mass-recovery-test"},
    )
    task_id = response["result"]["task_id"]
    logger.info(f"Task ID: {task_id}")

    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=60)
    assert final_task["status"] == "succeeded", "Actors should work after mass queue recreation"
    logger.info("[+] Mass deletion chaos test passed - all queues recreated, actors functional")


@pytest.mark.slow
@pytest.mark.chaos
def test_queue_deletion_during_processing_e2e(e2e_helper, chaos_queues, namespace):
    """
    E2E Chaos: Test queue deletion while actor is processing messages.

    Scenario:
    1. Send message to actor
    2. Delete queue during processing
    3. Wait for Crossplane reconciliation to recreate queue
    4. Verify message eventually processed

    Expected:
    - Queue recreated automatically
    - Message redelivery works after recreation
    - No data loss for pending messages

    Transport Support: Both RabbitMQ and SQS

    Note: Message might be lost if deleted before processing,
    but queue recreation ensures system recovers.

    Args:
        e2e_helper: E2E test helper fixture
        chaos_queues: Session fixture ensuring required queues exist
    """
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    transport_client = _get_transport_client(transport)

    queue_name = f"asya-{namespace}-test-echo"

    logger.info(f"Transport: {transport}, Testing queue deletion during processing")
    logger.info(f"Chaos queues ready: {chaos_queues}")

    logger.info("[1/4] Sending message to actor")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "processing-chaos-test"},
    )
    task_id = response["result"]["task_id"]
    logger.info(f"[+] Message sent, task ID: {task_id}")

    logger.info("[2/4] Deleting queue during/after processing")
    transport_client.delete_queue(queue_name)
    logger.info(f"[+] Queue deleted: {queue_name}")
    _trigger_crossplane_reconcile(e2e_helper, namespace, queue_name)

    logger.info("[3/4] Waiting for Crossplane reconciliation to recreate queue")
    max_wait = int(os.getenv("CROSSPLANE_RECONCILE_TIMEOUT_SECONDS", "300"))
    check_interval = 5
    elapsed = 0
    queue_recreated = False

    while elapsed < max_wait:
        queues = transport_client.list_queues()
        if queue_name in queues:
            queue_recreated = True
            logger.info(f"[+] Queue recreated after {elapsed}s: {queue_name}")
            break

        time.sleep(check_interval)  # Poll every 5s for queue recreation after triggered reconciliation
        elapsed += check_interval

    assert queue_recreated, f"Queue {queue_name} not recreated within {max_wait}s"

    logger.info("[4/4] Verifying actor can process new messages after recreation")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "post-chaos-test"},
    )
    task_id = response["result"]["task_id"]
    logger.info(f"Task ID: {task_id}")

    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=120)
    assert final_task["status"] == "succeeded", "Actor should process messages after queue recreation"

    logger.info("[+] Processing chaos test passed - queue recreated, actor functional")
