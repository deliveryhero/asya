package a2a

import (
	"context"

	"go.opentelemetry.io/otel"
)

// headerCarrier adapts envelope headers (map[string]any) to OTEL TextMapCarrier.
// Envelope headers may contain non-string values, but traceparent/tracestate are always strings.
type headerCarrier struct {
	headers map[string]any
}

// Get retrieves the value for a given key from the headers.
// Returns empty string if the key doesn't exist or the value is not a string.
func (h *headerCarrier) Get(key string) string {
	val, ok := h.headers[key]
	if !ok {
		return ""
	}
	str, ok := val.(string)
	if !ok {
		return ""
	}
	return str
}

// Set stores a key-value pair in the headers.
func (h *headerCarrier) Set(key, value string) {
	h.headers[key] = value
}

// Keys returns all keys in the headers.
func (h *headerCarrier) Keys() []string {
	keys := make([]string, 0, len(h.headers))
	for k := range h.headers {
		keys = append(keys, k)
	}
	return keys
}

// InjectTraceContext injects the trace context from the given context into the provided
// envelope headers map. The headers map must not be nil.
func InjectTraceContext(ctx context.Context, headers map[string]any) {
	carrier := &headerCarrier{headers: headers}
	otel.GetTextMapPropagator().Inject(ctx, carrier)
}
