package tracing

import (
	"context"
	"testing"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace/noop"
)

// resetGlobalTracer resets the global tracer provider to a no-op after test completion
func resetGlobalTracer(t *testing.T) {
	t.Cleanup(func() {
		otel.SetTracerProvider(noop.NewTracerProvider())
	})
}

func TestInit_NoOpWhenEndpointEmpty(t *testing.T) {
	resetGlobalTracer(t)

	shutdown, err := Init("", "test-service", "test-namespace")
	if err != nil {
		t.Fatalf("Init with empty endpoint should not error, got: %v", err)
	}
	if shutdown == nil {
		t.Fatal("Init should return non-nil shutdown function")
	}

	// Verify that the global tracer provider is a no-op
	tracer := otel.GetTracerProvider().Tracer("test")
	_, span := tracer.Start(context.Background(), "test-span")
	defer span.End()

	// No-op spans do not record anything
	if span.IsRecording() {
		t.Error("Expected no-op span, but span is recording")
	}

	// Shutdown should not fail
	if err := shutdown(context.Background()); err != nil {
		t.Errorf("Shutdown should not error for no-op provider, got: %v", err)
	}
}

func TestInit_RecordingWhenEndpointProvided(t *testing.T) {
	resetGlobalTracer(t)

	// Use a non-resolvable endpoint to avoid actual network calls in unit tests
	// The exporter will be created but won't actually connect
	shutdown, err := Init("localhost:4317", "test-service", "test-namespace")
	if err != nil {
		t.Fatalf("Init with endpoint should not error, got: %v", err)
	}
	if shutdown == nil {
		t.Fatal("Init should return non-nil shutdown function")
	}
	defer func() {
		_ = shutdown(context.Background())
	}()

	// Verify that the global tracer provider is recording
	tp := otel.GetTracerProvider()
	if _, ok := tp.(*sdktrace.TracerProvider); !ok {
		t.Errorf("Expected *sdktrace.TracerProvider, got %T", tp)
	}

	tracer := tp.Tracer("test")
	_, span := tracer.Start(context.Background(), "test-span")
	defer span.End()

	if !span.IsRecording() {
		t.Error("Expected recording span when endpoint is provided")
	}
}

func TestInit_ServiceNameAndNamespace(t *testing.T) {
	resetGlobalTracer(t)

	shutdown, err := Init("localhost:4317", "my-service", "my-namespace")
	if err != nil {
		t.Fatalf("Init should not error, got: %v", err)
	}
	defer func() {
		_ = shutdown(context.Background())
	}()

	// The test verifies that Init succeeds with service name and namespace
	// Resource attributes are not directly inspectable via public API without
	// reading spans, but we verify no error occurs
	if shutdown == nil {
		t.Fatal("Shutdown function should not be nil")
	}
}

func TestForceFlush_NoOp(t *testing.T) {
	resetGlobalTracer(t)

	// Set no-op provider
	otel.SetTracerProvider(noop.NewTracerProvider())

	// ForceFlush should not panic or error for no-op provider
	ForceFlush(context.Background())
}

func TestForceFlush_Recording(t *testing.T) {
	resetGlobalTracer(t)

	shutdown, err := Init("localhost:4317", "test-service", "test-namespace")
	if err != nil {
		t.Fatalf("Init should not error, got: %v", err)
	}
	defer func() {
		_ = shutdown(context.Background())
	}()

	// Create a span to ensure something is in the pipeline
	tracer := otel.GetTracerProvider().Tracer("test")
	_, span := tracer.Start(context.Background(), "test-span")
	span.End()

	// ForceFlush should not panic or error
	ForceFlush(context.Background())
}

func TestInit_PropagatorIsW3C(t *testing.T) {
	resetGlobalTracer(t)

	shutdown, err := Init("localhost:4317", "test-service", "test-namespace")
	if err != nil {
		t.Fatalf("Init should not error, got: %v", err)
	}
	defer func() {
		_ = shutdown(context.Background())
	}()

	// Verify that the propagator is set (W3C TraceContext)
	// We can't directly assert the type, but we can verify it extracts/injects
	carrier := make(map[string]string)
	ctx := context.Background()

	// Create a span to get a trace context
	tracer := otel.GetTracerProvider().Tracer("test")
	ctx, span := tracer.Start(ctx, "test-span")
	defer span.End()

	// Inject should populate the carrier
	otel.GetTextMapPropagator().Inject(ctx, &mapCarrier{carrier})

	if carrier["traceparent"] == "" {
		t.Error("Expected traceparent header to be injected")
	}
}

// mapCarrier is a simple TextMapCarrier for testing
type mapCarrier struct {
	data map[string]string
}

func (m *mapCarrier) Get(key string) string {
	return m.data[key]
}

func (m *mapCarrier) Set(key, value string) {
	m.data[key] = value
}

func (m *mapCarrier) Keys() []string {
	keys := make([]string, 0, len(m.data))
	for k := range m.data {
		keys = append(keys, k)
	}
	return keys
}

var _ propagation.TextMapCarrier = (*mapCarrier)(nil)
