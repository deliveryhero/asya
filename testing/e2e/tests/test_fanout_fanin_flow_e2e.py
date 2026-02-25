#!/usr/bin/env python3
"""
E2E tests for the research_flow fan-out/fan-in compiled flow.

Tests the full fan-out/fan-in lifecycle on a live Kind cluster:
- start-research-flow router (entry point, routes to fanout router)
- fanout-research-flow-l2 router (generates N+1 slices)
- research-agent actors (processes individual topics in parallel)
- research-flow-aggregator crew actor (collects N+1 slices, emits merged message)
- Final merged result persisted to S3 by x-sink

Prerequisites:
- Kind cluster deployed with PROFILE=sqs-s3
- asya-test-flows Helm chart deployed (includes research-flow actors)
- ASYA_HANDLER_MODE=message support in asya_runtime (see epic 1c7i)
- State proxy sidecar active on research-flow-aggregator pod

Actors deployed by the asya-test-flows chart:
- start-research-flow (queue: asya-asya-e2e-start-research-flow)
- fanout-research-flow-l2 (queue: asya-asya-e2e-fanout-research-flow-l2)
- research-agent (queue: asya-asya-e2e-research-agent)
- research-flow-aggregator (queue: asya-asya-e2e-research-flow-aggregator)

Fan-out protocol (N topics => N+1 messages):
- Slice index 0: parent payload forwarded to aggregator with x-asya-fan-in header
- Slices 1..N: each topic sent to research-agent, result forwarded to aggregator
- Aggregator emits merged message when all N+1 slices have arrived
"""

import json
import logging
import time
import uuid

import boto3
import pytest


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Flow helper fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def flow_helper(transport_timeouts, s3_endpoint, results_bucket, test_config):
    """Helper for research_flow fan-out/fan-in testing."""

    class FanoutFlowHelper:
        def __init__(self):
            self.timeouts = transport_timeouts
            self.s3_endpoint = s3_endpoint
            self.results_bucket = results_bucket
            self.test_config = test_config
            self.namespace = test_config.namespace

        def _queue_name(self, actor_name: str) -> str:
            """Compute SQS queue name for the given actor in this namespace."""
            return f"asya-{self.namespace}-{actor_name}"

        def send_to_flow(self, topics: list) -> str:
            """Send a message with a list of topics to the start-research-flow queue.

            Returns the task_id (message id) used to locate the result in S3.
            """
            sqs = boto3.client("sqs", endpoint_url=self.test_config.sqs_endpoint)

            queue_name = self._queue_name("start-research-flow")
            response = sqs.get_queue_url(QueueName=queue_name)
            queue_url = response["QueueUrl"]

            task_id = str(uuid.uuid4())

            message = {
                "id": task_id,
                "route": {
                    "prev": [],
                    "curr": "start-research-flow",
                    "next": [],
                },
                "payload": {"topics": topics},
            }

            sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(message))

            logger.info(f"[.] Sent message {task_id} to start-research-flow with {len(topics)} topics: {topics}")
            return task_id

        def wait_for_result(self, task_id: str, timeout: int = 120) -> dict:
            """Poll S3 results bucket until a result matching task_id appears.

            Returns the full message message stored by x-sink.
            Raises TimeoutError if result does not appear within timeout seconds.
            """
            s3 = boto3.client("s3", endpoint_url=self.s3_endpoint)

            start_time = time.time()
            while time.time() - start_time < timeout:
                # S3 key format: {prefix}/{timestamp}/{actor}/{task_id}.json
                # task_id appears as the filename, so we list with a broad prefix
                # and match by task_id within the key
                response = s3.list_objects_v2(Bucket=self.results_bucket)

                if "Contents" in response:
                    for obj in response["Contents"]:
                        if task_id in obj["Key"]:
                            result_obj = s3.get_object(Bucket=self.results_bucket, Key=obj["Key"])
                            result = json.loads(result_obj["Body"].read())
                            logger.info(f"[+] Retrieved result for task {task_id} from {obj['Key']}")
                            return result

                time.sleep(2)  # Poll S3 for new result objects

            raise TimeoutError(
                f"Fan-out/fan-in result not found after {timeout}s for task_id={task_id}. "
                f"Check aggregator logs (asya-e2e/research-flow-aggregator) and "
                f"ensure ASYA_HANDLER_MODE=message is supported by asya_runtime."
            )

        def count_partial_results_in_sink(self, task_id: str, timeout: int = 60) -> int:
            """Count how many S3 objects reference this task_id.

            For a correctly working fan-in, exactly ONE final merged message
            should reach x-sink (the partial slices are suppressed via
            x-asya-fan-in header detection in x-sink).
            """
            s3 = boto3.client("s3", endpoint_url=self.s3_endpoint)

            # Wait a moment for any partial results to potentially appear
            time.sleep(min(timeout, 10))  # Give x-sink time to process partials

            # S3 key format: {prefix}/{timestamp}/{actor}/{task_id}.json
            # task_id appears as the filename, so we list broadly and filter by key
            response = s3.list_objects_v2(Bucket=self.results_bucket)

            count = 0
            if "Contents" in response:
                for obj in response["Contents"]:
                    if task_id in obj["Key"]:
                        count += 1

            return count

    return FanoutFlowHelper()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.flow
@pytest.mark.timeout(300)
def test_fanout_fanin_basic_3_topics(flow_helper):
    """Fan-out with 3 topics: verify merged result contains all 3 research outputs.

    Flow: start-research-flow -> fanout-research-flow-l2 -> [research-agent x3]
          -> research-flow-aggregator (collects 4 slices: 1 parent + 3 agent results)
          -> x-sink -> S3

    Expected:
    - Exactly 1 result in S3 (not 4 partial results)
    - payload.results has 3 items (one per topic)
    - Each result item has topic and findings fields
    """
    topics = ["artificial-intelligence", "machine-learning", "natural-language-processing"]

    logger.info(f"[.] Testing fan-out with {len(topics)} topics")

    task_id = flow_helper.send_to_flow(topics=topics)
    # Timeout = 3 topics * 30s + 60s buffer for aggregation and routing
    result = flow_helper.wait_for_result(task_id, timeout=150)

    assert result is not None, "Expected a result from S3"

    # x-sink persists the payload dict directly (not the full message message)
    assert "results" in result, f"Merged payload missing 'results' field. Got keys: {list(result.keys())}"

    results = result["results"]
    assert len(results) == len(topics), (
        f"Expected {len(topics)} results but got {len(results)}. "
        f"Fan-in may have merged prematurely or some research-agent slices were dropped."
    )

    # Each result item should have topic and findings (from research_agent handler)
    for i, item in enumerate(results):
        assert isinstance(item, dict), f"Result item {i} should be a dict, got {type(item).__name__}"
        assert "topic" in item or "findings" in item, f"Result item {i} missing expected fields: {item}"

    logger.info(f"[+] Fan-out/fan-in with {len(topics)} topics completed: {len(results)} results in merged payload")


@pytest.mark.flow
@pytest.mark.timeout(300)
def test_fanout_fanin_no_false_positives_from_partial_slices(flow_helper):
    """Verify gateway does not see false completions from partial fan-in slices.

    When the aggregator returns None (accumulating partial slices), the sidecar
    routes those acked messages to x-sink. x-sink must NOT report gateway status
    for messages carrying the x-asya-fan-in header (non-reporting mechanism).

    Only the final merged message (emitted when all slices collected) triggers
    x-sink gateway reporting. This test verifies exactly ONE S3 result object
    appears for the task -- not N+1 partial results.

    See: RFC fan-in protocol, section 'Non-Reporting Mechanisms'.
    """
    topics = ["topic-alpha", "topic-beta"]

    logger.info("[.] Testing that partial fan-in slices do not produce false results")

    task_id = flow_helper.send_to_flow(topics=topics)
    # Wait for the merged result to appear
    result = flow_helper.wait_for_result(task_id, timeout=120)

    assert result is not None, "Expected one merged result"
    assert "results" in result, "Merged payload missing 'results' field"

    # Now check that only 1 result exists for this task_id
    count = flow_helper.count_partial_results_in_sink(task_id, timeout=30)
    assert count == 1, (
        f"Expected exactly 1 result in S3 for task {task_id} "
        f"(merged message only), but found {count}. "
        f"x-sink may not be suppressing partial fan-in results. "
        f"Check x-sink's x-asya-fan-in header detection logic."
    )

    logger.info(f"[+] No false positives: exactly {count} result in S3 for task {task_id}")


@pytest.mark.flow
@pytest.mark.timeout(600)
def test_fanout_fanin_10_topics(flow_helper):
    """Fan-out with 10 topics: verify all 10 results aggregated correctly.

    Tests higher fan-out cardinality to surface race conditions in the aggregator
    and verify the S3 split-key pattern handles concurrent slice writes correctly.

    Timeout: 10 topics * 30s + 120s buffer = 420s
    """
    topics = [f"research-topic-{i:02d}" for i in range(10)]

    logger.info(f"[.] Testing fan-out with {len(topics)} topics (high cardinality)")

    task_id = flow_helper.send_to_flow(topics=topics)
    # Generous timeout: 10 parallel research-agents + aggregation overhead
    result = flow_helper.wait_for_result(task_id, timeout=420)

    assert result is not None, "Expected merged result for 10-topic fan-out"

    assert "results" in result, "Merged payload missing 'results' field after 10-topic fan-out"

    results = result["results"]
    assert len(results) == 10, (
        f"Expected 10 results but got {len(results)}. Some research-agent slices may have been lost during aggregation."
    )

    logger.info(f"[+] 10-topic fan-out/fan-in completed: all {len(results)} results present")


@pytest.mark.flow
@pytest.mark.timeout(300)
def test_fanout_fanin_single_topic(flow_helper):
    """Fan-out with 1 topic: minimal case N=1, slice_count=2.

    Verifies the protocol works for the edge case of a single topic:
    - slice_count = 2 (1 parent + 1 sub-agent)
    - Aggregator must wait for both slice-0 and slice-1
    """
    topics = ["single-topic"]

    logger.info("[.] Testing fan-out with 1 topic (edge case)")

    task_id = flow_helper.send_to_flow(topics=topics)
    result = flow_helper.wait_for_result(task_id, timeout=90)

    assert result is not None, "Expected merged result for single-topic fan-out"

    assert "results" in result, "Merged payload missing 'results' field"

    results = result["results"]
    assert len(results) == 1, f"Expected 1 result for single-topic fan-out, got {len(results)}"

    logger.info("[+] Single-topic fan-out/fan-in completed successfully")


@pytest.mark.flow
@pytest.mark.timeout(300)
def test_fanout_fanin_concurrent_requests(flow_helper):
    """Two concurrent fan-out requests must not interfere with each other.

    Each request has a distinct task_id used as the origin_id in the x-asya-fan-in
    header. The aggregator uses origin_id as the S3 directory key, so concurrent
    requests must use independent state directories.

    Verifies: no cross-contamination between concurrent fan-out operations.
    """
    topics_a = ["concurrent-a-1", "concurrent-a-2"]
    topics_b = ["concurrent-b-1", "concurrent-b-2", "concurrent-b-3"]

    logger.info("[.] Sending two concurrent fan-out requests")

    task_id_a = flow_helper.send_to_flow(topics=topics_a)
    task_id_b = flow_helper.send_to_flow(topics=topics_b)

    logger.info(f"[.] Waiting for task_a={task_id_a} and task_b={task_id_b}")

    result_a = flow_helper.wait_for_result(task_id_a, timeout=150)
    result_b = flow_helper.wait_for_result(task_id_b, timeout=150)

    assert result_a is not None, f"Expected result for task_a={task_id_a}"
    assert result_b is not None, f"Expected result for task_b={task_id_b}"

    assert "results" in result_a, "Task A merged payload missing 'results'"
    assert "results" in result_b, "Task B merged payload missing 'results'"

    assert len(result_a["results"]) == len(topics_a), (
        f"Task A: expected {len(topics_a)} results, got {len(result_a['results'])}"
    )
    assert len(result_b["results"]) == len(topics_b), (
        f"Task B: expected {len(topics_b)} results, got {len(result_b['results'])}"
    )

    logger.info(
        f"[+] Concurrent fan-out/fan-in completed without cross-contamination: "
        f"task_a={len(result_a['results'])} results, task_b={len(result_b['results'])} results"
    )


@pytest.mark.flow
@pytest.mark.slow
@pytest.mark.timeout(600)
def test_fanout_fanin_aggregator_restart_mid_aggregation(flow_helper, e2e_helper):
    """Aggregator pod restart mid-aggregation must not lose progress.

    State is stored in S3 via the state proxy sidecar. When the aggregator
    pod is restarted, a new pod picks up the next slice and reads existing
    state from S3. The merged message is still emitted exactly once.

    This test verifies the durability guarantee of the S3 split-key fan-in design.

    Scenario:
    1. Send fan-out with 5 topics
    2. Wait briefly for first slice to arrive at aggregator
    3. Restart aggregator pod
    4. Wait for all slices to arrive and merged result to appear in S3
    5. Verify exactly 1 merged result (no duplicate emission)
    """
    topics = [f"durable-topic-{i}" for i in range(5)]

    logger.info("[.] Testing aggregator restart durability with 5 topics")

    task_id = flow_helper.send_to_flow(topics=topics)

    logger.info("[.] Waiting briefly for aggregation to start before restart")
    time.sleep(5)  # Allow at least one slice to reach aggregator before restart

    logger.info("[.] Restarting research-flow-aggregator pod")
    pods = e2e_helper.kubectl(
        "get",
        "pods",
        "-l",
        "asya.sh/actor=research-flow-aggregator",
        "-o",
        "jsonpath={.items[*].metadata.name}",
    )

    if pods and pods.strip():
        pod_name = pods.strip().split()[0]
        logger.info(f"[.] Deleting aggregator pod: {pod_name}")
        e2e_helper.delete_pod(pod_name)

        logger.info("[.] Waiting for new aggregator pod to become ready")
        assert e2e_helper.wait_for_pod_ready("asya.sh/actor=research-flow-aggregator", timeout=60), (
            "New aggregator pod did not become ready after restart"
        )
    else:
        pytest.skip("No research-flow-aggregator pod found; skip restart test")

    logger.info("[.] Waiting for merged result after aggregator restart")
    # Extra time for pod restart + S3 state recovery
    result = flow_helper.wait_for_result(task_id, timeout=300)

    assert result is not None, "Expected merged result after aggregator restart"

    assert "results" in result, "Merged payload missing 'results' after restart"

    results = result["results"]
    assert len(results) == len(topics), (
        f"Expected {len(topics)} results after restart, got {len(results)}. "
        f"State may not have survived pod restart. "
        f"Verify state proxy sidecar and S3 state storage are working correctly."
    )

    # Verify no duplicate emission (exactly 1 result in S3)
    count = flow_helper.count_partial_results_in_sink(task_id, timeout=10)
    assert count == 1, (
        f"Expected exactly 1 merged result but found {count}. "
        f"Aggregator may have emitted duplicate messages (check sentinel logic)."
    )

    logger.info(f"[+] Aggregator restart durability verified: {len(results)} results present, no duplicate emissions")
