---
title: Implement load testing suite for operator reconciliation and actor autoscaling
priority: 2 # medium
---



Create comprehensive load testing infrastructure to measure Asya operator performance and KEDA-based autoscaling under production-like workloads.

## Current Observations

**Operator Reconciliation Latencies:**
- Without load: p95 ~150ms, p99 ~240ms
- With load: p95 ~210ms, p99 ~460ms (sometimes reaching 1s)

**Benchmarks (from KEDA standards):**
- Healthy: P99 < 100ms
- Warning: 500ms - 2s
- Critical: > 5s

**Status:** Currently in Warning zone under load (460ms-1s P99)

## Requirements

### 1. Operator Reconciliation Metrics
- Measure `controller_runtime_reconcile_time_seconds` under varying loads
- Track workqueue duration (`workqueue_queue_duration_seconds`)
- Monitor API server throttling (`client_rate_limiter_queries_total`)
- Capture reconciliation errors and failure modes
- Test with varying numbers of AsyncActor CRDs (10, 50, 100, 500)

### 2. Actor Autoscaling Behavior
- Measure time from queue depth increase to pod scaling
- Track scale-up latency (0 → N pods)
- Track scale-down latency (N → 0 pods)
- Monitor KEDA ScaledObject reconciliation times
- Test with different queue depths and burst patterns

### 3. KEDA Integration Efficiency
- Measure `keda_internal_scale_loop_latency_seconds`
- Test external scaler polling frequency vs actual execution
- Monitor HPA update delays
- Track scaling decision accuracy

### 4. System Bottlenecks
- Identify CPU/memory hotspots in operator
- Monitor transport queue performance (RabbitMQ/SQS)
- Track end-to-end envelope latency (gateway → actor → happy-end)
- Measure resource utilization patterns

## Deliverables

1. Load testing framework (likely k6 or locust)
2. Prometheus metrics collection configuration
3. Grafana dashboard for reconciliation latencies
4. Performance report with p50/p95/p99 latencies
5. Recommendations for concurrency tuning (MaxConcurrentReconciles)
6. Documentation of bottlenecks and optimization opportunities

## Acceptance Criteria

- Load tests run against Kind cluster with realistic workloads
- Metrics collected for operator, KEDA, and actors
- Performance report identifies specific bottlenecks
- Recommendations provided for achieving P99 < 200ms target


---
_Migrated from beads `asya-si8`_
