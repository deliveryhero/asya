#!/usr/bin/env python3
"""
E2E tests for nested_if flow.

Tests all 4 possible routes through the nested if-else decision tree:
- Route A-X: level1=A, level2=X
- Route A-Y: level1=A, level2=Y
- Route B-X: level1=B, level2=X
- Route B-Y: level1=B, level2=Y
"""

import logging
import time
import json
import uuid
import boto3
import pytest
import requests

logger = logging.getLogger(__name__)


@pytest.fixture(scope="function")
def flow_helper(gateway_helper, transport_timeouts, s3_endpoint, results_bucket, test_config):
    """Helper for flow testing with result retrieval."""

    class FlowHelper:
        def __init__(self):
            self.gateway = gateway_helper
            self.timeouts = transport_timeouts
            self.s3_endpoint = s3_endpoint
            self.results_bucket = results_bucket
            self.test_config = test_config

        def send_to_flow(self, level1: str, level2: str) -> str:
            """Send test payload to flow start queue and return task_id."""

            sqs = boto3.client("sqs", endpoint_url=self.test_config.sqs_endpoint)

            response = sqs.get_queue_url(QueueName="asya-asya-e2e-start-test-nested-flow")
            queue_url = response["QueueUrl"]

            payload = {"level1": level1, "level2": level2}

            message = {
                "route": {"prev": [], "curr": "start-test-nested-flow", "next": []},
                "payload": payload,
            }


            task_id = str(uuid.uuid4())
            message["id"] = task_id

            sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(message))

            logger.info(f"Sent message {task_id} to flow with level1={level1}, level2={level2}")
            return task_id

        def wait_for_result(self, task_id: str, timeout: int = 120) -> dict:
            """Wait for flow completion and retrieve result from S3."""

            s3 = boto3.client("s3", endpoint_url=self.s3_endpoint)

            start_time = time.time()
            while time.time() - start_time < timeout:
                response = s3.list_objects_v2(Bucket=self.results_bucket, Prefix="")

                if "Contents" in response:
                    for obj in response["Contents"]:
                        if task_id in obj["Key"]:
                            result_obj = s3.get_object(Bucket=self.results_bucket, Key=obj["Key"])
                            result = json.loads(result_obj["Body"].read())
                            logger.info(f"Retrieved result for task {task_id} from {obj['Key']}")
                            return result

                time.sleep(2)

            raise TimeoutError(f"Flow result not found after {timeout}s for task {task_id}")

    return FlowHelper()


@pytest.mark.flow
@pytest.mark.timeout(300)
def test_route_a_x(flow_helper):
    """Test route A-X: level1=A, level2=X."""
    logger.info("Testing route A-X")

    task_id = flow_helper.send_to_flow(level1="A", level2="X")
    result = flow_helper.wait_for_result(task_id)

    assert result["validated"] is True
    assert result["path"] == "A"
    assert result["route"] == "A-X"
    assert result["processed_by"] == "route_a_x"
    assert result["result"] == "A-X complete"
    assert result["status"] == "completed"
    assert result["final"] is True

    logger.info("[+] Route A-X completed successfully")


@pytest.mark.flow
@pytest.mark.timeout(300)
def test_route_a_y(flow_helper):
    """Test route A-Y: level1=A, level2=Y."""
    logger.info("Testing route A-Y")

    task_id = flow_helper.send_to_flow(level1="A", level2="Y")
    result = flow_helper.wait_for_result(task_id)

    assert result["validated"] is True
    assert result["path"] == "A"
    assert result["route"] == "A-Y"
    assert result["processed_by"] == "route_a_y"
    assert result["result"] == "A-Y complete"
    assert result["status"] == "completed"
    assert result["final"] is True

    logger.info("[+] Route A-Y completed successfully")


@pytest.mark.flow
@pytest.mark.timeout(300)
def test_route_b_x(flow_helper):
    """Test route B-X: level1=B, level2=X."""
    logger.info("Testing route B-X")

    task_id = flow_helper.send_to_flow(level1="B", level2="X")
    result = flow_helper.wait_for_result(task_id)

    assert result["validated"] is True
    assert result["path"] == "B"
    assert result["route"] == "B-X"
    assert result["processed_by"] == "route_b_x"
    assert result["result"] == "B-X complete"
    assert result["status"] == "completed"
    assert result["final"] is True

    logger.info("[+] Route B-X completed successfully")


@pytest.mark.flow
@pytest.mark.timeout(300)
def test_route_b_y(flow_helper):
    """Test route B-Y: level1=B, level2=Y."""
    logger.info("Testing route B-Y")

    task_id = flow_helper.send_to_flow(level1="B", level2="Y")
    result = flow_helper.wait_for_result(task_id)

    assert result["validated"] is True
    assert result["path"] == "B"
    assert result["route"] == "B-Y"
    assert result["processed_by"] == "route_b_y"
    assert result["result"] == "B-Y complete"
    assert result["status"] == "completed"
    assert result["final"] is True

    logger.info("[+] Route B-Y completed successfully")


@pytest.mark.flow
@pytest.mark.timeout(300)
def test_all_routes_parallel(flow_helper):
    """Test all 4 routes in parallel to verify no crosstalk."""
    logger.info("Testing all routes in parallel")

    test_cases = [
        ("A", "X", "route_a_x", "A-X complete"),
        ("A", "Y", "route_a_y", "A-Y complete"),
        ("B", "X", "route_b_x", "B-X complete"),
        ("B", "Y", "route_b_y", "B-Y complete"),
    ]

    task_ids = []
    for level1, level2, _, _ in test_cases:
        task_id = flow_helper.send_to_flow(level1=level1, level2=level2)
        task_ids.append((task_id, level1, level2))

    logger.info(f"Sent {len(task_ids)} messages in parallel")

    for task_id, level1, level2 in task_ids:
        result = flow_helper.wait_for_result(task_id)

        expected_route = f"{level1}-{level2}"
        expected_handler = next(h for l1, l2, h, _ in test_cases if l1 == level1 and l2 == level2)
        expected_result = next(r for l1, l2, _, r in test_cases if l1 == level1 and l2 == level2)

        assert result["route"] == expected_route, f"Wrong route for {task_id}"
        assert result["processed_by"] == expected_handler, f"Wrong handler for {task_id}"
        assert result["result"] == expected_result, f"Wrong result for {task_id}"
        assert result["status"] == "completed", f"Not completed for {task_id}"

        logger.info(f"[+] Task {task_id} ({level1}-{level2}): verified")

    logger.info("[+] All routes completed successfully in parallel without crosstalk")


@pytest.mark.flow
@pytest.mark.timeout(300)
def test_route_a_x_via_mcp_tool(e2e_helper):
    """Test route A-X via MCP tool on gateway."""
    logger.info("Testing route A-X via MCP tool")

    response = e2e_helper.call_mcp_tool(
        tool_name="test_nested_flow",
        arguments={"level1": "A", "level2": "X"},
    )

    task_id = response["result"]["task_id"]
    logger.info(f"Task ID: {task_id}")

    final_task = e2e_helper.wait_for_task_completion(task_id, timeout=60)

    assert final_task["status"] == "succeeded", \
        f"Task should succeed, got {final_task['status']}"

    result_payload = final_task.get("result", {})
    assert result_payload.get("validated") is True
    assert result_payload.get("path") == "A"
    assert result_payload.get("route") == "A-X"
    assert result_payload.get("processed_by") == "route_a_x"
    assert result_payload.get("result") == "A-X complete"
    assert result_payload.get("status") == "completed"
    assert result_payload.get("final") is True

    logger.info("[+] Route A-X via MCP tool completed successfully")
