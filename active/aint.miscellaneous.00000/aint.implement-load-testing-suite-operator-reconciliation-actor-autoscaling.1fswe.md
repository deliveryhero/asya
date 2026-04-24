---
title: Implement load testing suite for operator reconciliation and actor autoscaling
status: open
priority: 2
---

Measure Asya operator performance and KEDA-based autoscaling under production-like workloads,
and drive reconciliation latency toward P99 < 200ms.

## Current Observations

**Operator Reconciliation Latencies:**
- Without load: p95 ~150ms, p99 ~240ms
- With load: p95 ~210ms, p99 ~460ms (sometimes reaching 1s)

**Benchmarks (from KEDA standards):**
- Healthy: P99 < 100ms
- Warning: 500ms - 2s
- Critical: > 5s

**Status:** Currently in Warning zone under load (460ms-1s P99)

## Foundation: asya-loadtest chart (done — PR #467)

`deploy/helm-charts/asya-loadtest/` provides the load generation layer:
- k6 Job with 4 modes: `transport` (direct SQS/PubSub/RabbitMQ injection),
  `mesh-api`, `a2a`, `mcp`
- 3 scenarios: `echo` (baseline), `slow` (drives queue depth → KEDA scale-up),
  `fanout` (multiplies envelope count)
- Prometheus remote write output (`metrics.prometheus.remoteWriteUrl`)
- Verified in Kind (sqs-s3-pvc): 1,386 envelopes at ~46 req/s, 100% success

## Remaining Work

### 1. Operator Reconciliation Metrics
- Measure `controller_runtime_reconcile_time_seconds` under varying loads
- Track workqueue duration (`workqueue_queue_duration_seconds`)
- Monitor API server throttling (`client_rate_limiter_queries_total`)
- Capture reconciliation errors and failure modes
- Test with varying AsyncActor CRD counts (10, 50, 100, 500) using the
  `slow` scenario at different VU levels to hold queue depth

### 2. KEDA Autoscaling Behavior
- Measure time from queue depth increase to pod scaling (scale-up latency 0 → N)
- Measure scale-down latency (N → 0 pods)
- Monitor `keda_internal_scale_loop_latency_seconds`
- Test external scaler polling frequency vs actual execution (pubsub scaler)
- Track HPA update delays and scaling decision accuracy

### 3. Grafana Dashboard
- Panel: `controller_runtime_reconcile_time_seconds` histogram (p50/p95/p99)
- Panel: KEDA scale-up latency (envelope inject time → first pod ready)
- Panel: k6 throughput + error rate (from remote write)
- Panel: actor queue depth over time
- Ship as a ConfigMap with `grafana_dashboard: "1"` label (auto-imported)

### 4. Performance Report + Tuning
- Run load test with `slow` scenario at 20/50/100 VUs
- Identify bottleneck: operator MaxConcurrentReconciles, KEDA polling interval,
  or transport throughput
- Recommend tuning parameters targeting P99 < 200ms reconciliation

## Acceptance Criteria

- Load test drives sustained queue depth using `asya-loadtest` chart
- Prometheus collects operator + KEDA + k6 metrics for the duration
- Grafana dashboard shows reconciliation latency, autoscaling behavior, and throughput
- Performance report identifies specific bottleneck and recommends a tuning change
- At least one tuning change verified to improve P99

_Migrated from beads `asya-si8`_
