---
title: "Research: SigNoz as alternative to Prometheus/Grafana for observability"
priority: 3 # low
tags:
  - type:feature
reason: not cncf-native
---




## Research Objective

Evaluate SigNoz (https://signoz.io/) as a unified observability platform for Asya, potentially replacing the traditional Prometheus + Grafana + Jaeger/Tempo stack.

## Why Consider SigNoz?

**Current stack complexity:**
- Prometheus for metrics
- Grafana for dashboards
- Jaeger/Tempo for traces
- Loki for logs
- Multiple operators, configs, and integrations to maintain

**SigNoz value proposition:**
- Single platform for metrics, traces, and logs
- OpenTelemetry-native (OTLP ingestion)
- ClickHouse backend (fast queries, efficient storage)
- Built-in dashboards and alerting
- Open source (Apache 2.0)

## Key Research Questions

### 1. Architecture fit with Asya

- How does SigNoz integrate with KEDA-scaled workloads?
- Can it handle bursty, scale-to-zero actor patterns?
- What's the resource footprint vs Prometheus+Grafana+Jaeger?

### 2. OpenTelemetry integration

Asya components could emit OTLP directly:
- Gateway: request traces, tool call metrics
- Sidecar: envelope routing spans, queue metrics
- Runtime: handler execution traces
- Operator: reconciliation metrics

Questions:
- What SDKs/auto-instrumentation available for Go and Python?
- How to correlate traces across async message passing?
- Envelope ID as trace context propagation?

### 3. ClickHouse considerations

- Self-hosted vs SigNoz Cloud?
- ClickHouse operational complexity
- Data retention and storage costs
- Query performance for high-cardinality actor metrics

### 4. Migration path

If adopting SigNoz:
- Can it coexist with Prometheus during migration?
- Prometheus remote-write to SigNoz?
- Dashboard migration from Grafana?

### 5. Comparison matrix

| Feature | Prometheus+Grafana+Jaeger | SigNoz |
|---------|---------------------------|--------|
| Metrics | ✅ | ✅ |
| Traces | ✅ (separate) | ✅ (unified) |
| Logs | ❌ (need Loki) | ✅ |
| Single pane | ❌ | ✅ |
| OTLP native | ❌ | ✅ |
| Helm chart | Multiple | Single |
| Resource usage | ? | ? |

## Research Deliverables

1. **PoC deployment** of SigNoz in Kind cluster
2. **Instrumentation spike** for one Asya component (sidecar or gateway)
3. **Comparison doc** with resource usage, query performance, UX
4. **Decision recommendation** with migration plan if adopting

## Links

- SigNoz docs: https://signoz.io/docs/
- SigNoz GitHub: https://github.com/SigNoz/signoz
- OpenTelemetry Go SDK: https://opentelemetry.io/docs/languages/go/
- OpenTelemetry Python SDK: https://opentelemetry.io/docs/languages/python/

NOTE: SigNoz is not CNCF-incubated (only CNCF golden sponsor), for asya it's best to use CNCF stack.


---
## Notes

## Observability 2.0 angle

**Link:** https://www.cncf.io/blog/2025/01/27/what-is-observability-2-0/

**Key insight from the article:**
> "2.0: Maps telemetry data to business metrics, ensuring decisions align with organizational goals."

**Why this matters for Asya:**

Data scientists using Asya are much closer to business metrics than typical backend/platform engineers:
- They understand what "model accuracy dropped 2%" means for revenue
- They can define SLOs in business terms, not just latency/error rates
- They know which flows are critical for business outcomes

**Opportunity:**
- Let users define custom business metrics alongside their flows
- Flow DSL could include metric definitions: `@metric("prediction_confidence", p["score"])`
- SigNoz (or any OTLP backend) could track these as first-class metrics
- Dashboards show business KPIs, not just infra health

**Example - ML inference flow:**
```python
def sentiment_analysis(p: dict) -> dict:
    p = preprocess(p)
    p = model_inference(p)
    
    # User-defined business metric
    emit_metric("sentiment_confidence", p["confidence"])
    emit_metric("sentiment_class", p["sentiment"], type="counter")
    
    return p
```

**This bridges the gap:**
- Platform engineers see: requests/sec, p99 latency, error rate
- Data scientists see: predictions/sec, confidence distribution, model drift
- Business sees: customer sentiment trend, processing cost per prediction

**Research addition:**
- Explore how Flow DSL could embed metric definitions
- How SigNoz handles custom business metrics
- Can we auto-generate dashboards from flow metric annotations?


---
_Migrated from beads `asya-sut`_
