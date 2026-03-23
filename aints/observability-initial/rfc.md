# RFC: Distributed Tracing — OTEL Instrumentation + Tempo in Grafana

**Aint**: `kvx0`
**Status**: Draft
**Date**: 2026-03-23

## Goal

Add end-to-end distributed tracing to Asya so that a user can trace a single
message through the actor mesh — from gateway ingress through each sidecar hop
to x-sink. Traces are viewable in Grafana via Tempo, including a service graph
topology map.

## Scope

### In Scope

- OTEL trace instrumentation in **sidecar** (Go) and **gateway** (Go)
- W3C Trace Context propagation via `envelope.headers.traceparent` / `tracestate`
- **Grafana Tempo** as trace backend (official Helm subchart in playground)
- Grafana integration: datasource provisioning, service graph, trace exploration
- Helm chart changes: XRD field `spec.tracing.endpoint`, env var injection
- Unit tests + component test with Tempo

### Not In Scope

- Python runtime instrumentation (runtime stays dependency-free)
- CLI trace viewer (`asya k trace` — separate aint `a38s`)
- Loki / trace-to-logs correlation (no Loki deployed yet)
- OTEL Collector intermediary (direct OTLP export)
- GKE deployment (separate task after Kind validation)
- Transport-level trace propagation (envelope headers only)

## Architecture

### OTEL SDK Initialization

Each component has its own `internal/tracing/` package:

**Sidecar** (`src/asya-sidecar/internal/tracing/tracing.go`):

```go
func Init(serviceName, namespace string) (shutdown func(context.Context) error, err error)
```

- Creates `TracerProvider` with explicit `otlptracegrpc.New()` exporter, reading
  `OTEL_EXPORTER_OTLP_ENDPOINT` from config. ~40-50 lines of init code.
- Sets resource attributes: `service.name` (programmatically from `ASYA_ACTOR_NAME`),
  `service.namespace` (from `ASYA_NAMESPACE`). Users can override via `OTEL_SERVICE_NAME`
  env var if needed (standard OTEL SDK precedence).
- No-op when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset — zero overhead, returns noop tracer
- Called in `main.go` after config load; `defer shutdown(ctx)` on exit
- **Timeout edge case**: Sidecar calls `os.Exit(1)` on runtime timeout, which
  bypasses deferred shutdown. `ForceFlush(ctx)` must be called before `os.Exit`
  to ensure the timed-out span is exported.

**Gateway** (`src/asya-gateway/internal/tracing/tracing.go`):

- Same pattern
- `service.name` = `asya-gateway-api` or `asya-gateway-mesh` (from mode)

### Environment Variables

Standard OTEL env vars — no custom ones:

| Var | Example | Source |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://tempo:4317` | `spec.tracing.endpoint` or Helm value |
| `OTEL_TRACES_SAMPLER` | `parentbased_traceidratio` | Optional, via `spec.sidecar.env[]` passthrough |
| `OTEL_TRACES_SAMPLER_ARG` | `0.1` | Optional, via `spec.sidecar.env[]` passthrough |

`service.name` is set programmatically from `ASYA_ACTOR_NAME` (sidecar) or the
gateway mode (gateway). Users can override via `OTEL_SERVICE_NAME` through the
standard sidecar env passthrough if needed.

### Sidecar Span Structure

The sidecar creates spans around the envelope processing lifecycle in
`Router.ProcessMessage()`:

```
actor.process                              <- root span per envelope
|-- attributes: asya.actor, asya.envelope_id, asya.queue, asya.flow
|
|-- actor.runtime.call                     <- wraps CallRuntime() HTTP POST
|   |-- attributes: http.method, http.status_code
|   +-- events: response frame count
|
|-- actor.resiliency.retry                 <- one per retry attempt
|   |-- attributes: asya.retry.attempt, asya.retry.policy
|   +-- actor.runtime.call                 <- retried runtime call
|
|-- actor.resiliency.timeout               <- timeout span (if triggered)
|   +-- attributes: asya.timeout.duration, asya.timeout.policy
|
+-- actor.queue.send                       <- per outgoing envelope
    +-- attributes: asya.destination_queue, asya.message_type (routing/sink/sump)
```

**Trace context propagation** (async messaging model):

Asya uses asynchronous queue-based messaging. OTEL span kinds reflect this:
- Gateway `queue.send` spans use `SpanKindProducer` — they end when the message
  is enqueued.
- Sidecar `actor.process` spans use `SpanKindConsumer` — they extract the
  parent trace context from the envelope, continuing the same trace (same trace
  ID) but as a new span tree. The consumer span does not extend the producer
  span's duration.

This is the standard OTEL messaging instrumentation pattern (same as Kafka,
RabbitMQ, SQS OTEL instrumentation libraries).

- **Inbound**: Extract `traceparent` + `tracestate` from `envelope.headers`
  using W3C `propagation.TraceContext` propagator. Creates a `SpanKindConsumer`
  span continuing the trace from the upstream producer.
- **Outbound**: `actor.queue.send` uses `SpanKindProducer`. Inject updated
  `traceparent` + `tracestate` into outgoing envelope's `headers` map before
  queue send. The producer span ends when the message is enqueued.
- **Fan-out**: First yield keeps the current span context (preserves `msg.id`).
  Each child envelope gets a new child `SpanKindProducer` span with its own
  `traceparent`, all sharing the same trace ID. This mirrors the `msg.id` /
  `msg.parent_id` pattern.
- **Handler header override**: If a handler overwrites headers via
  `yield "SET", ".headers", {...}`, the sidecar re-injects trace context into
  the outgoing envelope **after** the header merge logic in
  `handleSuccessResponse` / `routeResponse`. Trace context is sidecar-managed
  and always takes precedence over handler-set `traceparent`/`tracestate`.

**User access**: Handlers can read trace context via
`yield "GET", ".headers.traceparent"` for custom instrumentation.

### Gateway Span Structure

The gateway creates the **root span** — where `traceparent` is born:

```
gateway.task.execute                       <- root span (Executor.Execute())
|-- attributes: asya.task_id, asya.context_id, asya.actor, asya.flow
|
+-- gateway.queue.send                     <- dispatch to actor queue
    +-- attributes: asya.destination_queue
```

**HTTP middleware**: `otelhttp` wraps A2A and MCP handlers, creating a parent
span for each HTTP request. Gives visibility into HTTP latency vs processing.

**Mesh gateway** (`mode=mesh`): Status/progress/FLY callbacks get basic HTTP
spans via `otelhttp` middleware for free. No custom spans needed.

**Trace context injection**: `BuildA2AHeaders()` in `translator.go` injects
`traceparent` alongside existing `x-asya-a2a-task-id` and
`x-asya-a2a-context-id` headers.

### End-to-End Trace Example

A 3-actor flow (`actor-a -> actor-b -> actor-c`) produces this trace.
All spans share the same trace ID. Producer spans end at enqueue time;
consumer spans start when the sidecar dequeues. Tempo/Grafana renders
them as a connected waterfall despite the async gaps:

```
[gateway]  gateway.task.execute -----
             +-- gateway.queue.send -   (SpanKindProducer, ends at enqueue)

                     ... queue transit ...

[actor-a]  actor-a.process ---------    (SpanKindConsumer, extracts traceparent)
             |-- actor-a.runtime.call ---
             +-- actor-a.queue.send -   (SpanKindProducer)

                     ... queue transit ...

[actor-b]  actor-b.process ---------    (SpanKindConsumer)
             |-- actor-b.runtime.call ---
             +-- actor-b.queue.send -   (SpanKindProducer)

                     ... queue transit ...

[actor-c]  actor-c.process ---------    (SpanKindConsumer)
             |-- actor-c.runtime.call ---
             +-- actor-c.queue.send -   (SpanKindProducer, to x-sink)
```

## Tempo Deployment (Playground Chart)

### Subchart Dependency

```yaml
# deploy/helm-charts/asya-playground/Chart.yaml
dependencies:
  - name: tempo
    version: "~1.x"
    repository: https://grafana.github.io/helm-charts
    condition: sampleTracing.enabled
```

### Values

Approximate values for the `grafana/tempo` chart (single-binary / monolithic mode).
Exact schema must be verified against `helm show values grafana/tempo` during
implementation — the Prometheus remote-write URL depends on the kube-prometheus-stack
release name (e.g. `http://asya-monitoring-prometheus:9090/api/v1/write`).

```yaml
sampleTracing:
  enabled: false

tempo:
  tempo:
    storage:
      trace:
        backend: local
    retention: 24h
    metricsGenerator:
      enabled: true
      remoteWriteUrl: "http://<prometheus-service>:9090/api/v1/write"
    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: "0.0.0.0:4317"
          http:
            endpoint: "0.0.0.0:4318"
```

### Grafana Integration

Datasource auto-provisioning via kube-prometheus-stack:

```yaml
kube-prometheus-stack:
  grafana:
    additionalDataSources:
      - name: Tempo
        type: tempo
        url: http://tempo:3100
        access: proxy
        isDefault: false
        jsonData:
          tracesToMetricsEnabled: true
          tracesToMetrics:
            datasourceUid: prometheus
          serviceMap:
            datasourceUid: prometheus
```

This enables:
- Trace exploration in Grafana Explore (search by trace ID, service, attributes)
- Trace waterfall visualization (span tree view)
- TraceQL queries (e.g. `{resource.service.name="my-actor"}`)
- Service graph topology map (actors as nodes, edges showing request rates)
- Trace-to-metrics linking (click span attribute to open Prometheus query)

Grafana dashboards/panels for trace exploration and service topology will be
prototyped and iterated during implementation.

## Helm Chart Changes

### Crossplane Chart (`asya-crossplane`)

**XRD** (`xrd-asyncactor.yaml`): New optional field:

```yaml
spec:
  tracing:
    endpoint:
      type: string
      description: "OTLP endpoint for distributed tracing (e.g. http://tempo:4317)"
```

**Compositions** (all 3 — SQS, RabbitMQ, Pub/Sub): Inject into sidecar env:

```yaml
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: {{ .tracing.endpoint }}
```

Only injected when `spec.tracing.endpoint` is set (empty = tracing disabled).

### Gateway Chart (`asya-gateway`)

**values.yaml**: New field:

```yaml
tracing:
  endpoint: ""  # e.g. http://tempo:4317
```

**deployment-api.yaml** and **deployment-mesh.yaml**: Inject env var when set.

### Crew Chart (`asya-crew`)

Crew actors are AsyncActor CRDs rendered by Crossplane. The full config chain:
1. Crew chart `values.yaml` gets a `tracing.endpoint` field
2. Crew chart templates inject it into each AsyncActor CR's `spec.tracing.endpoint`
3. The XRD validates the field
4. The Crossplane composition injects `OTEL_EXPORTER_OTLP_ENDPOINT` into the
   sidecar env block

This enables x-sink, x-sump, x-pause, x-resume to participate in traces.

### Playground Chart

When `sampleTracing.enabled=true`, auto-wire `OTEL_EXPORTER_OTLP_ENDPOINT` to
the Tempo service URL for gateway values.

## Testing Strategy

### Unit Tests (Sidecar)

- Trace context extraction from envelope headers (mock with `traceparent`)
- Trace context injection into outgoing envelope headers
- Fan-out: children get new span IDs, same trace ID
- No-op when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset
- Resiliency retry spans: correct parent-child relationships
- Use OTEL SDK in-memory span exporter for assertions

### Unit Tests (Gateway)

- Root span creation in `Executor.Execute()`
- `traceparent` injection into envelope headers via `BuildA2AHeaders()`
- In-memory span exporter

### Component Test (Docker Compose)

- Sidecar + runtime + Tempo in Compose
- Send envelope through 2-3 actor hops
- Query Tempo HTTP API (`GET /api/traces/{traceID}`)
- Assert span count matches expected hops
- Assert parent-child relationships are correct

## Key Design Decisions

| Decision | Rationale |
|---|---|
| Independent OTEL init per component | Sidecar and gateway are separate Go modules with separate release cycles |
| Envelope headers only (no transport metadata) | Transport-agnostic, simpler, sufficient for trace propagation |
| `spec.tracing.endpoint` at actor level | Future-proofs for runtime OTEL (not just sidecar) |
| No-op when endpoint unset | Zero overhead for users who don't need tracing |
| Direct OTLP to Tempo (no Collector) | Simpler, Tempo accepts OTLP natively, users can point at any OTLP backend |
| Official Tempo Helm subchart | Maintained by Grafana, no custom templates needed |
| Explicit `otlptracegrpc` exporter | Stable, well-documented, ~40-50 lines init code |
| `SpanKindProducer`/`Consumer` | Correct OTEL semantics for async queue-based messaging |
| Trace ID stored in envelope headers | Gateway can store trace ID in PostgreSQL for direct "View Trace" links |

## Related Aints

| Aint | Relationship |
|---|---|
| `a38s` | Overlaps: sidecar spans + runtime spans + CLI. `kvx0` is foundational; `a38s` extends with Python runtime spans and `asya k trace` CLI |
| `1f4g` | User metrics env vars for runtime container — complementary, not overlapping |
| `1fbs` | Retry/error tracing — partially covered by resiliency spans in `kvx0` |
| `ldx4` | KubeCon demo metrics/dashboards — `kvx0` adds tracing alongside existing metrics |

## Files Changed (Expected)

| File | Change |
|---|---|
| `src/asya-sidecar/internal/tracing/tracing.go` | New: OTEL SDK init |
| `src/asya-sidecar/internal/router/router.go` | Span instrumentation in ProcessMessage |
| `src/asya-sidecar/internal/runtime/client.go` | Span around CallRuntime |
| `src/asya-sidecar/go.mod` | Add OTEL SDK + otlptracegrpc deps |
| `src/asya-gateway/internal/tracing/tracing.go` | New: OTEL SDK init |
| `src/asya-gateway/internal/a2a/executor.go` | Root span in Execute |
| `src/asya-gateway/internal/a2a/translator.go` | traceparent injection |
| `src/asya-gateway/cmd/gateway/main.go` | Init tracing, otelhttp middleware |
| `src/asya-gateway/go.mod` | Add OTEL SDK + otlptracegrpc deps |
| `deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml` | `spec.tracing.endpoint` field |
| `deploy/helm-charts/asya-crossplane/templates/composition-*.yaml` | OTEL env var injection (x3) |
| `deploy/helm-charts/asya-gateway/values.yaml` | `tracing.endpoint` |
| `deploy/helm-charts/asya-gateway/templates/deployment-*.yaml` | OTEL env var (x2) |
| `deploy/helm-charts/asya-crew/values.yaml` | `tracing.endpoint` per-actor |
| `deploy/helm-charts/asya-playground/Chart.yaml` | Tempo subchart dependency |
| `deploy/helm-charts/asya-playground/values.yaml` | `sampleTracing` config, Grafana datasource |
| `deploy/grafana-dashboards/` | Trace exploration / service graph panels |
| `src/asya-sidecar/internal/tracing/tracing_test.go` | Unit tests |
| `src/asya-gateway/internal/tracing/tracing_test.go` | Unit tests |
| `testing/component/tracing/` | Component test with Tempo |
| `docs/concepts/observability.md` | Update: distributed tracing section — currently aspirational ("every envelope carries a trace_id"), rewrite to reflect actual implementation (W3C traceparent, OTEL spans, Tempo backend) |
| `docs/setup/ops-observability.md` | Update: remove "Future: OpenTelemetry tracing" item, add tracing setup section (env vars, Tempo config, Grafana datasource, example TraceQL queries) |
| `docs/reference/specs/envelope.md` | Update: document `traceparent` and `tracestate` as sidecar-managed headers in the envelope headers spec |
