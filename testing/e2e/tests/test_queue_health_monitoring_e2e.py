#!/usr/bin/env python3
"""
E2E Queue Health Monitoring Tests for Asya Framework.

Tests that the operator automatically detects and recreates missing queues
when they are deleted externally (chaos scenarios).

Queue Health Monitoring:
The operator runs a periodic health check every 5 minutes to detect missing queues
and automatically recreate them. This ensures resilience against accidental deletions,
infrastructure failures, or chaos engineering scenarios.

Test Scenarios:
- test_operator_recreates_deleted_actor_queue_e2e: Delete actor queue, verify auto-recreation
- test_operator_recreates_deleted_system_queue_e2e: Delete error-end queue, verify auto-recreation
- test_multiple_queue_deletions_e2e: Delete multiple queues simultaneously

Transport Support:
- ✅ RabbitMQ: Full support
- ✅ SQS: Full support
"""

import logging
import os
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


@pytest.mark.slow
@pytest.mark.chaos
def test_operator_recreates_deleted_actor_queue_e2e(e2e_helper, kubectl):
    """
    E2E Chaos: Test operator recreates deleted actor queue within 5 minutes.

    Scenario:
    1. Verify test-echo AsyncActor exists and queue is created
    2. Delete test-echo queue manually (simulate chaos)
    3. Wait for operator health check cycle (max 6 minutes)
    4. Verify queue is automatically recreated
    5. Verify actor still processes messages correctly

    Expected:
    - Queue deleted successfully
    - Operator detects missing queue within 5 minutes
    - Queue automatically recreated with correct configuration
    - Actor resumes normal operation

    Transport Support: Both RabbitMQ and SQS
    """
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    transport_client = _get_transport_client(transport)

    queue_name = "asya-test-echo"
    namespace = os.getenv("ASYA_NAMESPACE", "asya-e2e")

    logger.info(f"Transport: {transport}, Testing queue: {queue_name}")

    logger.info("[1/5] Ensuring AsyncActor exists and queue is ready")
    result = kubectl.run(f"get asyncactor test-echo -n {namespace}", check=False)
    if result.returncode != 0:
        pytest.skip(f"AsyncActor test-echo not found in namespace {namespace}")

    max_wait = 60
    elapsed = 0
    check_interval = 5
    queue_ready = False

    while elapsed < max_wait:
        queues = transport_client.list_queues()
        if queue_name in queues:
            queue_ready = True
            logger.info(f"[+] Queue ready: {queue_name}")
            break
        logger.info(f"Waiting for queue to be created (elapsed: {elapsed}s / {max_wait}s)")
        time.sleep(check_interval)
        elapsed += check_interval

    if not queue_ready:
        pytest.skip(f"Queue {queue_name} not ready after {max_wait}s - may still be initializing")

    logger.info("[2/5] Deleting queue to simulate chaos scenario")
    transport_client.delete_queue(queue_name)
    logger.info(f"[+] Queue deleted: {queue_name}")

    logger.info("[3/5] Verifying queue is actually deleted")
    queues_after_delete = transport_client.list_queues()
    assert queue_name not in queues_after_delete, f"Queue {queue_name} should be deleted"
    logger.info(f"[+] Queue confirmed deleted: {queue_name}")

    logger.info("[4/5] Waiting for operator health check cycle (max 6 minutes)")
    max_wait = 360
    check_interval = 15
    elapsed = 0
    queue_recreated = False

    while elapsed < max_wait:
        logger.info(f"Checking queue existence (elapsed: {elapsed}s / {max_wait}s)")
        queues = transport_client.list_queues()
        if queue_name in queues:
            queue_recreated = True
            logger.info(f"[+] Queue recreated after {elapsed}s: {queue_name}")
            break

        elapsed += check_interval

    assert queue_recreated, \
        f"Queue {queue_name} was not recreated within {max_wait}s. Operator health check may be disabled."

    logger.info("[5/5] Verifying actor still processes messages after queue recreation")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"data": "chaos-test-recovery"},
    )

    assert response["status"] == "success", "Actor should process messages after queue recreation"
    result = response["result"]
    assert result["payload"]["data"] == "chaos-test-recovery", \
        "Actor should return correct payload after recovery"

    logger.info("[+] Chaos test passed - operator recreated queue and actor recovered")


@pytest.mark.slow
@pytest.mark.chaos
def test_operator_recreates_deleted_system_queue_e2e(e2e_helper, kubectl):
    """
    E2E Chaos: Test operator recreates deleted system queue (error-end).

    Scenario:
    1. Verify error-end AsyncActor exists and queue is created
    2. Delete error-end queue (simulate infrastructure failure)
    3. Wait for operator health check cycle
    4. Verify queue automatically recreated
    5. Verify error handling still works

    Expected:
    - System queue recreated automatically
    - Error handling pipeline remains functional

    Transport Support: Both RabbitMQ and SQS
    """
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    transport_client = _get_transport_client(transport)

    queue_name = "asya-error-end"
    namespace = os.getenv("ASYA_NAMESPACE", "asya-e2e")

    logger.info(f"Transport: {transport}, Testing system queue: {queue_name}")

    logger.info("[1/4] Ensuring error-end AsyncActor exists and queue is ready")
    result = kubectl.run(f"get asyncactor error-end -n {namespace}", check=False)
    if result.returncode != 0:
        pytest.skip(f"AsyncActor error-end not found in namespace {namespace}")

    max_wait = 60
    elapsed = 0
    check_interval = 5
    queue_ready = False

    while elapsed < max_wait:
        queues = transport_client.list_queues()
        if queue_name in queues:
            queue_ready = True
            logger.info(f"[+] System queue ready: {queue_name}")
            break
        logger.info(f"Waiting for system queue to be created (elapsed: {elapsed}s / {max_wait}s)")
        time.sleep(check_interval)
        elapsed += check_interval

    if not queue_ready:
        pytest.skip(f"System queue {queue_name} not ready after {max_wait}s - may still be initializing")

    logger.info("[2/4] Deleting system queue to simulate infrastructure failure")
    transport_client.delete_queue(queue_name)
    logger.info(f"[+] System queue deleted: {queue_name}")

    logger.info("[3/4] Waiting for operator health check to recreate queue")
    max_wait = 360
    check_interval = 15
    elapsed = 0
    queue_recreated = False

    while elapsed < max_wait:
        logger.info(f"Checking queue existence (elapsed: {elapsed}s / {max_wait}s)")
        queues = transport_client.list_queues()
        if queue_name in queues:
            queue_recreated = True
            logger.info(f"[+] System queue recreated after {elapsed}s: {queue_name}")
            break
        time.sleep(check_interval)
        elapsed += check_interval

    assert queue_recreated, \
        f"System queue {queue_name} was not recreated within {max_wait}s"

    logger.info("[4/4] Verifying error handling works after queue recreation")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_error",
        arguments={"should_fail": True},
    )

    assert response["status"] == "success", "Error handling should work after queue recreation"

    logger.info("[+] System queue chaos test passed - error handling functional after recreation")


@pytest.mark.slow
@pytest.mark.chaos
def test_multiple_queue_deletions_e2e(e2e_helper, kubectl):
    """
    E2E Chaos: Test operator handles multiple simultaneous queue deletions.

    Scenario:
    1. Identify multiple actor queues
    2. Delete all queues simultaneously (catastrophic failure)
    3. Wait for operator health check cycle
    4. Verify all queues recreated
    5. Verify all actors functional

    Expected:
    - All queues recreated within one health check cycle
    - All actors resume operation
    - No cascade failures

    Transport Support: Both RabbitMQ and SQS
    """
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    transport_client = _get_transport_client(transport)

    test_queues = [
        "asya-test-echo",
        "asya-test-error",
        "asya-error-end",
    ]
    namespace = os.getenv("ASYA_NAMESPACE", "asya-e2e")

    logger.info(f"Transport: {transport}, Testing multiple queue deletions")

    logger.info("[1/5] Ensuring all AsyncActors exist and queues are ready")
    for actor_name in ["test-echo", "test-error", "error-end"]:
        result = kubectl.run(f"get asyncactor {actor_name} -n {namespace}", check=False)
        if result.returncode != 0:
            pytest.skip(f"AsyncActor {actor_name} not found in namespace {namespace}")

    max_wait = 60
    elapsed = 0
    check_interval = 5
    all_ready = False

    while elapsed < max_wait:
        queues = transport_client.list_queues()
        ready_count = sum(1 for q in test_queues if q in queues)
        if ready_count == len(test_queues):
            all_ready = True
            logger.info(f"[+] All {len(test_queues)} queues ready")
            break
        logger.info(f"Waiting for queues ({ready_count}/{len(test_queues)} ready, elapsed: {elapsed}s / {max_wait}s)")
        time.sleep(check_interval)
        elapsed += check_interval

    if not all_ready:
        pytest.skip(f"Not all queues ready after {max_wait}s - may still be initializing")

    logger.info("[2/5] Deleting all queues simultaneously (catastrophic scenario)")
    for queue_name in test_queues:
        try:
            transport_client.delete_queue(queue_name)
            logger.info(f"[+] Deleted: {queue_name}")
        except Exception as e:
            logger.warning(f"Failed to delete {queue_name}: {e}")

    logger.info("[3/5] Verifying all queues deleted")
    queues_after_delete = transport_client.list_queues()
    for queue_name in test_queues:
        assert queue_name not in queues_after_delete, f"Queue {queue_name} should be deleted"
    logger.info(f"[+] All {len(test_queues)} queues confirmed deleted")

    logger.info("[4/5] Waiting for operator to recreate all queues")
    max_wait = 360
    check_interval = 15
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

        elapsed += check_interval

    assert all_recreated, \
        f"Not all queues recreated within {max_wait}s. " \
        f"Missing: {[q for q in test_queues if q not in queues]}"

    logger.info("[5/5] Verifying actors functional after mass recreation")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"data": "mass-recovery-test"},
    )

    assert response["status"] == "success", "Actors should work after mass queue recreation"

    logger.info("[+] Mass deletion chaos test passed - all queues recreated, actors functional")


@pytest.mark.slow
@pytest.mark.chaos
def test_queue_deletion_during_processing_e2e(e2e_helper, kubectl):
    """
    E2E Chaos: Test queue deletion while actor is processing messages.

    Scenario:
    1. Send message to actor
    2. Delete queue during processing
    3. Wait for operator to recreate queue
    4. Verify message eventually processed

    Expected:
    - Queue recreated automatically
    - Message redelivery works after recreation
    - No data loss for pending messages

    Transport Support: Both RabbitMQ and SQS

    Note: Message might be lost if deleted before processing,
    but queue recreation ensures system recovers.
    """
    transport = os.getenv("ASYA_TRANSPORT", "rabbitmq")
    transport_client = _get_transport_client(transport)

    queue_name = "asya-test-echo"
    namespace = os.getenv("ASYA_NAMESPACE", "asya-e2e")

    logger.info(f"Transport: {transport}, Testing queue deletion during processing")

    logger.info("[1/5] Ensuring AsyncActor exists and queue is ready")
    result = kubectl.run(f"get asyncactor test-echo -n {namespace}", check=False)
    if result.returncode != 0:
        pytest.skip(f"AsyncActor test-echo not found in namespace {namespace}")

    max_wait = 60
    elapsed = 0
    check_interval = 5
    queue_ready = False

    while elapsed < max_wait:
        queues = transport_client.list_queues()
        if queue_name in queues:
            queue_ready = True
            logger.info(f"[+] Queue ready: {queue_name}")
            break
        logger.info(f"Waiting for queue to be created (elapsed: {elapsed}s / {max_wait}s)")
        time.sleep(check_interval)
        elapsed += check_interval

    if not queue_ready:
        pytest.skip(f"Queue {queue_name} not ready after {max_wait}s - may still be initializing")

    logger.info("[2/5] Sending message to actor")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"data": "processing-chaos-test"},
    )
    envelope_id = response["result"]["envelope_id"]
    logger.info(f"[+] Message sent, envelope ID: {envelope_id}")

    logger.info("[3/5] Deleting queue during/after processing")
    transport_client.delete_queue(queue_name)
    logger.info(f"[+] Queue deleted: {queue_name}")

    logger.info("[4/5] Waiting for operator to recreate queue")
    max_wait = 360
    check_interval = 15
    elapsed = 0
    queue_recreated = False

    while elapsed < max_wait:
        queues = transport_client.list_queues()
        if queue_name in queues:
            queue_recreated = True
            logger.info(f"[+] Queue recreated after {elapsed}s: {queue_name}")
            break

        elapsed += check_interval

    assert queue_recreated, f"Queue {queue_name} not recreated within {max_wait}s"

    logger.info("[5/5] Verifying actor can process new messages after recreation")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"data": "post-chaos-test"},
    )

    assert response["status"] == "success", "Actor should process messages after queue recreation"

    logger.info("[+] Processing chaos test passed - queue recreated, actor functional")
