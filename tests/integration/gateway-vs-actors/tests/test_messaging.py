#!/usr/bin/env python3
"""
Gateway E2E integration test suite.

Tests the complete flow from Gateway → Actors → Results with SSE progress updates.

Test flow:
1. Send MCP request to gateway
2. Gateway creates job and sends to first actor queue
3. Actors send heartbeats (picked_up, processing, completed)
4. Gateway streams progress via SSE
5. Verify final result in job status

Run tests with:
    pytest -v tests/integration/test_messaging.py
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import List

import pytest
import requests
from sseclient import SSEClient

# Configure logging from environment variable (default: INFO)
log_level = os.getenv('ASYA_LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class SSEEvent:
    """Represents a Server-Sent Event."""
    event: str
    data: str

    def json(self) -> dict:
        """Parse data as JSON."""
        return json.loads(self.data)


class GatewayTestHelper:
    """Helper class for Gateway E2E testing."""

    def __init__(
        self,
        gateway_url: str = "http://gateway:8080",
    ):
        self.gateway_url = gateway_url
        self.tools_url = f"{gateway_url}/tools/call"
        self.jobs_url = f"{gateway_url}/jobs"

    def call_mcp_tool(
        self,
        tool_name: str,
        arguments: dict,
        timeout: int = 60,
    ) -> dict:
        """
        Call a tool via REST API.

        Returns a response with result containing job_id.
        """
        logger.info(f" Calling tool: {tool_name} with arguments: {arguments}")

        payload = {
            "name": tool_name,
            "arguments": arguments,
        }

        response = requests.post(
            self.tools_url,
            json=payload,
            timeout=timeout,
        )
        logger.info(f" Tool call response status: {response.status_code}")
        response.raise_for_status()

        # Parse MCP CallToolResult
        mcp_result = response.json()
        logger.info(f" MCP result: {mcp_result}")

        # Extract job ID from text content
        # Format: "Job created successfully with ID: {job_id}\n..."
        text_content = ""
        if "content" in mcp_result and len(mcp_result["content"]) > 0:
            text_content = mcp_result["content"][0].get("text", "")

        job_id = None
        if "Job created successfully with ID:" in text_content:
            # Extract job ID from the message

            match = re.search(r"ID: ([a-f0-9-]+)", text_content)
            if match:
                job_id = match.group(1)
                logger.info(f" Extracted job_id: {job_id}")

        # Return in expected format
        result = {
            "result": {
                "job_id": job_id,
                "message": text_content,
            }
        }
        logger.info(f" Returning result: {result}")
        return result

    def get_job_status(self, job_id: str) -> dict:
        """Get job status via REST API."""
        logger.info(f" Getting job status for: {job_id}")
        response = requests.get(f"{self.jobs_url}/{job_id}")
        response.raise_for_status()
        job_status = response.json()
        logger.info(f" Job status: {job_status}")
        return job_status

    def stream_job_progress(
        self,
        job_id: str,
        timeout: int = 60,
    ) -> List[SSEEvent]:
        """
        Stream job progress via SSE.

        Returns list of all SSE events received before completion.
        """
        logger.info(f" Starting SSE stream for job: {job_id}")
        events = []

        response = requests.get(
            f"{self.jobs_url}/{job_id}/stream",
            stream=True,
            timeout=timeout,
            headers={"Accept": "text/event-stream"},
        )
        response.raise_for_status()
        logger.info(f" SSE stream connected, status: {response.status_code}")

        client = SSEClient(response)

        try:
            for event in client.events():
                sse_event = SSEEvent(event=event.event or "message", data=event.data)
                events.append(sse_event)
                logger.info(f" SSE event received: type={sse_event.event} data={sse_event.data[:100]}")

                # Stop if we got a terminal status
                if sse_event.event == "update":
                    update = sse_event.json()
                    status = update.get("status")
                    logger.info(f" SSE update event: status={status} progress={update.get('progress_percent')}")
                    if status in ["Succeeded", "Failed"]:
                        logger.info(f" Terminal status reached: {status}")
                        break

        except Exception as e:
            logger.info(f" SSE stream ended with exception: {e}")

        logger.info(f" SSE stream complete. Received {len(events)} events")
        return events

    def wait_for_job_completion(
        self,
        job_id: str,
        timeout: int = 60,
        interval: float = 0.1,
    ) -> dict:
        """
        Poll job status until it reaches a terminal state.

        Returns the final job object.
        """
        logger.info(f" Waiting for job completion: {job_id} (timeout={timeout}s)")
        start_time = time.time()

        while time.time() - start_time < timeout:
            job = self.get_job_status(job_id)
            elapsed = time.time() - start_time

            if job["status"] in ["Succeeded", "Failed", "Unknown"]:
                logger.info(f" Job completed after {elapsed:.2f}s with status: {job['status']}")
                return job

            logger.info(f" Job still {job['status']} after {elapsed:.2f}s, waiting...")
            time.sleep(interval)  # Poll gateway API for job completion

        logger.info(f" Job {job_id} timed out after {timeout}s")
        raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")


# ============================================================================
# Helper Functions
# ============================================================================


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


# ============================================================================
# Pytest Fixtures
# ============================================================================


@pytest.fixture(scope="function")
def gateway_helper():
    """Create a gateway helper for each test."""
    gateway_url = os.getenv("ASYA_GATEWAY_URL", "http://gateway:8080")
    rabbitmq_url = os.getenv("RABBITMQ_MGMT_URL", "http://rabbitmq:15672")

    helper = GatewayTestHelper(gateway_url)

    # Wait for gateway to be ready
    max_retries = 30
    for i in range(max_retries):
        try:
            requests.get(f"{gateway_url}/health", timeout=2)
            break
        except Exception:
            if i == max_retries - 1:
                raise RuntimeError("Gateway not available")
            time.sleep(0.2)  # Poll gateway health endpoint until ready

    # Wait for actor sidecars to initialize RabbitMQ consumers
    wait_for_rabbitmq_consumers(rabbitmq_url, timeout=30)

    yield helper


# ============================================================================
# Test Cases
# ============================================================================


def test_simple_tool_execution(gateway_helper):
    """Test simple tool execution with single actor."""
    # Call the echo tool
    response = gateway_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "Hello, World!"},
    )

    # Verify JSON-RPC response
    assert "result" in response, "Should have result field"
    result = response["result"]
    assert "job_id" in result, "Should return job_id"

    job_id = result["job_id"]
    logger.info(f" Job ID: {job_id}")

    # Wait for job completion
    final_job = gateway_helper.wait_for_job_completion(job_id, timeout=30)

    # Verify job completed successfully
    logger.info(f" Final job: {final_job}")
    assert final_job["status"] == "Succeeded", f"Job should succeed, got {final_job}"
    assert final_job["result"] is not None, "Job should have result"

    # Verify the echo result
    job_result = final_job["result"]
    assert job_result.get("echoed") == "Hello, World!", "Should echo the message"


def test_sse_progress_streaming(gateway_helper):
    """Test SSE progress streaming with heartbeat updates."""
    # Call a tool that sends heartbeat updates
    response = gateway_helper.call_mcp_tool(
        tool_name="test_progress",
        arguments={"steps": 3},
    )

    job_id = response["result"]["job_id"]
    logger.info(f" Job ID: {job_id}")

    # Stream progress via SSE
    events = gateway_helper.stream_job_progress(job_id, timeout=30)

    # Verify we received events
    logger.info(f" Total events received: {len(events)}")
    assert len(events) > 0, "Should receive SSE events"

    # Check for initial status event
    status_events = [e for e in events if e.event == "status"]
    logger.info(f" Status events: {len(status_events)}")
    assert len(status_events) > 0, "Should have status event"

    # Check for update events
    update_events = [e for e in events if e.event == "update"]
    logger.info(f" Update events: {len(update_events)}")
    assert len(update_events) > 0, "Should have update events"

    # Verify updates show progress
    updates = [e.json() for e in update_events]

    # Should have updates for: received, processing, completed
    messages = [u.get("message", "") for u in updates]
    logger.info(f" Progress messages: {messages}")
    assert any("received" in msg.lower() for msg in messages), \
        "Should have 'received' update"
    assert any("completed" in msg.lower() for msg in messages), \
        "Should have 'completed' update"

    # Verify final status is Succeeded
    final_status = updates[-1].get("status")
    logger.info(f" Final status: {final_status}")
    assert final_status == "Succeeded", f"Final status should be Succeeded, got {final_status}"


def test_multi_step_pipeline(gateway_helper):
    """Test multi-step pipeline with multiple actors."""
    # Call a tool with multi-step route
    response = gateway_helper.call_mcp_tool(
        tool_name="test_pipeline",
        arguments={"value": 10},
    )

    job_id = response["result"]["job_id"]
    logger.info(f" Job ID: {job_id}")

    # Stream progress to see all steps
    events = gateway_helper.stream_job_progress(job_id, timeout=60)

    update_events = [e for e in events if e.event == "update"]
    updates = [e.json() for e in update_events]
    logger.info(f" Total update events: {len(update_events)}")

    # Should see updates from multiple actors in the pipeline
    messages = [u.get("message", "") for u in updates]
    logger.info(f" All messages: {messages}")

    # Verify we saw updates from different steps
    # Each step sends received, processing, and completed status
    steps_seen = set()
    for update in updates:
        step = update.get("step")
        if step:
            steps_seen.add(step)

    logger.info(f" Steps seen: {steps_seen}")
    assert len(steps_seen) >= 2, \
        f"Should see updates from multiple steps, saw: {steps_seen}"

    # Wait for completion
    final_job = gateway_helper.wait_for_job_completion(job_id, timeout=60)
    logger.info(f" Final job status: {final_job['status']}")
    assert final_job["status"] == "Succeeded", "Pipeline should complete successfully"

    # Verify the pipeline processed the value through all steps
    result = final_job["result"]
    logger.info(f" Result: {result}")
    assert result is not None, "Should have a result"
    # Value should be: 10 * 2 + 5 = 25 (doubled + incremented)
    assert result.get("value") == 25, f"Expected 25, got {result.get('value')}"


def test_error_handling_with_sse(gateway_helper):
    """Test error handling and SSE updates for failed jobs."""
    # Call a tool that will fail
    response = gateway_helper.call_mcp_tool(
        tool_name="test_error",
        arguments={"should_fail": True},
    )

    job_id = response["result"]["job_id"]
    logger.info(f" Job ID: {job_id}")

    # Stream progress
    events = gateway_helper.stream_job_progress(job_id, timeout=30)

    update_events = [e for e in events if e.event == "update"]
    updates = [e.json() for e in update_events]
    logger.info(f" Total update events: {len(update_events)}")

    # Final update should indicate failure
    final_update = updates[-1]
    logger.info(f" Final update: {final_update}")
    assert final_update["status"] == "Failed", "Job should fail"
    assert final_update.get("error"), "Should have error message"

    # Verify job status reflects the error
    final_job = gateway_helper.get_job_status(job_id)
    logger.info(f" Final job: {final_job}")
    assert final_job["status"] == "Failed", "Job status should be Failed"
    assert final_job["error"], "Job should have error message"


def test_job_status_endpoint(gateway_helper):
    """Test job status REST endpoint."""
    # Create a job
    response = gateway_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "status test"},
    )

    job_id = response["result"]["job_id"]
    logger.info(f" Job ID: {job_id}")

    # Immediately check status (should be Pending or Running)
    job = gateway_helper.get_job_status(job_id)
    logger.info(f" Initial job status: {job['status']}")
    assert job["id"] == job_id, "Job ID should match"
    assert job["status"] in ["Pending", "Running"], \
        f"Initial status should be Pending or Running, got {job['status']}"
    assert "route" in job, "Should have route information"
    assert "created_at" in job, "Should have created_at timestamp"

    # Wait for completion
    final_job = gateway_helper.wait_for_job_completion(job_id, timeout=30)

    # Check final status
    logger.info(f" Final job: {final_job}")
    assert final_job["status"] == "Succeeded", "Should complete successfully"
    assert final_job["result"] is not None, "Should have result"
    assert "updated_at" in final_job, "Should have updated_at timestamp"


def test_concurrent_jobs(gateway_helper):
    """Test multiple concurrent jobs."""
    # Start multiple jobs concurrently
    job_ids = []

    for i in range(3):
        response = gateway_helper.call_mcp_tool(
            tool_name="test_echo",
            arguments={"message": f"concurrent-{i}"},
        )
        job_id = response["result"]["job_id"]
        job_ids.append(job_id)
        logger.info(f" Created job {i}: {job_id}")

    logger.info(f" Total concurrent jobs: {len(job_ids)}")

    # Wait for all jobs to complete
    completed_jobs = []
    for i, job_id in enumerate(job_ids):
        logger.info(f" Waiting for job {i}: {job_id}")
        job = gateway_helper.wait_for_job_completion(job_id, timeout=30)
        completed_jobs.append(job)
        logger.info(f" Job {i} completed with status: {job['status']}")

    # Verify all jobs succeeded
    for job in completed_jobs:
        logger.info(f" Verifying job {job['id']}: status={job['status']}")
        assert job["status"] == "Succeeded", f"Job {job['id']} should succeed"
        assert job["result"] is not None, f"Job {job['id']} should have result"

    # Verify each job has its own result
    results = [job["result"]["echoed"] for job in completed_jobs]
    logger.info(f" All results: {results}")
    assert "concurrent-0" in results, "Should have result from job 0"
    assert "concurrent-1" in results, "Should have result from job 1"
    assert "concurrent-2" in results, "Should have result from job 2"


def test_timeout_handling(gateway_helper):
    """Test job timeout handling."""
    # Call a tool that sleeps longer than timeout
    response = gateway_helper.call_mcp_tool(
        tool_name="test_timeout",
        arguments={"sleep_seconds": 60},  # Will timeout before completing
    )

    job_id = response["result"]["job_id"]
    logger.info(f" Job ID: {job_id}")

    # Wait for job to timeout (timeout is set to 10s in config)
    # Use wait_for_job_completion which polls until terminal state
    try:
        job = gateway_helper.wait_for_job_completion(job_id, timeout=15)
        logger.info(f" Job completed with status: {job['status']}")
    except TimeoutError:
        # If still not complete after 15s, get current status
        job = gateway_helper.get_job_status(job_id)
        logger.info(f" Current job status: {job['status']}")

    # Should be marked as Failed due to timeout
    logger.info(f" Final job: {job}")
    assert job["status"] in ["Failed", "Unknown"], \
        f"Job should timeout, got status: {job['status']}"
