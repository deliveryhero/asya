#!/usr/bin/env python3
"""
Progress Tracking Integration Test.

Tests the SSE-based progress tracking functionality where actors report
progress at three checkpoints (received, processing, completed) for each step.

Test flow:
1. Send MCP request to gateway with a multi-step route
2. Gateway creates job and sends to first actor queue
3. Each actor reports progress: received → processing → completed
4. Gateway calculates progress percentage and streams via SSE
5. Verify progress increases monotonically from 0% to 100%
6. Verify all progress updates are received and accurate

Run tests with:
    pytest -v tests/integration/test_progress_tracking.py
"""

import json
import logging
import os
import time
from typing import  List, Optional
from dataclasses import dataclass

import pytest
import requests
from sseclient import SSEClient  # pip install sseclient-py

# Configure logging from environment variable (default: INFO)
log_level = os.getenv('ASYA_LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class ProgressUpdate:
    """Represents a progress update from SSE stream."""
    timestamp: float
    status: str
    progress_percent: Optional[float]
    step: Optional[str]
    step_status: Optional[str]
    message: Optional[str]

    @classmethod
    def from_sse_data(cls, data: dict, timestamp: float):
        """Create from SSE event data."""
        return cls(
            timestamp=timestamp,
            status=data.get("status"),
            progress_percent=data.get("progress_percent"),
            step=data.get("step"),
            step_status=data.get("step_status"),
            message=data.get("message"),
        )


class ProgressTrackingTestHelper:
    """Helper class for progress tracking E2E testing."""

    def __init__(self, gateway_url: str = "http://gateway:8080"):
        self.gateway_url = gateway_url
        self.tools_url = f"{gateway_url}/tools/call"
        self.jobs_url = f"{gateway_url}/jobs"

    def call_mcp_tool(
        self,
        tool_name: str,
        arguments: dict,
        timeout: int = 60,
    ) -> dict:
        """Call an MCP tool via REST API."""
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
            import re
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

    def stream_progress_updates(
        self,
        job_id: str,
        timeout: int = 60,
    ) -> List[ProgressUpdate]:
        """
        Stream job progress via SSE and return all progress updates.

        Returns list of ProgressUpdate objects with progress_percent field.
        """
        logger.info(f" Starting SSE stream for job: {job_id}")
        updates = []
        start_time = time.time()

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
                elapsed = time.time() - start_time

                # Parse event data
                if event.event == "update" and event.data:
                    data = json.loads(event.data)
                    logger.info(f" SSE event received: {event.event} data={event.data[:100]}")

                    # Only track updates with progress information
                    if data.get("progress_percent") is not None:
                        update = ProgressUpdate.from_sse_data(data, elapsed)
                        updates.append(update)

                        logger.info(f"[{elapsed:.2f}s] Progress: {update.progress_percent:.2f}% "
                              f"- {update.step}:{update.step_status}")

                    # Stop if terminal state
                    if data.get("status") in ["Succeeded", "Failed"]:
                        logger.info(f" Terminal status reached: {data.get('status')}")
                        break

        except Exception as e:
            logger.info(f" SSE stream ended with exception: {e}")

        logger.info(f" SSE stream complete. Received {len(updates)} progress updates")
        return updates


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
def progress_helper():
    """Create a progress tracking helper for each test."""
    gateway_url = os.getenv("ASYA_GATEWAY_URL", "http://localhost:8080")
    rabbitmq_url = os.getenv("RABBITMQ_MGMT_URL", "http://rabbitmq:15672")

    helper = ProgressTrackingTestHelper(gateway_url)

    # Wait for gateway to be ready
    max_retries = 30
    for i in range(max_retries):
        try:
            requests.get(f"{gateway_url}/health", timeout=2)
            break
        except Exception:
            if i == max_retries - 1:
                raise RuntimeError("Gateway not available")
            time.sleep(1)

    # Wait for actor sidecars to initialize RabbitMQ consumers
    wait_for_rabbitmq_consumers(rabbitmq_url, timeout=30)

    yield helper


# ============================================================================
# Test Cases
# ============================================================================


def test_progress_tracking_single_step(progress_helper):
    """Test progress tracking with a single-step pipeline."""
    # Call a tool with single-step route
    response = progress_helper.call_mcp_tool(
        tool_name="test_echo",
        arguments={"message": "progress test"},
    )

    assert "result" in response, "Should have result field"
    job_id = response["result"]["job_id"]
    logger.info(f" Job ID: {job_id}")

    # Stream progress updates
    updates = progress_helper.stream_progress_updates(job_id, timeout=30)

    # Should have at least 3 updates: received, processing, completed
    logger.info(f" Total updates: {len(updates)}")
    assert len(updates) >= 3, f"Expected at least 3 updates, got {len(updates)}"

    # Verify we have all three status checkpoints
    statuses = [u.step_status for u in updates]
    logger.info(f" Statuses seen: {statuses}")
    assert "received" in statuses, "Should have 'received' checkpoint"
    assert "processing" in statuses, "Should have 'processing' checkpoint"
    assert "completed" in statuses, "Should have 'completed' checkpoint"

    # Verify progress percentages
    progress_values = [u.progress_percent for u in updates]
    logger.info(f" Progress values: {progress_values}")

    # First update should be low (received = 10%)
    assert progress_values[0] <= 15, f"First progress should be ~10%, got {progress_values[0]}"

    # Last update should be 100% (completed)
    assert progress_values[-1] >= 99, f"Final progress should be ~100%, got {progress_values[-1]}"

    # Verify progress increases monotonically
    for i in range(1, len(progress_values)):
        assert progress_values[i] >= progress_values[i-1], \
            f"Progress decreased: {progress_values[i-1]:.2f}% → {progress_values[i]:.2f}%"

    # Verify final job status
    final_job = progress_helper.get_job_status(job_id)
    logger.info(f" Final job: {final_job}")
    assert final_job["progress_percent"] >= 99, "Final job progress should be ~100%"
    logger.info(" test_progress_tracking_single_step: PASSED")


def test_progress_tracking_multi_step(progress_helper):
    """Test progress tracking with a 2-step pipeline."""
    # Call a tool with multi-step route
    response = progress_helper.call_mcp_tool(
        tool_name="test_pipeline",  # 2-step pipeline: doubler → incrementer
        arguments={"value": 42},
    )

    job_id = response["result"]["job_id"]
    logger.info(f" Job ID: {job_id}")

    # Stream progress updates
    updates = progress_helper.stream_progress_updates(job_id, timeout=60)

    # 2 steps × 3 statuses = 6 expected updates
    logger.info(f" Total updates: {len(updates)}")
    assert len(updates) >= 6, f"Expected at least 6 updates for 2-step pipeline, got {len(updates)}"

    # Extract progress values
    progress_values = [u.progress_percent for u in updates]
    logger.info(f" Progress values: {progress_values}")

    # Verify progress starts near 0 and ends at 100
    assert progress_values[0] <= 5, f"Initial progress should be ~3%, got {progress_values[0]}"
    assert progress_values[-1] >= 99, f"Final progress should be ~100%, got {progress_values[-1]}"

    # Verify monotonic increase
    for i in range(1, len(progress_values)):
        assert progress_values[i] >= progress_values[i-1], \
            f"Progress decreased: {progress_values[i-1]:.2f}% → {progress_values[i]:.2f}%"

    # Verify we saw updates from all 2 steps
    steps_seen = set(u.step for u in updates if u.step)
    logger.info(f" Steps seen: {steps_seen}")
    assert len(steps_seen) >= 2, f"Should see updates from 2 steps, saw: {steps_seen}"

    # Verify all checkpoints for each step
    for step_name in steps_seen:
        step_updates = [u for u in updates if u.step == step_name]
        step_statuses = [u.step_status for u in step_updates]
        logger.info(f" Step {step_name} statuses: {step_statuses}")

        assert "received" in step_statuses, f"Step {step_name} missing 'received'"
        assert "processing" in step_statuses, f"Step {step_name} missing 'processing'"
        assert "completed" in step_statuses, f"Step {step_name} missing 'completed'"

    logger.info(" test_progress_tracking_multi_step: PASSED")


def test_progress_calculation_accuracy(progress_helper):
    """Test that progress calculation matches expected formula."""
    # 2-step pipeline: doubler → incrementer
    response = progress_helper.call_mcp_tool(
        tool_name="test_pipeline",
        arguments={"value": 100},
    )

    job_id = response["result"]["job_id"]
    updates = progress_helper.stream_progress_updates(job_id, timeout=60)

    # Define expected progress values (±1% tolerance)
    # Formula: (stepIndex * 100 + statusWeight) / totalSteps
    # statusWeight: received=10, processing=50, completed=100
    # totalSteps: 2
    expected_checkpoints = [
        # Step 0 (doubler)
        {"step_index": 0, "status": "received", "expected": 5.0},
        {"step_index": 0, "status": "processing", "expected": 25.0},
        {"step_index": 0, "status": "completed", "expected": 50.0},
        # Step 1 (incrementer)
        {"step_index": 1, "status": "received", "expected": 55.0},
        {"step_index": 1, "status": "processing", "expected": 75.0},
        {"step_index": 1, "status": "completed", "expected": 100.0},
    ]

    # Match updates to expected checkpoints
    tolerance = 1.0  # ±1%

    matched_checkpoints = 0
    for checkpoint in expected_checkpoints:
        # Find update matching this checkpoint
        matching_updates = [
            u for u in updates
            if u.step_status == checkpoint["status"]
        ]

        if matching_updates:
            # Check if any match the expected progress
            for update in matching_updates:
                if abs(update.progress_percent - checkpoint["expected"]) <= tolerance:
                    matched_checkpoints += 1
                    logger.info(f"✓ Matched {checkpoint['status']} at step {checkpoint['step_index']}: "
                          f"{update.progress_percent:.2f}% ≈ {checkpoint['expected']:.2f}%")
                    break

    # Should match most checkpoints (allow some variance due to timing)
    assert matched_checkpoints >= 5, \
        f"Expected to match at least 5/6 checkpoints, matched {matched_checkpoints}"


def test_progress_in_job_status_endpoint(progress_helper):
    """Test that GET /jobs/{id} returns updated progress information."""
    response = progress_helper.call_mcp_tool(
        tool_name="test_pipeline",
        arguments={"value": 50},
    )

    job_id = response["result"]["job_id"]

    # Poll job status several times while job is running
    seen_progress_values = []

    for _ in range(10):
        job = progress_helper.get_job_status(job_id)

        if "progress_percent" in job:
            seen_progress_values.append(job["progress_percent"])

        if "current_step" in job and job["current_step"]:
            logger.info(f"Current step: {job['current_step']} @ {job['progress_percent']:.2f}%")

        # Stop if job completed
        if job["status"] in ["Succeeded", "Failed"]:
            break

        time.sleep(0.5)

    # Should have seen multiple progress values
    assert len(seen_progress_values) > 0, "Should see progress in job status"

    # Final check
    final_job = progress_helper.get_job_status(job_id)
    assert final_job["progress_percent"] >= 99, "Final progress should be ~100%"
    assert final_job["total_steps"] == 2, "Should track total steps"


def test_concurrent_jobs_independent_progress(progress_helper):
    """Test that concurrent jobs track progress independently."""
    # Start 3 concurrent jobs
    job_ids = []

    for i in range(3):
        response = progress_helper.call_mcp_tool(
            tool_name="test_echo",
            arguments={"message": f"concurrent-progress-{i}"},
        )
        job_ids.append(response["result"]["job_id"])

    # Poll all jobs and verify each has independent progress
    job_progress = {job_id: [] for job_id in job_ids}

    for _ in range(20):
        for job_id in job_ids:
            try:
                job = progress_helper.get_job_status(job_id)
                if "progress_percent" in job:
                    job_progress[job_id].append(job["progress_percent"])
            except:
                pass

        time.sleep(0.2)

    # Each job should have tracked its own progress
    for job_id, progress_values in job_progress.items():
        assert len(progress_values) > 0, f"Job {job_id} should have progress updates"

        # Progress should reach 100% eventually
        final_job = progress_helper.get_job_status(job_id)
        assert final_job["status"] == "Succeeded", f"Job {job_id} should succeed"
        assert final_job["progress_percent"] >= 99, \
            f"Job {job_id} should reach ~100% progress"


def test_progress_with_error(progress_helper):
    """Test progress tracking when a job fails mid-pipeline."""
    # Call a tool that will fail
    response = progress_helper.call_mcp_tool(
        tool_name="test_error",
        arguments={"should_fail": True},
    )

    job_id = response["result"]["job_id"]

    # Stream progress until failure
    updates = progress_helper.stream_progress_updates(job_id, timeout=30)

    # Should have some progress updates before failure
    assert len(updates) > 0, "Should have progress updates before failure"

    # Progress should not reach 100% (job failed)
    progress_values = [u.progress_percent for u in updates]
    max_progress = max(progress_values) if progress_values else 0

    assert max_progress < 100, \
        f"Failed job should not reach 100% progress, got {max_progress}%"

    # Verify job status shows failure
    final_job = progress_helper.get_job_status(job_id)
    assert final_job["status"] == "Failed", "Job should be marked as Failed"
    assert final_job["progress_percent"] < 100, "Failed job progress should be < 100%"
