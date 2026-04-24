---
title: OTLP HTTP/protobuf transport support for all Go components
status: pushed
priority: 3 # low
assignee: Artem Yushkovskiy
tags:
  - observability
  - otel
  - debt
  - worktree:.worktrees/hwjzu.otlp-http-protobuf-transport-support-all-go-components
  - branch:hwjzu.otlp-http-protobuf-transport-support-all-go-components
---




## Problem

All Go components that emit traces (`asya-gateway`, `asya-sidecar`) hardcode the OTLP **gRPC**
transport. There is no way to switch to OTLP **HTTP/protobuf** (port 4318) without a code change.
`asya-state-proxy` has no OTel at all.

This blocks adoption in environments where gRPC is restricted or unavailable
(e.g. behind proxies, firewalls that block HTTP/2, or managed collector services that
expose only HTTP endpoints).

The OTel Go SDK does **not** auto-detect the protocol from `OTEL_EXPORTER_OTLP_PROTOCOL` — unlike
Python/Java SDKs. The right exporter package must be explicitly instantiated in code.

## Affected components

| Component | OTel today | What changes |
|-----------|-----------|--------------|
| `asya-gateway` | gRPC traces | Add HTTP/protobuf option |
| `asya-sidecar` | gRPC traces | Add HTTP/protobuf option |
| `asya-state-proxy` | nothing | Out of scope here — tracked in own aint |

Note: `asya-runtime` and `asya-crew` (Python) use the `opentelemetry-sdk` package which
**does** respect `OTEL_EXPORTER_OTLP_PROTOCOL` from the environment automatically.
No Python changes needed.

## Endpoint format gotcha

The two protocols use **different endpoint formats**:

- gRPC: bare `host:4317` (current)
- HTTP: full URL `http://host:4318`

The Helm `tracing.endpoint` field currently documents and assumes gRPC format. When HTTP support
is added, the docs and Helm chart comments must make this explicit, or a separate
`tracing.protocol` field must gate which format is expected.

## Implementation plan

### 1. Go code — both components (`asya-gateway`, `asya-sidecar`)

The two `internal/tracing/tracing.go` files are byte-for-byte identical today. Change both.

**`go.mod`** — add the HTTP exporter package:
```
go get go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp
```

**`tracing.go`** — read `OTEL_EXPORTER_OTLP_PROTOCOL` inside `Init()` and branch:
```go
import (
    "os"
    "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
    "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
)

protocol := os.Getenv("OTEL_EXPORTER_OTLP_PROTOCOL") // "grpc" (default) or "http"
var exporter sdktrace.SpanExporter
if protocol == "http" {
    exporter, err = otlptracehttp.New(ctx, otlptracehttp.WithEndpoint(endpoint))
} else {
    exporter, err = otlptracegrpc.New(ctx, otlptracegrpc.WithEndpoint(endpoint), otlptracegrpc.WithInsecure())
}
```

Reading from env var keeps `Init()` signature unchanged and is consistent with how all other
config is handled in this project.

### 2. Helm charts

**`asya-gateway/values.yaml`** — add `tracing.protocol`:
```yaml
tracing:
  endpoint: ""          # gRPC: host:4317  |  HTTP: http://host:4318
  protocol: "grpc"      # grpc or http
  serviceName: "asya-gateway"
```

**`asya-gateway/templates/deployment.yaml`** — emit the env var when protocol is set:
```yaml
{{- if .Values.tracing.protocol }}
- name: OTEL_EXPORTER_OTLP_PROTOCOL
  value: {{ .Values.tracing.protocol | quote }}
{{- end }}
```

Same change in `asya-crew/values.yaml` + its deployment template (controls sidecar env vars).

### 3. Crossplane XRD / compositions

`asya-crossplane/templates/xrd-asyncactor.yaml` — the `otelEndpoint` field description currently
says "e.g. `tempo:4317`". Update to document both formats and add an `otelProtocol` field.

`composition-*.yaml` files (pubsub, sqs, rabbitmq) — emit `OTEL_EXPORTER_OTLP_PROTOCOL` into
sidecar env when the field is set.

### 4. Playground values

`asya-playground/values.yaml` comments reference "Tempo's OTLP gRPC endpoint" — update to
note that HTTP uses port 4318 and full URL format.

## Files to touch

```
src/asya-gateway/go.mod
src/asya-gateway/internal/tracing/tracing.go
src/asya-sidecar/go.mod
src/asya-sidecar/internal/tracing/tracing.go
deploy/helm-charts/asya-gateway/values.yaml
deploy/helm-charts/asya-gateway/templates/deployment.yaml
deploy/helm-charts/asya-crew/values.yaml
deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml
deploy/helm-charts/asya-crossplane/templates/composition-pubsub.yaml
deploy/helm-charts/asya-crossplane/templates/composition-sqs.yaml
deploy/helm-charts/asya-crossplane/templates/composition-rabbitmq.yaml
deploy/helm-charts/asya-playground/values.yaml
```

## Cost estimate

**Small** — ~2–4 hours.

- Go code change is trivial: one conditional, one import per component.
- Helm changes are mechanical: one new field, one new env var block.
- Crossplane compositions are additive: new optional field plumbed through.
- No test changes needed — existing unit tests don't mock the exporter factory.

The only risk is the endpoint format split (gRPC vs HTTP expect different string shapes).
This must be documented clearly to avoid user confusion at deploy time.
