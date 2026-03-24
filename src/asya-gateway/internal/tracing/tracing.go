package tracing

import (
	"context"
	"fmt"
	"log/slog"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace/noop"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

// Init initializes the global OpenTelemetry tracer provider.
// If endpoint is empty, a no-op tracer provider is set (tracing disabled).
// Otherwise, creates an OTLP gRPC exporter, resource with service.name and service.namespace,
// and a BatchSpanProcessor. Returns a shutdown function to flush and close the provider.
func Init(endpoint, serviceName, namespace string) (func(context.Context) error, error) {
	if endpoint == "" {
		slog.Info("OTEL tracing disabled (no endpoint configured)")
		otel.SetTracerProvider(noop.NewTracerProvider())
		return func(context.Context) error { return nil }, nil
	}

	slog.Info("Initializing OTEL tracing", "endpoint", endpoint, "service", serviceName, "namespace", namespace)

	// Create OTLP gRPC exporter
	exporter, err := otlptracegrpc.New(
		context.Background(),
		otlptracegrpc.WithEndpoint(endpoint),
		otlptracegrpc.WithDialOption(grpc.WithTransportCredentials(insecure.NewCredentials())),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to create OTLP trace exporter: %w", err)
	}

	// Create resource with service.name and service.namespace
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

	// Create tracer provider with batch span processor
	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter),
		sdktrace.WithResource(res),
	)

	// Set as global tracer provider
	otel.SetTracerProvider(tp)

	// Set W3C TraceContext propagator
	otel.SetTextMapPropagator(propagation.TraceContext{})

	slog.Info("OTEL tracing initialized successfully")

	// Return shutdown function
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
