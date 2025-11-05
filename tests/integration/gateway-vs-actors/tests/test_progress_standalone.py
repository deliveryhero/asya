#!/usr/bin/env python3
"""
Standalone Progress Tracking Test

A simplified version of the progress tracking test with basic smoke tests
for MCP tool calls, job status API, and SSE streaming.

Run with pytest:
    pytest -v tests/integration/test_progress_standalone.py
"""

import json
import logging
import os
import re
import time
import pytest
import requests
from sseclient import SSEClient
from typing import List

# Configure logging from environment variable (default: INFO)
log_level = os.getenv('ASYA_LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def wait_for_rabbitmq_consumers(
    rabbitmq_url: str = "http://rabbitmq:15672",
    required_queues: List[str] = None,
    timeout: int = 30,
) -> None:
    """
    Wait for RabbitMQ queues to have active consumers.

    Polls RabbitMQ Management API until all required queues have at least one consumer.
    This ensures actor sidecars have initialized before tests start.
    """
    if required_queues is None:
        required_queues = [
            "test-echo-queue",
            "test-progress-queue",
            "test-doubler-queue",
            "test-incrementer-queue",
            "test-error-queue",
            "test-timeout-queue",
        ]

    start_time = time.time()
    poll_interval = 0.5

    while time.time() - start_time < timeout:
        try:
            # Query all queues via RabbitMQ Management API
            response = requests.get(
                f"{rabbitmq_url}/api/queues",
                auth=("guest", "guest"),
                timeout=2,
            )

            if response.status_code == 200:
                queues = response.json()
                queue_status = {q["name"]: q.get("consumers", 0) for q in queues}

                # Check if all required queues have consumers
                all_ready = all(
                    queue_status.get(queue_name, 0) > 0
                    for queue_name in required_queues
                )

                if all_ready:
                    logger.info(f"All RabbitMQ consumers ready after {time.time() - start_time:.2f}s")
                    return
                else:
                    missing = [q for q in required_queues if queue_status.get(q, 0) == 0]
                    logger.info(f"Waiting for consumers on: {missing}")

        except Exception as e:
            logger.info(f"RabbitMQ API not ready: {e}")

        time.sleep(poll_interval)  # Poll RabbitMQ API for consumer readiness

    raise RuntimeError(f"RabbitMQ consumers not ready after {timeout}s")


@pytest.fixture(scope="function")
def gateway_url():
    """Get gateway URL from environment."""
    url = os.getenv("ASYA_GATEWAY_URL", "http://localhost:8080")
    rabbitmq_url = os.getenv("RABBITMQ_MGMT_URL", "http://rabbitmq:15672")

    # Wait for gateway to be ready
    max_retries = 30
    for i in range(max_retries):
        try:
            response = requests.get(f"{url}/health", timeout=2)
            if response.status_code == 200:
                break
        except Exception:
            if i == max_retries - 1:
                raise RuntimeError("Gateway not available")
            time.sleep(1)

    # Wait for actor sidecars to initialize RabbitMQ consumers
    wait_for_rabbitmq_consumers(rabbitmq_url, timeout=30)

    return url


def test_mcp_tool_call(gateway_url: str):
    """Test basic MCP tool invocation."""
    tools_url = f"{gateway_url}/tools/call"
    logger.info(f" Tools URL: {tools_url}")

    payload = {
        "name": "test_echo",
        "arguments": {"message": "Hello from standalone test!"},
    }
    logger.info(f" Payload: {payload}")

    response = requests.post(tools_url, json=payload, timeout=10)
    logger.info(f" Response status: {response.status_code}")
    response.raise_for_status()
    result = response.json()
    logger.info(f" Result: {result}")

    # Extract job_id from response
    assert "content" in result, f"Response should have content field. Got: {result.keys()}"
    assert len(result["content"]) > 0, f"Content should not be empty. Got: {result['content']}"

    text_content = result["content"][0].get("text", "")
    logger.info(f" Text content: {text_content}")
    assert text_content, f"Text content should not be empty. Got: {result['content'][0]}"

    match = re.search(r"ID: ([a-f0-9-]+)", text_content)
    assert match, f"Could not extract job ID from: {text_content}"
    job_id = match.group(1)
    logger.info(f" Extracted job_id: {job_id}")

    assert job_id, "Should extract job_id from response"
    logger.info(" test_mcp_tool_call: PASSED")


def test_job_status(gateway_url: str):
    """Test GET /jobs/{id} endpoint."""
    tools_url = f"{gateway_url}/tools/call"

    # Create a job first
    payload = {
        "name": "test_echo",
        "arguments": {"message": "status test"},
    }
    logger.info(f" Creating job with payload: {payload}")

    response = requests.post(tools_url, json=payload, timeout=10)
    response.raise_for_status()
    result = response.json()
    logger.info(f" Tool call result: {result}")

    # Extract job_id from response
    text_content = result["content"][0].get("text", "")
    match = re.search(r"ID: ([a-f0-9-]+)", text_content)
    assert match, f"Could not extract job ID from: {text_content}"
    job_id = match.group(1)
    logger.info(f" Job ID: {job_id}")

    time.sleep(0.5)

    # Get job status
    logger.info(f" Getting job status for: {job_id}")
    response = requests.get(f"{gateway_url}/jobs/{job_id}", timeout=10)
    response.raise_for_status()
    job = response.json()
    logger.info(f" Job status: {job}")

    assert "status" in job, "Job should have status field"
    assert "progress_percent" in job, "Job should have progress_percent field"
    assert "total_steps" in job, "Job should have total_steps field"
    logger.info(" test_job_status: PASSED")


def test_sse_streaming(gateway_url: str):
    """Test SSE progress streaming."""
    tools_url = f"{gateway_url}/tools/call"

    # Create a job for SSE test
    payload = {
        "name": "test_echo",
        "arguments": {"message": "SSE test"},
    }
    logger.info(f" Creating job with payload: {payload}")

    response = requests.post(tools_url, json=payload, timeout=10)
    response.raise_for_status()
    result = response.json()
    logger.info(f" Tool call result: {result}")

    # Extract job_id from response
    text_content = result["content"][0].get("text", "")
    match = re.search(r"ID: ([a-f0-9-]+)", text_content)
    assert match, f"Could not extract job ID from: {text_content}"
    job_id = match.group(1)
    logger.info(f" Job ID: {job_id}")

    # Stream progress via SSE
    progress_updates = []

    try:
        logger.info(f" Starting SSE stream for job: {job_id}")
        response = requests.get(
            f"{gateway_url}/jobs/{job_id}/stream",
            stream=True,
            timeout=30,
            headers={"Accept": "text/event-stream"},
        )
        response.raise_for_status()
        logger.info(f" SSE stream connected, status: {response.status_code}")

        client = SSEClient(response)

        for event in client.events():
            if event.event == "update" and event.data:
                data = json.loads(event.data)
                logger.info(f" SSE event: {event.event} data={event.data[:100]}")

                if data.get("progress_percent") is not None:
                    progress_updates.append(data["progress_percent"])
                    logger.info(f" Progress: {data['progress_percent']:.2f}%")

                # Stop on terminal state
                if data.get("status") in ["Succeeded", "Failed"]:
                    logger.info(f" Terminal status reached: {data.get('status')}")
                    break

    except Exception as e:
        logger.info(f" SSE stream ended with exception: {e}")

    # Validate progress updates
    logger.info(f" Total progress updates: {len(progress_updates)}")
    logger.info(f" Progress values: {progress_updates}")
    assert len(progress_updates) > 0, "Should receive at least one progress update"

    # Check monotonic increase
    for i in range(1, len(progress_updates)):
        assert progress_updates[i] >= progress_updates[i-1], \
            f"Progress should increase monotonically: {progress_updates[i-1]:.2f}% -> {progress_updates[i]:.2f}%"

    # Check that progress reaches completion
    max_progress = max(progress_updates)
    logger.info(f" Max progress: {max_progress:.2f}%")
    assert max_progress >= 99, f"Progress should reach ~100%, got {max_progress:.2f}%"
    logger.info(" test_sse_streaming: PASSED")
