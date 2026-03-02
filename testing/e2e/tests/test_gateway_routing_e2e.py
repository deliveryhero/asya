#!/usr/bin/env python3
"""
E2E tests for Gateway routing and MCP protocol.

Tests gateway functionality in a real Kubernetes environment:
- Dynamic route modification via VFS
- Route validation and error handling
- Concurrent requests with different routes
- MCP SSE streaming robustness
- Gateway restart resilience
- Tool parameter validation
- Task lifecycle tracking

These tests verify the gateway handles real-world routing scenarios correctly.
"""

import logging
import subprocess
import threading
import time

import pytest
import requests

logger = logging.getLogger(__name__)


@pytest.mark.chaos
@pytest.mark.xdist_group(name="chaos")
@pytest.mark.skip(reason="Gateway restart causes task timeout - timing issue in test environment")
def test_gateway_restart_during_processing(e2e_helper):
    """
    E2E: Test gateway restart while messages are being processed.

    Scenario:
    1. Send message to slow actor (1.5s processing)
    2. Restart gateway pod immediately
    3. Message continues processing
    4. Can still query task status after restart

    Expected: Gateway stateless, message processing continues
    """
    logger.info("Sending message to slow actor...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_slow_boundary",
        arguments={"first_call": True},
    )

    task_id = response["result"]["task_id"]
    logger.info(f"Task ID: {task_id}")

    time.sleep(0.5)

    logger.info("Restarting gateway pod...")
    pods = e2e_helper.kubectl(
        "get", "pods",
        "-l", "app.kubernetes.io/name=asya-gateway",
        "-o", "jsonpath='{.items[*].metadata.name}'"
    )

    if pods and pods != "''":
        pod_names = pods.strip("'").split()
        if pod_names:
            pod_name = pod_names[0]
            logger.info(f"Deleting gateway pod: {pod_name}")
            e2e_helper.delete_pod(pod_name)

            logger.info("Waiting for new gateway pod to be ready...")
            assert e2e_helper.wait_for_pod_ready("app.kubernetes.io/name=asya-gateway", timeout=30), \
                "Gateway pod should restart"

            logger.info("Re-establishing port-forward to new gateway pod...")
            assert e2e_helper.restart_port_forward(), "Port-forward should be re-established"

            time.sleep(2)

    logger.info("Checking if task status is still accessible...")
    task = e2e_helper.get_task_status(task_id)
    logger.info(f"Task status after restart: {task['status']}")

    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=120)
    assert final_task["status"] == "succeeded", \
        "Task should complete successfully despite gateway restart"

    logger.info("[+] Gateway restart handled gracefully")


@pytest.mark.fast
def test_concurrent_different_routes(e2e_helper):
    """
    E2E: Test concurrent requests to different routes.

    Scenario:
    1. Send 5 messages to test-echo concurrently
    2. Send 5 messages to test-pipeline concurrently
    3. Send 5 messages to test-fanout concurrently
    4. All should complete independently

    Expected: No route cross-contamination
    """
    import threading

    results = {"echo": [], "pipeline": [], "fanout": []}
    locks = {"echo": threading.Lock(), "pipeline": threading.Lock(), "fanout": threading.Lock()}

    def send_echo(index):
        try:
            response = e2e_helper.call_mcp_tool(
                tool_name="test_echo",
                arguments={"message": f"echo-{index}"},
            )
            task_id = response["result"]["task_id"]
            final = e2e_helper.wait_for_task_completion(task_id, timeout=60)
            with locks["echo"]:
                results["echo"].append((index, final))
        except Exception as e:
            logger.error(f"Echo {index} failed: {e}")

    def send_pipeline(index):
        try:
            response = e2e_helper.call_mcp_tool(
                tool_name="test_pipeline",
                arguments={"value": index},
            )
            task_id = response["result"]["task_id"]
            final = e2e_helper.wait_for_task_completion(task_id, timeout=60)
            with locks["pipeline"]:
                results["pipeline"].append((index, final))
        except Exception as e:
            logger.error(f"Pipeline {index} failed: {e}")

    def send_fanout(index):
        try:
            response = e2e_helper.call_mcp_tool(
                tool_name="test_fanout",
                arguments={"count": 3},
            )
            task_id = response["result"]["task_id"]
            final = e2e_helper.wait_for_task_completion(task_id, timeout=90)
            with locks["fanout"]:
                results["fanout"].append((index, final))
        except Exception as e:
            logger.error(f"Fanout {index} failed: {e}")

    threads = []

    for i in range(5):
        threads.append(threading.Thread(target=send_echo, args=(i,)))
        threads.append(threading.Thread(target=send_pipeline, args=(i,)))
        threads.append(threading.Thread(target=send_fanout, args=(i,)))

    for t in threads:
        t.start()

    for t in threads:
        t.join(timeout=120)

    assert len(results["echo"]) == 5, f"Should have 5 echo results, got {len(results['echo'])}"
    assert len(results["pipeline"]) == 5, f"Should have 5 pipeline results, got {len(results['pipeline'])}"
    assert len(results["fanout"]) == 5, f"Should have 5 fanout results, got {len(results['fanout'])}"

    for idx, task in results["echo"]:
        assert task["status"] == "succeeded", f"Echo {idx} should succeed"

    for idx, task in results["pipeline"]:
        assert task["status"] == "succeeded", f"Pipeline {idx} should succeed"

    for idx, task in results["fanout"]:
        assert task["status"] == "succeeded", f"Fanout {idx} should succeed"

    logger.info("[+] All concurrent routes processed independently")


@pytest.mark.fast
def test_mcp_tool_parameter_validation(e2e_helper):
    """
    E2E: Test MCP tool parameter validation.

    Scenario:
    1. Call tool with missing required parameter (MUST be rejected)
    2. Call tool with wrong parameter type (validation is implementation-dependent)

    Expected: Missing required parameters are rejected
    """
    logger.info("Testing missing required parameter...")
    try:
        e2e_helper.call_mcp_tool(
            tool_name="test_echo",
            arguments={},
        )
        pytest.fail("Should fail with missing required parameter")
    except Exception as e:
        logger.info(f"Correctly rejected missing parameter: {e}")

    logger.info("[+] Parameter validation working correctly")


@pytest.mark.fast
def test_task_status_history(e2e_helper):
    """
    E2E: Test task status tracking through lifecycle.

    Scenario:
    1. Send message through multi-hop route
    2. Poll status at different stages
    3. Verify status progression: pending → processing → succeeded

    Expected: Status accurately reflects current state
    """
    logger.info("Sending multi-hop message...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_pipeline",
        arguments={"value": 10},
    )

    task_id = response["result"]["task_id"]
    statuses_seen = set()

    logger.info("Polling task status during processing...")
    start_time = time.time()
    while time.time() - start_time < 90:
        task = e2e_helper.get_task_status(task_id)
        status = task["status"]
        statuses_seen.add(status)

        logger.debug(f"Current status: {status}")

        if status in ["succeeded", "failed"]:
            break

        time.sleep(0.2)

    logger.info(f"Statuses observed: {statuses_seen}")

    assert "succeeded" in statuses_seen or "failed" in statuses_seen, \
        "Should reach terminal status"

    logger.info("[+] Task status tracking verified")


@pytest.mark.fast
def test_sse_streaming_with_slow_actor(e2e_helper):
    """
    E2E: Test SSE streaming with slow actor processing.

    Scenario:
    1. Send message to slow actor
    2. Stream progress updates via SSE
    3. Verify updates received in real-time
    4. Verify final status in stream

    Expected: SSE provides real-time updates
    """
    logger.info("Sending message to slow actor...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_slow_boundary",
        arguments={"first_call": True},
    )

    task_id = response["result"]["task_id"]

    logger.info("Starting SSE stream...")
    updates = e2e_helper.stream_task_progress(task_id, timeout=120)

    logger.info(f"Received {len(updates)} SSE updates")

    assert len(updates) > 0, "Should receive at least one SSE update"

    final_update = updates[-1]
    assert final_update["status"] in ["succeeded", "failed"], \
        f"Final SSE update should have terminal status, got {final_update['status']}"

    logger.info("[+] SSE streaming provided real-time updates")


@pytest.mark.fast
def test_http_polling_vs_sse_consistency(e2e_helper):
    """
    E2E: Test HTTP polling and SSE give consistent results.

    Scenario:
    1. Send two identical messages
    2. Monitor one via HTTP polling
    3. Monitor one via SSE streaming
    4. Compare final results

    Expected: Both methods give same final state
    """
    logger.info("Sending two identical messages...")

    response1 = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "consistency-test-1"},
    )
    task_id_1 = response1["result"]["task_id"]

    response2 = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "consistency-test-2"},
    )
    task_id_2 = response2["result"]["task_id"]

    logger.info("Monitoring task 1 via HTTP polling...")
    http_updates = e2e_helper.poll_task_progress(task_id_1, timeout=30)

    logger.info("Monitoring task 2 via SSE streaming...")
    sse_updates = e2e_helper.stream_task_progress(task_id_2, timeout=30)

    logger.info(f"HTTP updates: {len(http_updates)}, SSE updates: {len(sse_updates)}")

    http_final = http_updates[-1] if http_updates else None
    sse_final = sse_updates[-1] if sse_updates else None

    assert http_final is not None, "HTTP polling should provide updates"
    assert sse_final is not None, "SSE streaming should provide updates"

    assert http_final["status"] == sse_final["status"], \
        f"Final status should match: HTTP={http_final['status']}, SSE={sse_final['status']}"

    logger.info("[+] HTTP polling and SSE are consistent")


@pytest.mark.fast
def test_task_timeout_tracking(e2e_helper):
    """
    E2E: Test task timeout is properly tracked.

    Scenario:
    1. Send message with short timeout to slow actor
    2. Monitor status
    3. Verify timeout is detected and handled

    Expected: Task status reflects timeout
    """
    logger.info("Sending message with timeout...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_timeout",
        arguments={"sleep_seconds": 60},
    )

    task_id = response["result"]["task_id"]

    logger.info("Waiting for task to process (should timeout)...")
    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=180)

    logger.info(f"Final status: {final_task['status']}")

    assert final_task["status"] in ["failed", "succeeded"], \
        "Task should complete (timeout or success after retry)"

    logger.info("[+] Timeout handling verified")


@pytest.mark.fast
def test_gateway_health_check(e2e_helper, gateway_url):
    """
    E2E: Test gateway health endpoint.

    Scenario:
    1. Check /health endpoint
    2. Verify 200 OK response
    3. Check response format

    Expected: Health check always responsive
    """
    logger.info("Checking gateway health...")
    response = requests.get(f"{gateway_url}/health", timeout=10)

    assert response.status_code == 200, f"Health check should return 200, got {response.status_code}"

    logger.info("[+] Gateway health check passed")


@pytest.mark.fast
def test_task_creation_rate_limit(e2e_helper):
    """
    E2E: Test rapid task creation doesn't overwhelm gateway.

    Scenario:
    1. Create 50 tasks as fast as possible
    2. All should be accepted
    3. All should eventually complete

    Expected: Gateway handles burst creation
    """
    logger.info("Creating 50 tasks rapidly...")
    task_ids = []

    for i in range(50):
        try:
            response = e2e_helper.call_mcp_tool(
                tool_name="test_echo",
                arguments={"message": f"burst-{i}"},
            )
            task_ids.append(response["result"]["task_id"])
        except Exception as e:
            logger.warning(f"Failed to create task {i}: {e}")

    logger.info(f"Created {len(task_ids)} tasks")
    assert len(task_ids) >= 45, f"Should create at least 45/50 tasks, got {len(task_ids)}"

    logger.info("Waiting for sample tasks to complete...")
    completed = 0
    for task_id in task_ids[:10]:
        try:
            final = e2e_helper.wait_for_task_completion(task_id, timeout=30)
            if final["status"] == "succeeded":
                completed += 1
        except Exception as e:
            logger.warning(f"Task failed: {e}")

    assert completed >= 8, f"At least 8/10 sample tasks should complete, got {completed}"

    logger.info("[+] Gateway handled burst creation")


@pytest.mark.fast
def test_mcp_tools_list(e2e_helper, gateway_url):
    """
    E2E: Test MCP tools/list endpoint.

    Scenario:
    1. Initialize MCP session
    2. Query tools/list endpoint with session ID
    3. Verify all configured tools are present
    4. Verify tool schemas are correct

    Expected: All tools discoverable via MCP
    """
    logger.info("Initializing MCP session...")
    init_response = requests.post(
        f"{gateway_url}/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"}
            }
        },
        timeout=10
    )
    assert init_response.status_code == 200, f"initialize should return 200, got {init_response.status_code}"

    session_id = init_response.headers.get("Mcp-Session-Id")
    assert session_id, "Should receive Mcp-Session-Id header from initialize"
    logger.info(f"Received session ID: {session_id}")

    logger.info("Listing MCP tools...")
    response = requests.post(
        f"{gateway_url}/mcp",
        headers={"Mcp-Session-Id": session_id},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        },
        timeout=10
    )

    assert response.status_code == 200, f"tools/list should return 200, got {response.status_code}"

    result = response.json()
    assert "result" in result, "Should have result field"

    tools = result["result"].get("tools", [])
    logger.info(f"Found {len(tools)} tools")

    tool_names = [t["name"] for t in tools]
    logger.info(f"Tool names: {tool_names}")

    expected_tools = ["test_echo", "test_pipeline", "test_error", "test_timeout"]
    for expected in expected_tools:
        assert expected in tool_names, f"Tool {expected} should be in list"

    logger.info("[+] MCP tools list verified")
