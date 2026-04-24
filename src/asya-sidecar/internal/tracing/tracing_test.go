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

func TestInit_HTTPProtocol(t *testing.T) {
	resetGlobalTracer(t)
	t.Setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http")

	// otlptracehttp.WithEndpoint accepts bare host:port and will not actually connect
	shutdown, err := Init("localhost:4318", "test-service", "test-namespace")
	if err != nil {
		t.Fatalf("Init with HTTP protocol should not error, got: %v", err)
	}
	if shutdown == nil {
		t.Fatal("Init should return non-nil shutdown function")
	}
	defer func() { _ = shutdown(context.Background()) }()

	tp := otel.GetTracerProvider()
	if _, ok := tp.(*sdktrace.TracerProvider); !ok {
		t.Errorf("Expected *sdktrace.TracerProvider with HTTP protocol, got %T", tp)
	}

	tracer := tp.Tracer("test")
	_, span := tracer.Start(context.Background(), "test-span")
	defer span.End()

	if !span.IsRecording() {
		t.Error("Expected recording span when HTTP endpoint is provided")
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

func TestExtractTraceContext_WithValidTraceparent(t *testing.T) {
	resetGlobalTracer(t)

	shutdown, err := Init("localhost:4317", "test-service", "test-namespace")
	if err != nil {
		t.Fatalf("Init should not error, got: %v", err)
	}
	defer func() {
		_ = shutdown(context.Background())
	}()

	// Create a span to generate a valid traceparent
	tracer := otel.GetTracerProvider().Tracer("test")
	ctx, span := tracer.Start(context.Background(), "parent-span")
	spanCtx := span.SpanContext()
	span.End()

	// Inject into headers
	headers := make(map[string]any)
	InjectTraceContext(ctx, headers)

	// Verify traceparent was injected
	if headers["traceparent"] == nil {
		t.Fatal("Expected traceparent to be injected")
	}

	// Extract from headers into a new context
	newCtx := ExtractTraceContext(context.Background(), headers)

	// Create a child span from the extracted context
	_, childSpan := tracer.Start(newCtx, "child-span")
	childSpanCtx := childSpan.SpanContext()
	childSpan.End()

	// Verify trace IDs match (same trace)
	if spanCtx.TraceID() != childSpanCtx.TraceID() {
		t.Errorf("Expected trace IDs to match: parent=%s, child=%s", spanCtx.TraceID(), childSpanCtx.TraceID())
	}

	// Verify span IDs differ (different spans)
	if spanCtx.SpanID() == childSpanCtx.SpanID() {
		t.Error("Expected span IDs to differ")
	}
}

func TestExtractTraceContext_WithNoTraceparent(t *testing.T) {
	resetGlobalTracer(t)

	shutdown, err := Init("localhost:4317", "test-service", "test-namespace")
	if err != nil {
		t.Fatalf("Init should not error, got: %v", err)
	}
	defer func() {
		_ = shutdown(context.Background())
	}()

	// Extract from empty headers
	headers := make(map[string]any)
	ctx := ExtractTraceContext(context.Background(), headers)

	// Create a span from the extracted context
	tracer := otel.GetTracerProvider().Tracer("test")
	_, span := tracer.Start(ctx, "new-span")
	spanCtx := span.SpanContext()
	span.End()

	// Should create a new trace (valid trace ID and span ID)
	if !spanCtx.TraceID().IsValid() {
		t.Error("Expected valid trace ID for new trace")
	}
	if !spanCtx.SpanID().IsValid() {
		t.Error("Expected valid span ID for new span")
	}
}

func TestInjectTraceContext_WritesTraceparent(t *testing.T) {
	resetGlobalTracer(t)

	shutdown, err := Init("localhost:4317", "test-service", "test-namespace")
	if err != nil {
		t.Fatalf("Init should not error, got: %v", err)
	}
	defer func() {
		_ = shutdown(context.Background())
	}()

	// Create a span to get a trace context
	tracer := otel.GetTracerProvider().Tracer("test")
	ctx, span := tracer.Start(context.Background(), "test-span")
	defer span.End()

	// Inject into headers
	headers := make(map[string]any)
	InjectTraceContext(ctx, headers)

	// Verify traceparent header exists
	traceparent, ok := headers["traceparent"]
	if !ok {
		t.Fatal("Expected traceparent header to be injected")
	}

	// Verify it's a string
	if _, ok := traceparent.(string); !ok {
		t.Errorf("Expected traceparent to be string, got %T", traceparent)
	}
}

func TestHeaderCarrier_NonStringValues(t *testing.T) {
	resetGlobalTracer(t)

	// Create headers with non-string values
	headers := map[string]any{
		"string_key": "string_value",
		"int_key":    42,
		"bool_key":   true,
		"nil_key":    nil,
	}

	carrier := &headerCarrier{headers: headers}

	// Get should return empty string for non-string values
	if got := carrier.Get("string_key"); got != "string_value" {
		t.Errorf("Expected 'string_value', got %q", got)
	}
	if got := carrier.Get("int_key"); got != "" {
		t.Errorf("Expected empty string for int, got %q", got)
	}
	if got := carrier.Get("bool_key"); got != "" {
		t.Errorf("Expected empty string for bool, got %q", got)
	}
	if got := carrier.Get("nil_key"); got != "" {
		t.Errorf("Expected empty string for nil, got %q", got)
	}
	if got := carrier.Get("missing_key"); got != "" {
		t.Errorf("Expected empty string for missing key, got %q", got)
	}
}

func TestHeaderCarrier_SetAndKeys(t *testing.T) {
	headers := make(map[string]any)
	carrier := &headerCarrier{headers: headers}

	// Set values
	carrier.Set("key1", "value1")
	carrier.Set("key2", "value2")

	// Verify Set worked
	if headers["key1"] != "value1" {
		t.Errorf("Expected key1='value1', got %v", headers["key1"])
	}
	if headers["key2"] != "value2" {
		t.Errorf("Expected key2='value2', got %v", headers["key2"])
	}

	// Verify Keys returns all keys
	keys := carrier.Keys()
	if len(keys) != 2 {
		t.Errorf("Expected 2 keys, got %d", len(keys))
	}

	keyMap := make(map[string]bool)
	for _, k := range keys {
		keyMap[k] = true
	}
	if !keyMap["key1"] || !keyMap["key2"] {
		t.Errorf("Expected keys to contain 'key1' and 'key2', got %v", keys)
	}
}
