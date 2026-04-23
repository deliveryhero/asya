"""
Observability E2E tests for distributed tracing, metrics, and logs.

Verifies the full observability stack:
- Tempo: traces appear with correct span structure
- Prometheus: sidecar metrics are scraped
- Loki: sidecar logs are collected

These tests require the observability stack (tracing + prometheus + loki + promtail)
to be deployed. They are skipped if the backends are not available.
"""

import json
import logging
import os
import subprocess
import time

import pytest


logger = logging.getLogger(__name__)

NAMESPACE = os.environ.get("ASYA_NAMESPACE", "asya-e2e")
TEMPO_URL = os.environ.get("ASYA_TEMPO_URL", f"http://tempo.{NAMESPACE}.svc.cluster.local:3200")
PROMETHEUS_URL = os.environ.get("ASYA_PROMETHEUS_URL", f"http://prometheus-server.{NAMESPACE}.svc.cluster.local:80")
LOKI_URL = os.environ.get("ASYA_LOKI_URL", f"http://loki.{NAMESPACE}.svc.cluster.local:3100")


def _kubectl_exec_wget(pod_selector: str, url: str, namespace: str = NAMESPACE) -> dict:
    """Query an in-cluster HTTP endpoint via kubectl exec + wget on a sidecar pod."""
    result = subprocess.run(
        [
            "kubectl", "-n", namespace,
            "get", "pod", "-l", pod_selector,
            "-o", "jsonpath={.items[0].metadata.name}",
        ],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0 or not result.stdout.strip():
        pytest.skip(f"No pod found for selector {pod_selector}")
    pod_name = result.stdout.strip()

    result = subprocess.run(
        [
            "kubectl", "-n", namespace,
            "exec", pod_name, "-c", "asya-sidecar", "--",
            "wget", "-qO-", url,
        ],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        pytest.skip(f"wget failed in {pod_name}: {result.stderr}")
    return json.loads(result.stdout)


def _query_tempo(query: str, limit: int = 10) -> dict:
    """Query Tempo search API from inside the cluster via a sidecar pod."""
    url = f"{TEMPO_URL}/api/search?q={query}&limit={limit}"
    return _kubectl_exec_wget("asya.sh/actor=x-sink", url)


def _query_prometheus(query: str) -> dict:
    """Query Prometheus from inside the cluster via a sidecar pod."""
    url = f"{PROMETHEUS_URL}/api/v1/query?query={query}"
    return _kubectl_exec_wget("asya.sh/actor=x-sink", url)


def _query_loki(query: str, limit: int = 5) -> dict:
    """Query Loki from inside the cluster via a sidecar pod."""
    start = int((time.time() - 600) * 1e9)  # 10 minutes ago
    end = int(time.time() * 1e9)
    url = f"{LOKI_URL}/loki/api/v1/query_range?query={query}&start={start}&end={end}&limit={limit}"
    return _kubectl_exec_wget("asya.sh/actor=x-sink", url)


# ---------------------------------------------------------------------------
# Tracing tests (Tempo)
# ---------------------------------------------------------------------------


class TestTracing:
    """Verify distributed traces flow through the actor mesh."""

    def test_tempo_is_healthy(self):
        """Tempo is deployed and accepting queries."""
        data = _query_tempo("{}")
        assert "traces" in data or "metrics" in data, "Tempo did not return a valid response"
        logger.info("[+] Tempo is healthy")

    def test_gateway_traces_exist(self, gateway_helper):
        """Gateway produces traces with gateway.task.execute spans."""
        # Send a message to generate a trace
        gateway_helper.call_mcp_tool(
            tool_name="test_echo",
            arguments={"message": "observability-trace-test"},
        )

        # Poll Tempo for the trace (spans are batched, may take a few seconds)
        deadline = time.time() + 30
        traces = []
        while time.time() < deadline:
            data = _query_tempo('{name="gateway.task.execute"}', limit=5)
            traces = data.get("traces", [])
            if traces:
                break
            time.sleep(2)  # polling for Tempo indexing

        assert len(traces) > 0, "No gateway.task.execute traces found in Tempo"
        logger.info("[+] Found %d gateway traces in Tempo", len(traces))

    def test_sidecar_traces_exist(self):
        """Sidecar produces actor.process spans."""
        data = _query_tempo('{name="actor.process"}', limit=5)
        traces = data.get("traces", [])
        assert len(traces) > 0, "No actor.process traces found in Tempo"
        logger.info("[+] Found %d actor traces in Tempo", len(traces))

    def test_trace_spans_have_attributes(self):
        """Trace spans include asya-specific attributes."""
        data = _query_tempo('{name="actor.process"}', limit=1)
        traces = data.get("traces", [])
        if not traces:
            pytest.skip("No actor traces available yet")

        trace_id = traces[0]["traceID"]

        # Fetch full trace
        url = f"{TEMPO_URL}/api/traces/{trace_id}"
        trace_data = _kubectl_exec_wget("asya.sh/actor=x-sink", url)

        # Find actor.process span and check attributes
        found_attrs = set()
        for batch in trace_data.get("batches", []):
            for scope in batch.get("scopeSpans", []):
                for span in scope.get("spans", []):
                    if span.get("name") == "actor.process":
                        for attr in span.get("attributes", []):
                            found_attrs.add(attr["key"])

        expected_attrs = {"asya.actor", "asya.envelope_id", "asya.queue"}
        missing = expected_attrs - found_attrs
        assert not missing, f"actor.process span missing attributes: {missing}"
        logger.info("[+] actor.process spans have correct attributes: %s", found_attrs)

    def test_multi_service_trace(self):
        """A single trace spans multiple actor services (end-to-end propagation)."""
        deadline = time.time() + 60
        multi_service = []
        total_traces = 0
        while time.time() < deadline:
            data = _query_tempo('{name="actor.process"}', limit=20)
            traces = data.get("traces", [])
            total_traces = len(traces)
            multi_service = [
                t for t in traces
                if len(t.get("serviceStats", {})) > 1
            ]
            if multi_service:
                break
            time.sleep(5)

        assert len(multi_service) > 0, (
            "No multi-service traces found. Trace context may not be propagating across actors. "
            f"Found {total_traces} single-service traces."
        )

        best = max(multi_service, key=lambda t: len(t.get("serviceStats", {})))
        services = list(best["serviceStats"].keys())
        logger.info(
            "[+] Found multi-service trace spanning %d services: %s",
            len(services), services,
        )


# ---------------------------------------------------------------------------
# Metrics tests (Prometheus)
# ---------------------------------------------------------------------------


class TestMetrics:
    """Verify Prometheus scrapes sidecar metrics."""

    def test_prometheus_is_healthy(self):
        """Prometheus is deployed and scraping targets."""
        data = _query_prometheus("up")
        results = data.get("data", {}).get("result", [])
        assert len(results) > 0, "Prometheus has no targets"
        logger.info("[+] Prometheus is healthy with %d targets", len(results))

    def test_sidecar_metrics_scraped(self):
        """Sidecar metrics (asya_actor_messages_received_total) are in Prometheus."""
        data = _query_prometheus("asya_actor_messages_received_total")
        results = data.get("data", {}).get("result", [])
        assert len(results) > 0, "No asya_actor_messages_received_total metrics found"
        logger.info("[+] Found sidecar metrics for %d actors", len(results))

    def test_metrics_have_actor_label(self):
        """Sidecar metrics include the actor label from pod labels."""
        data = _query_prometheus("asya_actor_messages_received_total")
        results = data.get("data", {}).get("result", [])
        if not results:
            pytest.skip("No sidecar metrics available")

        actors_with_label = [
            r for r in results
            if r.get("metric", {}).get("actor")
        ]
        assert len(actors_with_label) > 0, "No metrics have the 'actor' label"
        sample_actor = actors_with_label[0]["metric"]["actor"]
        logger.info("[+] Metrics have actor labels (e.g. '%s')", sample_actor)


# ---------------------------------------------------------------------------
# Logs tests (Loki)
# ---------------------------------------------------------------------------


class TestLogs:
    """Verify Loki collects sidecar and gateway logs."""

    def test_loki_is_healthy(self):
        """Loki is deployed and has labels."""
        url = f"{LOKI_URL}/loki/api/v1/labels"
        data = _kubectl_exec_wget("asya.sh/actor=x-sink", url)
        labels = data.get("data", [])
        assert "container" in labels, f"Loki missing 'container' label. Labels: {labels}"
        logger.info("[+] Loki is healthy with labels: %s", labels)

    def test_sidecar_logs_collected(self):
        """Sidecar container logs are in Loki."""
        data = _query_loki('{container="asya-sidecar"}', limit=3)
        results = data.get("data", {}).get("result", [])
        assert len(results) > 0, "No asya-sidecar logs found in Loki"
        total_entries = sum(len(r.get("values", [])) for r in results)
        logger.info("[+] Found %d sidecar log streams (%d entries)", len(results), total_entries)

    def test_gateway_logs_collected(self):
        """Gateway container logs are in Loki.

        Container name changed from 'gateway' to 'mesh-api' in the new
        multi-container deployment. Query by pod label instead.
        """
        # New deployment uses container="mesh-api"; fall back to pod label selector
        data = _query_loki('{container="mesh-api"}', limit=3)
        results = data.get("data", {}).get("result", [])
        if not results:
            # Try broader pod-level query for backward compat
            data = _query_loki('{pod=~"asya-gateway-.*"}', limit=3)
            results = data.get("data", {}).get("result", [])
        assert len(results) > 0, "No gateway logs found in Loki"
        logger.info("[+] Found %d gateway log streams", len(results))
