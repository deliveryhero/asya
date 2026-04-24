package tracing

import (
	"context"
	"testing"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/trace"
	"go.opentelemetry.io/otel/trace/noop"
)

func TestInit_NoEndpoint(t *testing.T) {
	// Backup and restore global tracer provider
	oldProvider := otel.GetTracerProvider()
	t.Cleanup(func() {
		otel.SetTracerProvider(oldProvider)
	})

	shutdown, err := Init("", "test-service", "test-ns")
	if err != nil {
		t.Fatalf("Init with empty endpoint should not error: %v", err)
	}

	// Shutdown should be no-op
	if err := shutdown(context.Background()); err != nil {
		t.Fatalf("Shutdown should not error: %v", err)
	}

	// Verify no-op tracer provider
	tp := otel.GetTracerProvider()
	if _, ok := tp.(noop.TracerProvider); !ok {
		t.Errorf("Expected noop.TracerProvider when endpoint is empty, got %T", tp)
	}

	// Create a span and verify it's non-recording
	tracer := tp.Tracer("test")
	ctx, span := tracer.Start(context.Background(), "test-span")
	defer span.End()

	if span.IsRecording() {
		t.Error("Span should not be recording when endpoint is empty")
	}

	// Verify span context is invalid
	spanCtx := trace.SpanContextFromContext(ctx)
	if spanCtx.IsValid() {
		t.Error("SpanContext should be invalid for no-op provider")
	}
}

func TestInit_WithEndpoint(t *testing.T) {
	// This test only verifies that Init doesn't crash with a valid endpoint.
	// Actual OTLP export is tested in integration tests.

	// Backup and restore global tracer provider
	oldProvider := otel.GetTracerProvider()
	t.Cleanup(func() {
		otel.SetTracerProvider(oldProvider)
	})

	// Use a fake endpoint (won't actually connect)
	shutdown, err := Init("localhost:4317", "test-service", "test-ns")
	if err != nil {
		t.Fatalf("Init with endpoint should not error: %v", err)
	}
	defer shutdown(context.Background())

	// Verify we got a real tracer provider (not no-op)
	tp := otel.GetTracerProvider()
	if _, ok := tp.(noop.TracerProvider); ok {
		t.Error("Expected real TracerProvider when endpoint is provided, got noop")
	}

	// Create a span and verify it's recording
	tracer := tp.Tracer("test")
	ctx, span := tracer.Start(context.Background(), "test-span")
	defer span.End()

	if !span.IsRecording() {
		t.Error("Span should be recording when endpoint is provided")
	}

	// Verify span context is valid
	spanCtx := trace.SpanContextFromContext(ctx)
	if !spanCtx.IsValid() {
		t.Error("SpanContext should be valid for real provider")
	}
}

func TestInit_HTTPProtocol(t *testing.T) {
	oldProvider := otel.GetTracerProvider()
	t.Cleanup(func() { otel.SetTracerProvider(oldProvider) })
	t.Setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http")

	// HTTP endpoint uses full URL format (host:port without scheme is also accepted
	// by otlptracehttp.WithEndpoint — it will not actually connect in unit tests)
	shutdown, err := Init("localhost:4318", "test-service", "test-ns")
	if err != nil {
		t.Fatalf("Init with HTTP protocol should not error: %v", err)
	}
	defer shutdown(context.Background())

	tp := otel.GetTracerProvider()
	if _, ok := tp.(noop.TracerProvider); ok {
		t.Error("Expected real TracerProvider when endpoint is provided, got noop")
	}

	tracer := tp.Tracer("test")
	ctx, span := tracer.Start(context.Background(), "test-span")
	defer span.End()

	if !span.IsRecording() {
		t.Error("Span should be recording with HTTP protocol")
	}

	spanCtx := trace.SpanContextFromContext(ctx)
	if !spanCtx.IsValid() {
		t.Error("SpanContext should be valid for real provider")
	}
}
