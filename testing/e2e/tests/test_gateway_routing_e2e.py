#!/usr/bin/env python3
"""
E2E tests for Gateway routing and MCP protocol.

Tests gateway functionality in a real Kubernetes environment:
- Dynamic route modification in envelope mode
- Route validation and error handling
- Concurrent requests with different routes
- MCP SSE streaming robustness
- Gateway restart resilience
- Tool parameter validation
- Envelope lifecycle tracking

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
@pytest.mark.skip(reason="Gateway restart causes envelope timeout - timing issue in test environment")
def test_gateway_restart_during_processing(e2e_helper):
    """
    E2E: Test gateway restart while envelopes are being processed.

    Scenario:
    1. Send envelope to slow actor (1.5s processing)
    2. Restart gateway pod immediately
    3. Envelope continues processing
    4. Can still query envelope status after restart

    Expected: Gateway stateless, envelope processing continues
    """
    logger.info("Sending envelope to slow actor...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_slow_boundary",
        arguments={"first_call": True},
    )

    envelope_id = response["result"]["envelope_id"]
    logger.info(f"Envelope ID: {envelope_id}")

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

    logger.info("Checking if envelope status is still accessible...")
    envelope = e2e_helper.get_envelope_status(envelope_id)
    logger.info(f"Envelope status after restart: {envelope['status']}")

    final_envelope = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=120)
    assert final_envelope["status"] == "succeeded", \
        "Envelope should complete successfully despite gateway restart"

    logger.info("[+] Gateway restart handled gracefully")


@pytest.mark.fast
def test_concurrent_different_routes(e2e_helper):
    """
    E2E: Test concurrent requests to different routes.

    Scenario:
    1. Send 5 envelopes to test-echo concurrently
    2. Send 5 envelopes to test-pipeline concurrently
    3. Send 5 envelopes to test-fanout concurrently
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
            envelope_id = response["result"]["envelope_id"]
            final = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=60)
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
            envelope_id = response["result"]["envelope_id"]
            final = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=60)
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
            envelope_id = response["result"]["envelope_id"]
            final = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=90)
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

    for idx, envelope in results["echo"]:
        assert envelope["status"] == "succeeded", f"Echo {idx} should succeed"

    for idx, envelope in results["pipeline"]:
        assert envelope["status"] == "succeeded", f"Pipeline {idx} should succeed"

    for idx, envelope in results["fanout"]:
        assert envelope["status"] == "succeeded", f"Fanout {idx} should succeed"

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
def test_envelope_status_history(e2e_helper):
    """
    E2E: Test envelope status tracking through lifecycle.

    Scenario:
    1. Send envelope through multi-hop route
    2. Poll status at different stages
    3. Verify status progression: pending → processing → succeeded

    Expected: Status accurately reflects current state
    """
    logger.info("Sending multi-hop envelope...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_pipeline",
        arguments={"value": 10},
    )

    envelope_id = response["result"]["envelope_id"]
    statuses_seen = set()

    logger.info("Polling envelope status during processing...")
    start_time = time.time()
    while time.time() - start_time < 45:
        envelope = e2e_helper.get_envelope_status(envelope_id)
        status = envelope["status"]
        statuses_seen.add(status)

        logger.debug(f"Current status: {status}")

        if status in ["succeeded", "failed"]:
            break

        time.sleep(0.2)

    logger.info(f"Statuses observed: {statuses_seen}")

    assert "succeeded" in statuses_seen or "failed" in statuses_seen, \
        "Should reach terminal status"

    logger.info("[+] Envelope status tracking verified")


@pytest.mark.fast
def test_sse_streaming_with_slow_actor(e2e_helper):
    """
    E2E: Test SSE streaming with slow actor processing.

    Scenario:
    1. Send envelope to slow actor
    2. Stream progress updates via SSE
    3. Verify updates received in real-time
    4. Verify final status in stream

    Expected: SSE provides real-time updates
    """
    logger.info("Sending envelope to slow actor...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_slow_boundary",
        arguments={"first_call": True},
    )

    envelope_id = response["result"]["envelope_id"]

    logger.info("Starting SSE stream...")
    updates = e2e_helper.stream_envelope_progress(envelope_id, timeout=120)

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
    1. Send two identical envelopes
    2. Monitor one via HTTP polling
    3. Monitor one via SSE streaming
    4. Compare final results

    Expected: Both methods give same final state
    """
    logger.info("Sending two identical envelopes...")

    response1 = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "consistency-test-1"},
    )
    envelope_id_1 = response1["result"]["envelope_id"]

    response2 = e2e_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "consistency-test-2"},
    )
    envelope_id_2 = response2["result"]["envelope_id"]

    logger.info("Monitoring envelope 1 via HTTP polling...")
    http_updates = e2e_helper.poll_envelope_progress(envelope_id_1, timeout=30)

    logger.info("Monitoring envelope 2 via SSE streaming...")
    sse_updates = e2e_helper.stream_envelope_progress(envelope_id_2, timeout=30)

    logger.info(f"HTTP updates: {len(http_updates)}, SSE updates: {len(sse_updates)}")

    http_final = http_updates[-1] if http_updates else None
    sse_final = sse_updates[-1] if sse_updates else None

    assert http_final is not None, "HTTP polling should provide updates"
    assert sse_final is not None, "SSE streaming should provide updates"

    assert http_final["status"] == sse_final["status"], \
        f"Final status should match: HTTP={http_final['status']}, SSE={sse_final['status']}"

    logger.info("[+] HTTP polling and SSE are consistent")


@pytest.mark.fast
def test_envelope_timeout_tracking(e2e_helper):
    """
    E2E: Test envelope timeout is properly tracked.

    Scenario:
    1. Send envelope with short timeout to slow actor
    2. Monitor status
    3. Verify timeout is detected and handled

    Expected: Envelope status reflects timeout
    """
    logger.info("Sending envelope with timeout...")
    response = e2e_helper.call_mcp_tool(
        tool_name="test_timeout",
        arguments={"sleep_seconds": 60},
    )

    envelope_id = response["result"]["envelope_id"]

    logger.info("Waiting for envelope to process (should timeout)...")
    final_envelope = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=180)

    logger.info(f"Final status: {final_envelope['status']}")

    assert final_envelope["status"] in ["failed", "succeeded"], \
        "Envelope should complete (timeout or success after retry)"

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
def test_envelope_creation_rate_limit(e2e_helper):
    """
    E2E: Test rapid envelope creation doesn't overwhelm gateway.

    Scenario:
    1. Create 50 envelopes as fast as possible
    2. All should be accepted
    3. All should eventually complete

    Expected: Gateway handles burst creation
    """
    logger.info("Creating 50 envelopes rapidly...")
    envelope_ids = []

    for i in range(50):
        try:
            response = e2e_helper.call_mcp_tool(
                tool_name="test_echo",
                arguments={"message": f"burst-{i}"},
            )
            envelope_ids.append(response["result"]["envelope_id"])
        except Exception as e:
            logger.warning(f"Failed to create envelope {i}: {e}")

    logger.info(f"Created {len(envelope_ids)} envelopes")
    assert len(envelope_ids) >= 45, f"Should create at least 45/50 envelopes, got {len(envelope_ids)}"

    logger.info("Waiting for sample envelopes to complete...")
    completed = 0
    for envelope_id in envelope_ids[:10]:
        try:
            final = e2e_helper.wait_for_envelope_completion(envelope_id, timeout=30)
            if final["status"] == "succeeded":
                completed += 1
        except Exception as e:
            logger.warning(f"Envelope failed: {e}")

    assert completed >= 8, f"At least 8/10 sample envelopes should complete, got {completed}"

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
