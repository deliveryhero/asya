# Distributed Tracing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add end-to-end OTEL distributed tracing to sidecar and gateway, with Grafana Tempo backend in the playground chart.

**Architecture:** Independent `internal/tracing/` packages in sidecar and gateway init OTEL TracerProviders with `otlptracegrpc` exporters. Sidecar creates spans around envelope processing (receive, runtime call, resiliency, queue send) using `SpanKindConsumer`/`SpanKindProducer` semantics. Gateway creates root spans on task execution. Trace context propagates via W3C `traceparent`/`tracestate` in envelope headers. Grafana Tempo deployed as a Helm subchart in the playground.

**Tech Stack:** Go OTEL SDK (`go.opentelemetry.io/otel/sdk`), `otlptracegrpc` exporter, W3C Trace Context propagation, Grafana Tempo Helm chart, kube-prometheus-stack Grafana datasource provisioning.

**Spec:** `.aint/aints/observability-initial/rfc.md`

---

## File Structure

### New Files

| File | Responsibility |
|---|---|
| `src/asya-sidecar/internal/tracing/tracing.go` | OTEL TracerProvider init, shutdown, no-op detection |
| `src/asya-sidecar/internal/tracing/propagation.go` | Extract/inject traceparent from/to envelope headers |
| `src/asya-sidecar/internal/tracing/tracing_test.go` | Unit tests for init + propagation |
| `src/asya-gateway/internal/tracing/tracing.go` | OTEL TracerProvider init (same pattern, gateway-specific) |
| `src/asya-gateway/internal/tracing/tracing_test.go` | Unit tests for gateway tracing init |
| `deploy/helm-charts/asya-playground/templates/sample-tracing/` | Tempo templates (if not using subchart for everything) |
| `testing/component/tracing/` | Component test: multi-hop trace verification via Tempo API |

### Modified Files

| File | Change |
|---|---|
| `src/asya-sidecar/cmd/sidecar/main.go` | Init tracing after metrics (~line 245), defer shutdown |
| `src/asya-sidecar/internal/router/router.go` | Span instrumentation in ProcessMessage, handleSuccessResponse, handleErrorResponse, applyPolicy, routeResponse |
| `src/asya-sidecar/internal/runtime/client.go` | Span around CallRuntime HTTP POST |
| `src/asya-sidecar/go.mod` | Add OTEL SDK + otlptracegrpc direct deps |
| `src/asya-gateway/cmd/gateway/main.go` | Init tracing, otelhttp middleware on routes |
| `src/asya-gateway/internal/a2a/executor.go` | Root span in Execute(), span in handleResume() |
| `src/asya-gateway/internal/a2a/translator.go` | Inject traceparent in BuildA2AHeaders() |
| `src/asya-gateway/go.mod` | Add OTEL SDK + otlptracegrpc + otelhttp direct deps |
| `deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml` | Add `spec.tracing` field (~after line 309) |
| `deploy/helm-charts/asya-crossplane/templates/composition-sqs.yaml` | Inject OTEL env vars into sidecar (~line 559) |
| `deploy/helm-charts/asya-crossplane/templates/composition-rabbitmq.yaml` | Same OTEL env var injection |
| `deploy/helm-charts/asya-crossplane/templates/composition-pubsub.yaml` | Same OTEL env var injection |
| `deploy/helm-charts/asya-gateway/values.yaml` | Add `tracing:` section |
| `deploy/helm-charts/asya-gateway/templates/deployment-api.yaml` | Inject tracing env vars (~line 113) |
| `deploy/helm-charts/asya-gateway/templates/deployment-mesh.yaml` | Inject tracing env vars (~line 105) |
| `deploy/helm-charts/asya-crew/values.yaml` | Add `tracing.endpoint` field per-actor |
| `deploy/helm-charts/asya-crew/templates/sink.yaml` | Inject `spec.tracing.endpoint` into AsyncActor CR |
| `deploy/helm-charts/asya-crew/templates/sump.yaml` | Same |
| `deploy/helm-charts/asya-crew/templates/pause.yaml` | Same |
| `deploy/helm-charts/asya-crew/templates/resume.yaml` | Same |
| `deploy/helm-charts/asya-playground/Chart.yaml` | Add Tempo subchart dependency |
| `deploy/helm-charts/asya-playground/values.yaml` | Add `sampleTracing` config, Grafana Tempo datasource |
| `docs/concepts/observability.md` | Update tracing section from aspirational to actual |
| `docs/setup/ops-observability.md` | Add tracing setup guide, remove "Future" item |
| `docs/reference/specs/envelope.md` | Document traceparent/tracestate as sidecar-managed headers |

---

## Task 1: Sidecar OTEL SDK Init + No-Op Detection

**Files:**
- Create: `src/asya-sidecar/internal/tracing/tracing.go`
- Create: `src/asya-sidecar/internal/tracing/tracing_test.go`
- Modify: `src/asya-sidecar/cmd/sidecar/main.go:245-248`
- Modify: `src/asya-sidecar/go.mod`

- [ ] **Step 1: Add OTEL SDK dependencies to sidecar go.mod**

```bash
cd src/asya-sidecar
go get go.opentelemetry.io/otel/sdk@latest
go get go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc@latest
go mod tidy
```

Note: `sdk/resource` is part of `otel/sdk`, no separate `go get` needed.
Use the semconv version matching the installed SDK (check `go list -m go.opentelemetry.io/otel/sdk`).

- [ ] **Step 2: Write failing test for tracing init**

Create `src/asya-sidecar/internal/tracing/tracing_test.go`:

```go
package tracing

import (
	"context"
	"testing"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/trace"
	"go.opentelemetry.io/otel/trace/noop"
)

// resetGlobalTracer restores the global OTEL state after each test.
// Tests that call Init() modify global state, so cleanup is required.
func resetGlobalTracer(t *testing.T) {
	t.Helper()
	t.Cleanup(func() {
		otel.SetTracerProvider(noop.NewTracerProvider())
	})
}

func TestInit_NoEndpoint_ReturnsNoopTracer(t *testing.T) {
	resetGlobalTracer(t)

	shutdown, err := Init("", "test-actor", "test-ns")
	if err != nil {
		t.Fatalf("Init() error = %v", err)
	}
	defer shutdown(context.Background())

	tracer := otel.Tracer("test")
	_, span := tracer.Start(context.Background(), "test-span")
	defer span.End()

	if span.IsRecording() {
		t.Error("expected non-recording span when endpoint is empty")
	}
}

func TestInit_WithEndpoint_ReturnsRecordingTracer(t *testing.T) {
	resetGlobalTracer(t)

	shutdown, err := Init("localhost:4317", "test-actor", "test-ns")
	if err != nil {
		t.Fatalf("Init() error = %v", err)
	}
	defer shutdown(context.Background())

	tracer := otel.Tracer("test")
	_, span := tracer.Start(context.Background(), "test-span")
	defer span.End()

	if !span.IsRecording() {
		t.Error("expected recording span when endpoint is set")
	}
}
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd src/asya-sidecar && go test ./internal/tracing/ -v -run TestInit
```

Expected: compilation error — `Init` not defined.

- [ ] **Step 4: Implement tracing init**

Create `src/asya-sidecar/internal/tracing/tracing.go`:

```go
package tracing

import (
	"context"
	"fmt"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
	"go.opentelemetry.io/otel/trace/noop"
)

// Init sets up the OTEL TracerProvider. Returns a shutdown function.
// If endpoint is empty, registers a no-op tracer (zero overhead).
func Init(endpoint, serviceName, namespace string) (func(context.Context) error, error) {
	if endpoint == "" {
		tp := noop.NewTracerProvider()
		otel.SetTracerProvider(tp)
		return func(ctx context.Context) error { return nil }, nil
	}

	ctx := context.Background()

	exporter, err := otlptracegrpc.New(ctx,
		otlptracegrpc.WithEndpoint(endpoint),
		otlptracegrpc.WithInsecure(),
	)
	if err != nil {
		return nil, fmt.Errorf("create OTLP exporter: %w", err)
	}

	res, err := resource.New(ctx,
		resource.WithAttributes(
			semconv.ServiceNameKey.String(serviceName),
			semconv.ServiceNamespaceKey.String(namespace),
		),
	)
	if err != nil {
		return nil, fmt.Errorf("create resource: %w", err)
	}

	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter),
		sdktrace.WithResource(res),
	)

	otel.SetTracerProvider(tp)
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	))

	return tp.Shutdown, nil
}
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd src/asya-sidecar && go test ./internal/tracing/ -v -run TestInit
```

Expected: PASS

- [ ] **Step 6: Wire tracing init into main.go**

Modify `src/asya-sidecar/cmd/sidecar/main.go`. After metrics init (~line 245) and before router creation (~line 248), add:

```go
	// Tracing (OTEL)
	otelEndpoint := os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
	tracingShutdown, err := tracing.Init(otelEndpoint, cfg.ActorName, cfg.Namespace)
	if err != nil {
		slog.Error("Failed to initialize tracing", "error", err)
		os.Exit(1)
	}
	defer tracingShutdown(context.Background())
	if otelEndpoint != "" {
		slog.Info("Tracing enabled", "endpoint", otelEndpoint)
	}
```

Add import: `"github.com/deliveryhero/asya/asya-sidecar/internal/tracing"`

- [ ] **Step 7: Run full sidecar unit tests**

```bash
cd src/asya-sidecar && go test ./... -count=1
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/asya-sidecar/internal/tracing/ src/asya-sidecar/cmd/sidecar/main.go src/asya-sidecar/go.mod src/asya-sidecar/go.sum
git commit -m "feat(sidecar): add OTEL tracing init with no-op detection [kvx0]"
```

---

## Task 2: Sidecar Trace Context Propagation (Extract/Inject)

**Files:**
- Create: `src/asya-sidecar/internal/tracing/propagation.go`
- Modify: `src/asya-sidecar/internal/tracing/tracing_test.go`

- [ ] **Step 1: Write failing test for trace context extraction**

Add to `tracing_test.go`:

```go
func TestExtractTraceContext_ValidTraceparent(t *testing.T) {
	// Set up a real tracer for propagation
	shutdown, _ := Init("localhost:4317", "test", "test")
	defer shutdown(context.Background())

	headers := map[string]interface{}{
		"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
		"custom":      "preserved",
	}

	ctx := ExtractTraceContext(context.Background(), headers)
	sc := trace.SpanContextFromContext(ctx)

	if !sc.IsValid() {
		t.Fatal("expected valid span context")
	}
	if sc.TraceID().String() != "4bf92f3577b34da6a3ce929d0e0e4736" {
		t.Errorf("trace ID = %s, want 4bf92f3577b34da6a3ce929d0e0e4736", sc.TraceID())
	}
}

func TestExtractTraceContext_NoTraceparent(t *testing.T) {
	shutdown, _ := Init("localhost:4317", "test", "test")
	defer shutdown(context.Background())

	headers := map[string]interface{}{"custom": "value"}
	ctx := ExtractTraceContext(context.Background(), headers)
	sc := trace.SpanContextFromContext(ctx)

	if sc.IsValid() {
		t.Error("expected invalid span context when no traceparent")
	}
}

func TestInjectTraceContext_WritesTraceparent(t *testing.T) {
	shutdown, _ := Init("localhost:4317", "test", "test")
	defer shutdown(context.Background())

	tracer := otel.Tracer("test")
	ctx, span := tracer.Start(context.Background(), "test-span")
	defer span.End()

	headers := map[string]interface{}{"custom": "preserved"}
	InjectTraceContext(ctx, headers)

	tp, ok := headers["traceparent"]
	if !ok {
		t.Fatal("traceparent not injected")
	}
	if tp.(string) == "" {
		t.Error("traceparent is empty")
	}
	if headers["custom"] != "preserved" {
		t.Error("existing headers were lost")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd src/asya-sidecar && go test ./internal/tracing/ -v -run TestExtract
```

Expected: compilation error — `ExtractTraceContext` not defined.

- [ ] **Step 3: Implement propagation helpers**

Create `src/asya-sidecar/internal/tracing/propagation.go`:

```go
package tracing

import (
	"context"
	"fmt"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"
)

// headerCarrier adapts envelope headers map to OTEL TextMapCarrier.
type headerCarrier map[string]interface{}

func (c headerCarrier) Get(key string) string {
	v, ok := c[key]
	if !ok {
		return ""
	}
	return fmt.Sprintf("%v", v)
}

func (c headerCarrier) Set(key, value string) {
	c[key] = value
}

func (c headerCarrier) Keys() []string {
	keys := make([]string, 0, len(c))
	for k := range c {
		keys = append(keys, k)
	}
	return keys
}

// ExtractTraceContext reads traceparent/tracestate from envelope headers
// and returns a context with the extracted span context.
func ExtractTraceContext(ctx context.Context, headers map[string]interface{}) context.Context {
	if headers == nil {
		return ctx
	}
	return otel.GetTextMapPropagator().Extract(ctx, headerCarrier(headers))
}

// InjectTraceContext writes traceparent/tracestate from the current span
// context into envelope headers. Existing non-trace headers are preserved.
func InjectTraceContext(ctx context.Context, headers map[string]interface{}) {
	otel.GetTextMapPropagator().Inject(ctx, headerCarrier(headers))
}
```

- [ ] **Step 4: Run all tracing tests**

```bash
cd src/asya-sidecar && go test ./internal/tracing/ -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asya-sidecar/internal/tracing/
git commit -m "feat(sidecar): trace context extract/inject via envelope headers [kvx0]"
```

---

## Task 3: Sidecar Router Span Instrumentation

**Files:**
- Modify: `src/asya-sidecar/internal/router/router.go`
- Modify: `src/asya-sidecar/internal/router/router_test.go` (if span assertions needed)

This is the largest task — instrumenting the core message processing loop.

- [ ] **Step 1: Add tracer field to Router struct**

In `router.go` (~line 32), add a tracer field:

```go
import "go.opentelemetry.io/otel/trace"

type Router struct {
	// ... existing fields ...
	tracer trace.Tracer
}
```

In `NewRouter()`, initialize it:

```go
func NewRouter(/* existing params */) *Router {
	return &Router{
		// ... existing fields ...
		tracer: otel.Tracer("asya-sidecar"),
	}
}
```

Add import: `"go.opentelemetry.io/otel"`

- [ ] **Step 2: Instrument ProcessMessage with root span**

In `ProcessMessage()` (~line 703), after parsing the envelope, add the root span:

```go
func (r *Router) ProcessMessage(ctx context.Context, queueMsg transport.QueueMessage) error {
	startTime := time.Now()

	// Parse envelope
	msg, err := r.parseAndValidateMessage(queueMsg)
	if err != nil {
		// ... existing error handling ...
	}

	// Extract trace context from envelope headers
	ctx = tracing.ExtractTraceContext(ctx, msg.Headers)

	// Start root span for this envelope hop
	ctx, span := r.tracer.Start(ctx, "actor.process",
		trace.WithSpanKind(trace.SpanKindConsumer),
		trace.WithAttributes(
			attribute.String("asya.actor", r.actorName),
			attribute.String("asya.envelope_id", msg.ID),
			attribute.String("asya.queue", r.cfg.ActorName),
		),
	)
	defer span.End()

	// Add flow attribute if available from headers
	if flow, ok := msg.Headers["x-asya-flow"]; ok {
		span.SetAttributes(attribute.String("asya.flow", fmt.Sprintf("%v", flow)))
	}

	// ... rest of ProcessMessage (all subsequent operations inherit ctx) ...
}
```

Add imports:
```go
"go.opentelemetry.io/otel/attribute"
"go.opentelemetry.io/otel/trace"
"github.com/deliveryhero/asya/asya-sidecar/internal/tracing"
```

- [ ] **Step 3: Instrument routeResponse with producer span**

In `routeResponse()` (~line 987), wrap the queue send:

```go
func (r *Router) routeResponse(ctx context.Context, /* params */) error {
	// ... existing queue name resolution ...

	// Inject trace context into outgoing envelope headers
	if headers == nil {
		headers = make(map[string]interface{})
	}

	// Start producer span
	ctx, sendSpan := r.tracer.Start(ctx, "actor.queue.send",
		trace.WithSpanKind(trace.SpanKindProducer),
		trace.WithAttributes(
			attribute.String("asya.destination_queue", destQueue),
			attribute.String("asya.message_type", messageType),
		),
	)

	// Inject updated trace context AFTER creating producer span
	tracing.InjectTraceContext(ctx, headers)

	// ... existing transport.Send() call ...
	err := r.transport.Send(ctx, destQueue, envelopeBytes)
	if err != nil {
		sendSpan.RecordError(err)
		sendSpan.SetStatus(codes.Error, err.Error())
	}
	sendSpan.End()

	return err
}
```

Add import: `"go.opentelemetry.io/otel/codes"`

- [ ] **Step 4: Ensure trace context survives handler header override**

In `handleSuccessResponse()` (~line 613), after merging headers from runtime response, re-inject trace context. The existing code uses `response.Headers` which may overwrite `traceparent`. After building `outHeaders`, the `routeResponse` call will inject fresh trace context, so this is handled by Step 3's injection in `routeResponse`. No additional code needed here — the sidecar always injects `traceparent` at send time.

Verify by reading the code flow: `handleSuccessResponse()` → `routeResponse()` → `InjectTraceContext()`.

- [ ] **Step 5: Instrument resiliency spans**

Note: `applyPolicy()` does NOT contain a retry loop. It checks if attempts are
exhausted and either calls `retryMessage()` (which re-enqueues the message for
the next dequeue) or routes to `onExhausted`/failure. The retry happens on the
_next_ dequeue, where `ProcessMessage` runs again with an incremented attempt count.

In `applyPolicy()` (~line 351), add a span around the resiliency decision:

```go
func (r *Router) applyPolicy(ctx context.Context, msg *envelopes.Envelope, policy *config.PolicyConfig, response runtime.RuntimeResponse) error {
	_, policySpan := r.tracer.Start(ctx, "actor.resiliency.policy",
		trace.WithAttributes(
			attribute.Int("asya.retry.attempt", msg.Status.Attempt),
			attribute.String("asya.retry.policy", policy.Name),
			attribute.Int("asya.retry.max_attempts", policy.MaxAttempts),
		),
	)
	defer policySpan.End()

	if msg.Status.Attempt >= policy.MaxAttempts {
		policySpan.SetAttributes(attribute.String("asya.retry.outcome", "exhausted"))
		// ... existing exhausted handling ...
	} else {
		policySpan.SetAttributes(attribute.String("asya.retry.outcome", "retry"))
		// ... existing retryMessage call (re-enqueues for next attempt) ...
	}
}
```

The `actor.process` root span in `ProcessMessage` already carries `msg.Status.Attempt`
as an attribute, so multiple retries show as separate traces with incrementing attempt
numbers, all sharing the same trace ID (because `traceparent` is preserved in headers
across re-enqueues).

- [ ] **Step 6: Add ForceFlush before os.Exit calls**

The sidecar calls `os.Exit(1)` in helper methods (`processEndActorEnvelope`,
`handleRuntimeCallError`) that are NOT inside `ProcessMessage` directly. The
deferred `span.End()` and `tracingShutdown()` in main.go won't run on `os.Exit`.

Solution: use the global TracerProvider (no span reference needed). Create a
helper in `tracing/tracing.go`:

```go
// ForceFlush flushes all pending spans. Call before os.Exit().
func ForceFlush(ctx context.Context) {
	if tp, ok := otel.GetTracerProvider().(*sdktrace.TracerProvider); ok {
		tp.ForceFlush(ctx)
	}
}
```

Then at each `os.Exit(1)` call site in router.go, add before the exit:

```go
tracing.ForceFlush(context.Background())
os.Exit(1)
```

- [ ] **Step 7: Add span-verification unit tests with in-memory exporter**

Add to `tracing_test.go` or create `src/asya-sidecar/internal/router/router_tracing_test.go`:

```go
import (
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
)

func setupTestTracer(t *testing.T) *tracetest.InMemoryExporter {
	t.Helper()
	exporter := tracetest.NewInMemoryExporter()
	tp := sdktrace.NewTracerProvider(sdktrace.WithSyncer(exporter))
	otel.SetTracerProvider(tp)
	t.Cleanup(func() {
		tp.Shutdown(context.Background())
		otel.SetTracerProvider(noop.NewTracerProvider())
	})
	return exporter
}

func TestProcessMessage_CreatesExpectedSpans(t *testing.T) {
	exporter := setupTestTracer(t)

	// ... set up router with mock transport and runtime ...
	// ... call ProcessMessage with an envelope containing traceparent ...

	spans := exporter.GetSpans()
	// Verify span names and parent-child relationships
	var processSpan, sendSpan tracetest.SpanStub
	for _, s := range spans {
		switch s.Name {
		case "actor.process":
			processSpan = s
		case "actor.queue.send":
			sendSpan = s
		}
	}
	if processSpan.Name == "" {
		t.Fatal("missing actor.process span")
	}
	if sendSpan.Name == "" {
		t.Fatal("missing actor.queue.send span")
	}
	// Verify send span is child of process span
	if sendSpan.Parent.SpanID() != processSpan.SpanContext.SpanID() {
		t.Error("actor.queue.send should be child of actor.process")
	}
}
```

Adapt this pattern for fan-out tests (verify multiple send spans with same trace ID).

- [ ] **Step 8: Run sidecar unit tests**

```bash
cd src/asya-sidecar && go test ./... -count=1
```

Expected: all pass. Some tests may need context parameters updated.

- [ ] **Step 9: Commit**

```bash
git add src/asya-sidecar/internal/router/ src/asya-sidecar/internal/tracing/
git commit -m "feat(sidecar): span instrumentation for process, send, retry, timeout [kvx0]"
```

---

## Task 4: Sidecar Runtime Call Span

**Files:**
- Modify: `src/asya-sidecar/internal/runtime/client.go`

- [ ] **Step 1: Add span around CallRuntime**

In `CallRuntime()` (~line 102), wrap the HTTP call:

```go
import (
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/trace"
)

func (c *Client) CallRuntime(ctx context.Context, data []byte, timeout time.Duration,
	onUpstream func(json.RawMessage), onDownstream func(RuntimeResponse, int)) error {

	tracer := otel.Tracer("asya-sidecar")
	ctx, span := tracer.Start(ctx, "actor.runtime.call",
		trace.WithAttributes(
			semconv.HTTPRequestMethodKey.String("POST"),
			attribute.String("url.path", "/invoke"),
		),
	)
	defer span.End()

	// ... existing timeout context setup ...
	// ... existing HTTP POST ...

	resp, err := c.httpClient.Do(req.WithContext(timeoutCtx))
	if err != nil {
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
		return err
	}

	span.SetAttributes(semconv.HTTPResponseStatusCodeKey.Int(resp.StatusCode))

	// ... existing response handling ...
}
```

- [ ] **Step 2: Run tests**

```bash
cd src/asya-sidecar && go test ./internal/runtime/ -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/asya-sidecar/internal/runtime/client.go
git commit -m "feat(sidecar): span around runtime HTTP call [kvx0]"
```

---

## Task 5: Gateway OTEL SDK Init

**Files:**
- Create: `src/asya-gateway/internal/tracing/tracing.go`
- Create: `src/asya-gateway/internal/tracing/tracing_test.go`
- Modify: `src/asya-gateway/cmd/gateway/main.go`
- Modify: `src/asya-gateway/go.mod`

- [ ] **Step 1: Add OTEL SDK dependencies to gateway go.mod**

```bash
cd src/asya-gateway
go get go.opentelemetry.io/otel/sdk@latest
go get go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc@latest
go get go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp@latest
go mod tidy
```

- [ ] **Step 2: Create gateway tracing package**

Create `src/asya-gateway/internal/tracing/tracing.go` — same pattern as sidecar:

```go
package tracing

import (
	"context"
	"fmt"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
	"go.opentelemetry.io/otel/trace/noop"
)

func Init(endpoint, serviceName, namespace string) (func(context.Context) error, error) {
	if endpoint == "" {
		tp := noop.NewTracerProvider()
		otel.SetTracerProvider(tp)
		return func(ctx context.Context) error { return nil }, nil
	}

	ctx := context.Background()

	exporter, err := otlptracegrpc.New(ctx,
		otlptracegrpc.WithEndpoint(endpoint),
		otlptracegrpc.WithInsecure(),
	)
	if err != nil {
		return nil, fmt.Errorf("create OTLP exporter: %w", err)
	}

	res, err := resource.New(ctx,
		resource.WithAttributes(
			semconv.ServiceNameKey.String(serviceName),
			semconv.ServiceNamespaceKey.String(namespace),
		),
	)
	if err != nil {
		return nil, fmt.Errorf("create resource: %w", err)
	}

	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter),
		sdktrace.WithResource(res),
	)

	otel.SetTracerProvider(tp)
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	))

	return tp.Shutdown, nil
}
```

- [ ] **Step 3: Write tests**

Create `src/asya-gateway/internal/tracing/tracing_test.go` — same two tests as sidecar (no-op and recording).

- [ ] **Step 4: Wire into gateway main.go**

In `main.go`, after logging setup (~line 48) and before envelope store init (~line 56), add:

```go
	// Tracing (OTEL)
	otelEndpoint := os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
	gatewayMode := os.Getenv("ASYA_GATEWAY_MODE")
	serviceName := "asya-gateway-" + gatewayMode
	namespace := os.Getenv("ASYA_NAMESPACE")
	tracingShutdown, err := tracing.Init(otelEndpoint, serviceName, namespace)
	if err != nil {
		slog.Error("Failed to initialize tracing", "error", err)
		os.Exit(1)
	}
	defer tracingShutdown(context.Background())
```

- [ ] **Step 5: Add otelhttp middleware at server level**

Wrap the entire mux at the HTTP server creation point (~line 238 in main.go),
not per-handler. This avoids conflicts with existing auth middleware chain:

```go
import "go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"

// When creating the HTTP server, wrap the mux:
handler := otelhttp.NewHandler(mux, "asya-gateway")
srv := &http.Server{
	Addr:    ":" + port,
	Handler: handler,
}
```

This gives every HTTP route automatic request/response spans with no
per-handler wrapping needed.

- [ ] **Step 6: Run gateway tests**

```bash
cd src/asya-gateway && go test ./... -count=1
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/asya-gateway/internal/tracing/ src/asya-gateway/cmd/gateway/main.go src/asya-gateway/go.mod src/asya-gateway/go.sum
git commit -m "feat(gateway): add OTEL tracing init and otelhttp middleware [kvx0]"
```

---

## Task 6: Gateway Root Span + Traceparent Injection

**Files:**
- Modify: `src/asya-gateway/internal/a2a/executor.go:41-118`
- Modify: `src/asya-gateway/internal/a2a/translator.go:77-82`

- [ ] **Step 1: Add root span in Executor.Execute()**

In `executor.go` `Execute()` method (~line 41), wrap task execution:

```go
import (
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/trace"
)

func (e *Executor) Execute(ctx context.Context, reqCtx *a2asrv.RequestContext, eq eventqueue.Queue) (*a2asrv.RequestContext, error) {
	tracer := otel.Tracer("asya-gateway")

	msg := reqCtx.Message
	taskID := reqCtx.TaskID
	contextID := reqCtx.ContextID

	ctx, span := tracer.Start(ctx, "gateway.task.execute",
		trace.WithSpanKind(trace.SpanKindServer),
		trace.WithAttributes(
			attribute.String("asya.task_id", string(taskID)),
			attribute.String("asya.context_id", contextID),
		),
	)
	defer span.End()

	// ... existing resume check ...
	// ... existing skill resolution ...

	skill := resolvedSkill
	span.SetAttributes(attribute.String("asya.actor", skill.Actor))
	if skill.Flow != "" {
		span.SetAttributes(attribute.String("asya.flow", skill.Flow))
	}

	// Pass ctx to translator so traceparent is injected
	payload, headers := MessageToPayload(ctx, msg, taskID, contextID)

	// ... existing envelope creation, store, dispatch ...
}
```

- [ ] **Step 2: Inject traceparent in BuildA2AHeaders**

Modify `translator.go` `BuildA2AHeaders()` (~line 77) to accept context and inject trace context:

```go
import (
	"go.opentelemetry.io/otel"
)

func BuildA2AHeaders(ctx context.Context, taskID a2asrv.TaskID, contextID string) map[string]interface{} {
	headers := map[string]interface{}{
		"x-asya-a2a-task-id":    taskID,
		"x-asya-a2a-context-id": contextID,
	}
	// Inject W3C trace context from current span
	otel.GetTextMapPropagator().Inject(ctx, headerCarrier(headers))
	return headers
}
```

Add the `headerCarrier` adapter (same as sidecar propagation.go):

```go
type headerCarrier map[string]interface{}

func (c headerCarrier) Get(key string) string {
	v, ok := c[key]
	if !ok {
		return ""
	}
	return fmt.Sprintf("%v", v)
}

func (c headerCarrier) Set(key, value string) {
	c[key] = value
}

func (c headerCarrier) Keys() []string {
	keys := make([]string, 0, len(c))
	for k := range c {
		keys = append(keys, k)
	}
	return keys
}
```

Update `MessageToPayload()` signature to accept `ctx context.Context` and pass it to `BuildA2AHeaders(ctx, ...)`.

- [ ] **Step 3: Add queue send span**

In `Execute()`, wrap the `queueClient.SendMessage()` call:

```go
	ctx, sendSpan := tracer.Start(ctx, "gateway.queue.send",
		trace.WithSpanKind(trace.SpanKindProducer),
		trace.WithAttributes(
			attribute.String("asya.destination_queue", skill.Actor),
		),
	)
	err = e.queueClient.SendMessage(ctx, envelope)
	if err != nil {
		sendSpan.RecordError(err)
		sendSpan.SetStatus(codes.Error, err.Error())
	}
	sendSpan.End()
```

- [ ] **Step 4: Update all callers of MessageToPayload/BuildA2AHeaders**

Search for all call sites and add `ctx` parameter. Check `handleResume()` as well.

```bash
cd src/asya-gateway && grep -rn "MessageToPayload\|BuildA2AHeaders" --include="*.go"
```

Update each call site.

- [ ] **Step 5: Run gateway tests**

```bash
cd src/asya-gateway && go test ./... -count=1
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/asya-gateway/internal/a2a/
git commit -m "feat(gateway): root span and traceparent injection in executor [kvx0]"
```

---

## Task 7: Helm Chart — XRD and Composition Changes

**Files:**
- Modify: `deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml:~309`
- Modify: `deploy/helm-charts/asya-crossplane/templates/composition-sqs.yaml:~559`
- Modify: `deploy/helm-charts/asya-crossplane/templates/composition-rabbitmq.yaml`
- Modify: `deploy/helm-charts/asya-crossplane/templates/composition-pubsub.yaml`

- [ ] **Step 1: Add `spec.tracing` field to XRD**

In `xrd-asyncactor.yaml`, after the `sidecar` property block (~line 309), add:

```yaml
                tracing:
                  type: object
                  description: "Distributed tracing configuration"
                  properties:
                    endpoint:
                      type: string
                      description: "OTLP gRPC endpoint (e.g. http://tempo:4317)"
```

- [ ] **Step 2: Inject OTEL env var in composition-sqs.yaml**

In the sidecar env vars block (~line 559, after actor-specific env injection), add:

```yaml
                          {{`{{- if $xrSpec.tracing }}`}}
                          {{`{{- if $xrSpec.tracing.endpoint }}`}}
                          - name: OTEL_EXPORTER_OTLP_ENDPOINT
                            value: {{`"{{ $xrSpec.tracing.endpoint }}"`}}
                          {{`{{- end }}`}}
                          {{`{{- end }}`}}
```

- [ ] **Step 3: Apply same change to composition-rabbitmq.yaml and composition-pubsub.yaml**

Find the equivalent sidecar env var injection point in each file and add the same block.

- [ ] **Step 4: Run Helm template tests**

```bash
cd deploy/helm-charts/asya-crossplane && helm template . --set sidecar.image=test:latest | grep -A2 OTEL_EXPORTER
```

Verify the env var appears only when `tracing.endpoint` is set.

- [ ] **Step 5: Commit**

```bash
git add deploy/helm-charts/asya-crossplane/
git commit -m "feat(crossplane-chart): add spec.tracing.endpoint XRD field and OTEL env injection [kvx0]"
```

---

## Task 8: Helm Chart — Gateway and Crew

**Files:**
- Modify: `deploy/helm-charts/asya-gateway/values.yaml`
- Modify: `deploy/helm-charts/asya-gateway/templates/deployment-api.yaml:~113`
- Modify: `deploy/helm-charts/asya-gateway/templates/deployment-mesh.yaml:~105`
- Modify: `deploy/helm-charts/asya-crew/values.yaml`

- [ ] **Step 1: Add tracing section to gateway values.yaml**

After the last config entry (~line 163), add:

```yaml
tracing:
  endpoint: ""
```

- [ ] **Step 2: Inject env var in deployment-api.yaml**

After `ASYA_CONFIG_PATH` env var (~line 113), before `{{- with .Values.env }}`:

```yaml
        {{- if .Values.tracing.endpoint }}
        - name: OTEL_EXPORTER_OTLP_ENDPOINT
          value: {{ .Values.tracing.endpoint | quote }}
        {{- end }}
```

- [ ] **Step 3: Same injection in deployment-mesh.yaml**

After `ASYA_NAMESPACE` env var (~line 105), before `{{- with .Values.env }}`:

```yaml
        {{- if .Values.tracing.endpoint }}
        - name: OTEL_EXPORTER_OTLP_ENDPOINT
          value: {{ .Values.tracing.endpoint | quote }}
        {{- end }}
```

- [ ] **Step 4: Add tracing.endpoint to crew values.yaml**

Add a `tracing` section at the top level of crew `values.yaml`:

```yaml
tracing:
  endpoint: ""
```

- [ ] **Step 5: Inject spec.tracing.endpoint into crew actor templates**

For each crew actor template (`sink.yaml`, `sump.yaml`, `pause.yaml`, `resume.yaml`),
add `spec.tracing.endpoint` to the AsyncActor CR. Example for `sink.yaml`:

```yaml
spec:
  # ... existing fields ...
  {{- if .Values.tracing.endpoint }}
  tracing:
    endpoint: {{ .Values.tracing.endpoint | quote }}
  {{- end }}
  {{- with $sink.sidecar }}
  sidecar:
    {{- toYaml . | nindent 4 }}
  {{- end }}
```

Apply the same pattern to all 4 crew actor templates. This completes the chain:
crew `values.yaml` -> crew templates -> AsyncActor CR `spec.tracing.endpoint` ->
XRD validates -> Crossplane composition injects `OTEL_EXPORTER_OTLP_ENDPOINT`.

- [ ] **Step 6: Run Helm template validation**

```bash
cd deploy/helm-charts/asya-gateway && helm template . --set tracing.endpoint=http://tempo:4317 | grep OTEL
```

Expected: `OTEL_EXPORTER_OTLP_ENDPOINT` appears in both api and mesh deployments.

- [ ] **Step 6: Commit**

```bash
git add deploy/helm-charts/asya-gateway/ deploy/helm-charts/asya-crew/values.yaml
git commit -m "feat(gateway-chart,crew-chart): add tracing.endpoint config [kvx0]"
```

---

## Task 9: Playground Chart — Tempo Subchart + Grafana Datasource

**Files:**
- Modify: `deploy/helm-charts/asya-playground/Chart.yaml`
- Modify: `deploy/helm-charts/asya-playground/values.yaml`

- [ ] **Step 1: Add Tempo dependency to Chart.yaml**

Add to dependencies section:

```yaml
  - name: tempo
    version: "~1.x"
    repository: https://grafana.github.io/helm-charts
    condition: sampleTracing.enabled
```

- [ ] **Step 2: Run helm dependency update**

```bash
cd deploy/helm-charts/asya-playground && helm dependency update
```

- [ ] **Step 3: Add sampleTracing config to values.yaml**

After `sampleMonitoring` section (~line 171), add:

```yaml
sampleTracing:
  enabled: false
```

Add Tempo values section:

```yaml
tempo:
  tempo:
    storage:
      trace:
        backend: local
    retention: 24h
    metricsGenerator:
      enabled: true
      remoteWriteUrl: "http://asya-monitoring-kube-pr-prometheus:9090/api/v1/write"
    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: "0.0.0.0:4317"
          http:
            endpoint: "0.0.0.0:4318"
```

**Note:** The `remoteWriteUrl` must match the actual Prometheus service name. Verify with:
```bash
helm template asya-monitoring deploy/helm-charts/asya-playground/ --set sampleMonitoring.enabled=true | grep "name:.*prometheus" | head -5
```

- [ ] **Step 4: Add Grafana Tempo datasource**

In the kube-prometheus-stack Grafana section, add:

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
          nodeGraph:
            enabled: true
```

- [ ] **Step 5: Auto-wire gateway tracing endpoint when sampleTracing is enabled**

In the `asya-gateway` subchart values section of playground `values.yaml`, add
conditional tracing endpoint that points to the Tempo service:

```yaml
asya-gateway:
  tracing:
    endpoint: ""  # overridden when sampleTracing.enabled=true
```

Also add conditional wiring. If the playground chart supports value overrides via
templates, create a helper template. Otherwise, document that users must set
`asya-gateway.tracing.endpoint: "tempo:4317"` alongside `sampleTracing.enabled: true`.

Similarly, wire crew chart tracing:

```yaml
asya-crew:
  tracing:
    endpoint: ""  # set to "tempo:4317" when sampleTracing.enabled=true
```

- [ ] **Step 6: Verify Helm template renders**

```bash
cd deploy/helm-charts/asya-playground && helm template . --set sampleTracing.enabled=true --set sampleMonitoring.enabled=true | grep -A5 "tempo"
```

Also verify gateway gets the OTEL endpoint:
```bash
helm template . --set sampleTracing.enabled=true --set asya-gateway.tracing.endpoint=tempo:4317 | grep OTEL_EXPORTER
```

- [ ] **Step 7: Commit**

```bash
git add deploy/helm-charts/asya-playground/
git commit -m "feat(playground-chart): add Tempo subchart with Grafana datasource [kvx0]"
```

---

## Task 10: Component Test — Multi-Hop Trace Verification

**Files:**
- Create: `testing/component/tracing/docker-compose.yaml`
- Create: `testing/component/tracing/tests/test_tracing.py`
- Create: `testing/component/tracing/tests/conftest.py`

- [ ] **Step 1: Create Docker Compose for tracing test**

Create `testing/component/tracing/docker-compose.yaml` with:
- Tempo (single binary, OTLP receiver on 4317)
- 2 sidecar instances (actor-a, actor-b) with `OTEL_EXPORTER_OTLP_ENDPOINT=tempo:4317`
- 2 runtime instances with simple pass-through handlers
- RabbitMQ for transport

- [ ] **Step 2: Write test that sends envelope and queries Tempo**

Create `testing/component/tracing/tests/test_tracing.py`:

```python
import json
import time
import requests
import pytest

def _poll_tempo_for_traces(tempo_url, service_name, timeout=30, interval=2):
    """Poll Tempo API until traces appear for the given service."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(
            f"{tempo_url}/api/search",
            params={"q": f'{{resource.service.name="{service_name}"}}', "limit": 10},
        )
        if resp.status_code == 200:
            traces = resp.json().get("traces", [])
            if traces:
                return traces
        time.sleep(interval)  # polling for Tempo indexing
    return []

def test_trace_propagation_across_actors(rabbitmq_connection, tempo_url):
    """Send envelope through actor-a -> actor-b, verify connected trace in Tempo."""
    envelope = {
        "id": "test-trace-001",
        "route": {"prev": [], "curr": "actor-a", "next": ["actor-b"]},
        "headers": {},
        "payload": {"data": "test"},
    }

    # Publish to actor-a queue
    publish_to_queue(rabbitmq_connection, "asya-actor-a", json.dumps(envelope))

    # Poll Tempo until traces are indexed
    traces = _poll_tempo_for_traces(tempo_url, "actor-a", timeout=30)
    assert len(traces) > 0, "No traces found for actor-a after 30s"

    # Fetch full trace via Tempo HTTP API (OTLP JSON format)
    trace_id = traces[0]["traceID"]
    trace_resp = requests.get(f"{tempo_url}/api/traces/{trace_id}")
    assert trace_resp.status_code == 200

    # Tempo returns OTLP format: { "resourceSpans": [...] }
    trace_data = trace_resp.json()
    services = set()
    for rs in trace_data.get("resourceSpans", []):
        for attr in rs.get("resource", {}).get("attributes", []):
            if attr.get("key") == "service.name":
                services.add(attr["value"]["stringValue"])

    # Both actors should appear in the same trace
    assert "actor-a" in services, f"actor-a not in trace, found: {services}"
    assert "actor-b" in services, f"actor-b not in trace, found: {services}"
```

- [ ] **Step 3: Add Makefile target**

Add to root Makefile:

```makefile
test-component-tracing:
	cd testing/component/tracing && docker compose up -d
	cd testing/component/tracing && pytest tests/ -v
	cd testing/component/tracing && docker compose down
```

- [ ] **Step 4: Run component test**

```bash
make test-component-tracing
```

Expected: PASS — traces span both actors.

- [ ] **Step 5: Commit**

```bash
git add testing/component/tracing/ Makefile
git commit -m "test(tracing): component test for multi-hop trace propagation [kvx0]"
```

---

## Task 11: Documentation Updates

**Files:**
- Modify: `docs/concepts/observability.md`
- Modify: `docs/setup/ops-observability.md`
- Modify: `docs/reference/specs/envelope.md`

- [ ] **Step 1: Update concepts/observability.md**

Rewrite the "Distributed tracing" section to reflect the actual implementation:

```markdown
## Distributed tracing

Every envelope carries W3C Trace Context headers (`traceparent`, `tracestate`).
The gateway generates the root trace when a task is created. Each sidecar
extracts the trace context, creates spans for envelope processing, and injects
updated context into outgoing envelopes.

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to enable tracing. Traces appear in any
OTLP-compatible backend: Tempo, Jaeger, Cloud Trace, Datadog, or Honeycomb.

Span structure per actor hop:
- `actor.process` — full envelope processing (SpanKindConsumer)
- `actor.runtime.call` — handler execution via Unix socket
- `actor.resiliency.retry` — retry attempts (when applicable)
- `actor.queue.send` — outbound dispatch (SpanKindProducer)
```

- [ ] **Step 2: Update setup/ops-observability.md**

Remove the "Future" section at the end. Add a new "Distributed Tracing" section before "Logging":

```markdown
## Distributed Tracing

### Configuration

Set `OTEL_EXPORTER_OTLP_ENDPOINT` on sidecar and gateway to enable tracing:

- **Sidecar**: Set via `spec.tracing.endpoint` in AsyncActor CR
- **Gateway**: Set via `tracing.endpoint` in gateway Helm values

### Playground Setup

Enable `sampleTracing.enabled: true` in the playground chart to deploy Grafana
Tempo. The Tempo datasource is auto-provisioned in Grafana.

### Querying Traces

In Grafana Explore, select the Tempo datasource and use TraceQL:

\`\`\`
{resource.service.name="my-actor"}
{span.asya.flow="text-improver" && status=error}
\`\`\`
```

- [ ] **Step 3: Update reference/specs/envelope.md**

Add `traceparent` and `tracestate` to the headers documentation:

```markdown
### Sidecar-Managed Headers

These headers are automatically managed by the sidecar and should not be
modified by user handlers:

| Header | Description |
|---|---|
| `traceparent` | W3C Trace Context parent (auto-injected when tracing enabled) |
| `tracestate` | W3C Trace Context state (auto-injected when tracing enabled) |
```

- [ ] **Step 4: Commit**

```bash
git add docs/
git commit -m "docs: update observability docs for distributed tracing [kvx0]"
```

---

## Task 12: Final Integration + Lint + Push

- [ ] **Step 1: Run all linters**

```bash
make lint
```

Fix any issues.

- [ ] **Step 2: Run full unit test suite**

```bash
make test-unit
```

Expected: all pass.

- [ ] **Step 3: Build all images**

```bash
make build
```

Expected: successful build.

- [ ] **Step 4: Push**

```bash
git pull --rebase origin main
git push -u origin observability-initial/kvx0.implement-distributed-tracing-otel-instrumentation-jaeger-tempo-grafana
```

- [ ] **Step 5: Update aint status**

```bash
git aint update kvx0 --status pushed
```
