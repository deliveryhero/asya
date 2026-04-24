package tracing

import (
	"context"
	"fmt"
	"log/slog"
	"os"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace/noop"
)

// Init initializes the global OpenTelemetry tracer provider.
// If endpoint is empty, a no-op tracer provider is set (tracing disabled).
// Otherwise, creates an OTLP exporter using the protocol selected by
// OTEL_EXPORTER_OTLP_PROTOCOL ("http" → HTTP/protobuf, anything else → gRPC).
// gRPC expects bare host:port; HTTP expects a full URL (http://host:4318).
// Returns a shutdown function to flush and close the provider.
func Init(endpoint, serviceName, namespace string) (func(context.Context) error, error) {
	if endpoint == "" {
		slog.Info("OTEL tracing disabled (no endpoint configured)")
		otel.SetTracerProvider(noop.NewTracerProvider())
		return func(context.Context) error { return nil }, nil
	}

	protocol := os.Getenv("OTEL_EXPORTER_OTLP_PROTOCOL")
	slog.Info("Initializing OTEL tracing", "endpoint", endpoint, "protocol", protocol, "service", serviceName, "namespace", namespace)

	var (
		exporter sdktrace.SpanExporter
		err      error
	)
	if protocol == "http" {
		exporter, err = otlptracehttp.New(
			context.Background(),
			otlptracehttp.WithEndpoint(endpoint),
			otlptracehttp.WithInsecure(),
		)
	} else {
		exporter, err = otlptracegrpc.New(
			context.Background(),
			otlptracegrpc.WithEndpoint(endpoint),
			otlptracegrpc.WithInsecure(),
		)
	}
	if err != nil {
		return nil, fmt.Errorf("failed to create OTLP trace exporter: %w", err)
	}

	res, err := resource.New(
		context.Background(),
		resource.WithAttributes(
			attribute.String("service.name", serviceName),
			attribute.String("service.namespace", namespace),
		),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to create resource: %w", err)
	}

	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter),
		sdktrace.WithResource(res),
	)

	otel.SetTracerProvider(tp)
	otel.SetTextMapPropagator(propagation.TraceContext{})

	slog.Info("OTEL tracing initialized successfully")

	return tp.Shutdown, nil
}

// ForceFlush forces the tracer provider to flush all pending spans.
// This is useful before os.Exit to ensure spans are exported.
// If the global tracer provider is not a recording provider, this is a no-op.
func ForceFlush(ctx context.Context) {
	if tp, ok := otel.GetTracerProvider().(*sdktrace.TracerProvider); ok {
		if err := tp.ForceFlush(ctx); err != nil {
			slog.Warn("Failed to flush traces", "error", err)
		}
	}
}
