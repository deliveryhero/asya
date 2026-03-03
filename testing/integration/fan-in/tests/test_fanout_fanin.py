"""Integration tests: fan-out/fan-in pipeline.

Pipeline under test:
  fan-out-router -> [sub-agent x N] -> aggregator -> x-sink

The fan-out router receives a message with a 'topics' list, generates N+1 slices:
  - Slice 0 (parent payload): routed directly to aggregator
  - Slices 1..N (topic payloads): routed through sub-agent -> aggregator

The aggregator collects all slices using S3-backed split-key state and emits
the merged payload (parent payload with 'results' field added) to x-sink.

NOTE: Intermediate aggregator invocations (still accumulating, returns None)
cause the sidecar to route the original slice message to x-sink automatically.
The wait_for_merged_result helper skips those intermediate messages and waits
for the final merged payload (identified by the presence of 'results' key).
"""

import logging
import uuid


logger = logging.getLogger(__name__)

SINK_QUEUE = "asya-default-x-sink"
FANOUT_ROUTER_QUEUE = "asya-default-test-fanout-router"


def _msg_id() -> str:
    return f"test-{uuid.uuid4().hex[:8]}"


class TestFanOutFanIn:
    """End-to-end fan-out/fan-in pipeline tests."""

    def test_two_topics_produces_merged_result(self, transport):
        """Fan-out with 2 topics: parent + 2 slices merge into one message at x-sink."""
        msg_id = _msg_id()
        payload = {
            "query": "test query",
            "topics": ["topic-alpha", "topic-beta"],
        }

        envelope = {
            "id": msg_id,
            "route": {"prev": [], "curr": "test-fanout-router", "next": []},
            "payload": payload,
        }

        logger.info(f"[.] Publishing fan-out message id={msg_id} with 2 topics")
        transport.publish_envelope(FANOUT_ROUTER_QUEUE, envelope)

        # Intermediate slices also appear at x-sink (when aggregator returns None),
        # so use wait_for_merged_result to skip them and find the final merged payload.
        result = transport.wait_for_merged_result(SINK_QUEUE, aggregation_key="results", timeout=60)
        assert result is not None, f"No merged result at '{SINK_QUEUE}' within 60s"
        logger.info(f"[+] Received merged result at x-sink")

        merged_payload = result["payload"]
        assert "results" in merged_payload, f"Expected 'results' in payload: {merged_payload}"
        results = merged_payload["results"]

        # 2 sub-agent results (echo_handler returns payload as-is when no "message" key)
        assert len(results) == 2, f"Expected 2 sub-agent results, got {len(results)}: {results}"

        # Verify original parent fields are preserved
        assert merged_payload["query"] == "test query"
        assert merged_payload["topics"] == ["topic-alpha", "topic-beta"]

        # Verify sub-agent processed each topic slice payload
        topics_in_results = {r.get("topic") for r in results}
        assert "topic-alpha" in topics_in_results, f"topic-alpha not in results: {results}"
        assert "topic-beta" in topics_in_results, f"topic-beta not in results: {results}"

        logger.info("[+] test_two_topics_produces_merged_result passed")

    def test_three_topics_produces_merged_result(self, transport):
        """Fan-out with 3 topics: 4 slices (parent + 3) merge correctly."""
        msg_id = _msg_id()
        payload = {
            "request": "multi-topic",
            "topics": ["alpha", "beta", "gamma"],
        }

        envelope = {
            "id": msg_id,
            "route": {"prev": [], "curr": "test-fanout-router", "next": []},
            "payload": payload,
        }

        logger.info(f"[.] Publishing fan-out message id={msg_id} with 3 topics")
        transport.publish_envelope(FANOUT_ROUTER_QUEUE, envelope)

        result = transport.wait_for_merged_result(SINK_QUEUE, aggregation_key="results", timeout=60)
        assert result is not None, f"No merged result at '{SINK_QUEUE}' within 60s"
        logger.info(f"[+] Received merged result at x-sink")

        merged_payload = result["payload"]
        assert "results" in merged_payload, f"Expected 'results' in payload: {merged_payload}"
        results = merged_payload["results"]

        assert len(results) == 3, f"Expected 3 sub-agent results, got {len(results)}: {results}"
        assert merged_payload["request"] == "multi-topic"

        topics_in_results = {r.get("topic") for r in results}
        assert "alpha" in topics_in_results
        assert "beta" in topics_in_results
        assert "gamma" in topics_in_results

        logger.info("[+] test_three_topics_produces_merged_result passed")

    def test_single_topic_produces_merged_result(self, transport):
        """Fan-out with 1 topic: 2 slices (parent + 1) merge correctly."""
        msg_id = _msg_id()
        payload = {
            "data": "single",
            "topics": ["only-topic"],
        }

        envelope = {
            "id": msg_id,
            "route": {"prev": [], "curr": "test-fanout-router", "next": []},
            "payload": payload,
        }

        logger.info(f"[.] Publishing fan-out message id={msg_id} with 1 topic")
        transport.publish_envelope(FANOUT_ROUTER_QUEUE, envelope)

        result = transport.wait_for_merged_result(SINK_QUEUE, aggregation_key="results", timeout=60)
        assert result is not None, f"No merged result at '{SINK_QUEUE}' within 60s"
        merged_payload = result["payload"]

        assert "results" in merged_payload
        results = merged_payload["results"]
        assert len(results) == 1, f"Expected 1 sub-agent result, got: {results}"
        assert results[0].get("topic") == "only-topic"

        logger.info("[+] test_single_topic_produces_merged_result passed")

    def test_two_independent_fanout_messages(self, transport):
        """Two independent fan-out messages do not interfere with each other."""
        msg_id_1 = _msg_id()
        msg_id_2 = _msg_id()

        message_1 = {
            "id": msg_id_1,
            "route": {"prev": [], "curr": "test-fanout-router", "next": []},
            "payload": {"label": "first", "topics": ["t1a", "t1b"]},
        }
        message_2 = {
            "id": msg_id_2,
            "route": {"prev": [], "curr": "test-fanout-router", "next": []},
            "payload": {"label": "second", "topics": ["t2a", "t2b"]},
        }

        logger.info(f"[.] Publishing two independent fan-out messages")
        transport.publish_envelope(FANOUT_ROUTER_QUEUE, message_1)
        transport.publish_envelope(FANOUT_ROUTER_QUEUE, message_2)

        # Both must produce merged results at x-sink; order is not guaranteed
        result_a = transport.wait_for_merged_result(SINK_QUEUE, aggregation_key="results", timeout=60)
        assert result_a is not None, f"No first merged result at '{SINK_QUEUE}' within 60s"
        result_b = transport.wait_for_merged_result(SINK_QUEUE, aggregation_key="results", timeout=60)
        assert result_b is not None, f"No second merged result at '{SINK_QUEUE}' within 60s"

        labels = {result_a["payload"].get("label"), result_b["payload"].get("label")}
        assert "first" in labels, f"'first' missing from results: {labels}"
        assert "second" in labels, f"'second' missing from results: {labels}"

        for result in [result_a, result_b]:
            payload = result["payload"]
            assert "results" in payload
            assert len(payload["results"]) == 2

        logger.info("[+] test_two_independent_fanout_messages passed")


class TestFanOutFanInEdgeCases:
    """Edge case and error handling tests for the fan-out/fan-in pipeline."""

    def test_empty_topics_list_produces_merged_result(self, transport):
        """Fan-out with empty topics: slice_count=1, aggregator emits immediately.

        The fan-out router sends only slice 0 (parent payload) when topics is empty.
        slice_count=1 means only the parent slice is needed. The aggregator receives
        it, finds all 1 slices present, emits the merged payload with results=[].
        """
        msg_id = _msg_id()
        payload = {"query": "empty topics test", "topics": []}

        envelope = {
            "id": msg_id,
            "route": {"prev": [], "curr": "test-fanout-router", "next": []},
            "payload": payload,
        }

        logger.info(f"[.] Publishing fan-out message with empty topics list")
        transport.publish_envelope(FANOUT_ROUTER_QUEUE, envelope)

        # With 0 topics, slice_count=1 so only the parent slice is needed.
        # Aggregator receives the parent, sets results=[], emits to x-sink.
        result = transport.wait_for_merged_result(SINK_QUEUE, aggregation_key="results", timeout=30)
        assert result is not None, f"No merged result at '{SINK_QUEUE}' within 30s"
        merged_payload = result["payload"]

        assert "results" in merged_payload, f"Expected 'results' key: {merged_payload}"
        assert merged_payload["results"] == [], f"Expected empty results: {merged_payload}"
        assert merged_payload["query"] == "empty topics test"

        logger.info("[+] test_empty_topics_list_produces_merged_result passed")
