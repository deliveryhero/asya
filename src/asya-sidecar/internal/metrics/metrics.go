package metrics

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/deliveryhero/asya/asya-sidecar/internal/config"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// Metrics holds all standard actor metrics
type Metrics struct {
	// Standard metrics
	messagesReceived     *prometheus.CounterVec
	messagesProcessed    *prometheus.CounterVec
	messagesSent         *prometheus.CounterVec
	messagesFailed       *prometheus.CounterVec
	processingDuration   *prometheus.HistogramVec
	runtimeDuration      *prometheus.HistogramVec
	queueReceiveDuration *prometheus.HistogramVec
	queueSendDuration    *prometheus.HistogramVec
	messageSize          *prometheus.HistogramVec
	activeMessages       prometheus.Gauge
	runtimeErrors        *prometheus.CounterVec

	// Custom metrics (dynamically registered)
	customCounters   map[string]*prometheus.CounterVec
	customGauges     map[string]*prometheus.GaugeVec
	customHistograms map[string]*prometheus.HistogramVec

	registry *prometheus.Registry
}

// NewMetrics creates a new metrics collector
func NewMetrics(namespace string, customMetricsConfig []config.CustomMetricConfig) *Metrics {
	registry := prometheus.NewRegistry()

	m := &Metrics{
		registry:         registry,
		customCounters:   make(map[string]*prometheus.CounterVec),
		customGauges:     make(map[string]*prometheus.GaugeVec),
		customHistograms: make(map[string]*prometheus.HistogramVec),
	}

	// Standard metrics
	m.messagesReceived = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Namespace: namespace,
			Name:      "messages_received_total",
			Help:      "Total number of messages received from queue",
		},
		[]string{"queue", "transport"},
	)

	m.messagesProcessed = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Namespace: namespace,
			Name:      "messages_processed_total",
			Help:      "Total number of messages successfully processed",
		},
		[]string{"queue", "status"}, // status: success, error, empty_response
	)

	m.messagesSent = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Namespace: namespace,
			Name:      "messages_sent_total",
			Help:      "Total number of messages sent to queues",
		},
		[]string{"destination_queue", "message_type"}, // message_type: routing, happy_end, error_end
	)

	m.messagesFailed = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Namespace: namespace,
			Name:      "messages_failed_total",
			Help:      "Total number of failed messages",
		},
		[]string{"queue", "reason"}, // reason: parse_error, runtime_error, transport_error
	)

	m.processingDuration = prometheus.NewHistogramVec(
		prometheus.HistogramOpts{
			Namespace: namespace,
			Name:      "processing_duration_seconds",
			Help:      "Total time to process a message (queue receive to queue send)",
			Buckets:   []float64{.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10, 30, 60, 120},
		},
		[]string{"queue"},
	)

	m.runtimeDuration = prometheus.NewHistogramVec(
		prometheus.HistogramOpts{
			Namespace: namespace,
			Name:      "runtime_execution_duration_seconds",
			Help:      "Time spent executing payload in runtime",
			Buckets:   []float64{.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10, 30, 60, 120},
		},
		[]string{"queue"},
	)

	m.queueReceiveDuration = prometheus.NewHistogramVec(
		prometheus.HistogramOpts{
			Namespace: namespace,
			Name:      "queue_receive_duration_seconds",
			Help:      "Time spent receiving message from queue",
			Buckets:   []float64{.001, .005, .01, .025, .05, .1, .25, .5, 1, 2, 5, 10},
		},
		[]string{"queue", "transport"},
	)

	m.queueSendDuration = prometheus.NewHistogramVec(
		prometheus.HistogramOpts{
			Namespace: namespace,
			Name:      "queue_send_duration_seconds",
			Help:      "Time spent sending message to queue",
			Buckets:   []float64{.001, .005, .01, .025, .05, .1, .25, .5, 1, 2, 5},
		},
		[]string{"destination_queue", "transport"},
	)

	m.messageSize = prometheus.NewHistogramVec(
		prometheus.HistogramOpts{
			Namespace: namespace,
			Name:      "envelope_size_bytes",
			Help:      "Size of envelopes in bytes",
			Buckets:   prometheus.ExponentialBuckets(100, 10, 8), // 100B to ~10MB
		},
		[]string{"direction"}, // direction: received, sent
	)

	m.activeMessages = prometheus.NewGauge(
		prometheus.GaugeOpts{
			Namespace: namespace,
			Name:      "active_messages",
			Help:      "Number of messages currently being processed",
		},
	)

	m.runtimeErrors = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Namespace: namespace,
			Name:      "runtime_errors_total",
			Help:      "Total number of runtime errors",
		},
		[]string{"queue", "error_type"},
	)

	// Register standard metrics
	registry.MustRegister(
		m.messagesReceived,
		m.messagesProcessed,
		m.messagesSent,
		m.messagesFailed,
		m.processingDuration,
		m.runtimeDuration,
		m.queueReceiveDuration,
		m.queueSendDuration,
		m.messageSize,
		m.activeMessages,
		m.runtimeErrors,
	)

	// Register custom metrics
	for _, config := range customMetricsConfig {
		m.registerCustomMetric(config)
	}

	return m
}

// registerCustomMetric registers a custom metric
func (m *Metrics) registerCustomMetric(config config.CustomMetricConfig) {
	name := sanitizeMetricName(config.Name)

	switch strings.ToLower(config.Type) {
	case "counter":
		counter := prometheus.NewCounterVec(
			prometheus.CounterOpts{
				Name: name,
				Help: config.Help,
			},
			config.Labels,
		)
		m.customCounters[name] = counter
		m.registry.MustRegister(counter)
		slog.Debug("Registered custom counter", "name", name)

	case "gauge":
		gauge := prometheus.NewGaugeVec(
			prometheus.GaugeOpts{
				Name: name,
				Help: config.Help,
			},
			config.Labels,
		)
		m.customGauges[name] = gauge
		m.registry.MustRegister(gauge)
		slog.Debug("Registered custom gauge", "name", name)

	case "histogram":
		buckets := config.Buckets
		if len(buckets) == 0 {
			buckets = prometheus.DefBuckets
		}
		histogram := prometheus.NewHistogramVec(
			prometheus.HistogramOpts{
				Name:    name,
				Help:    config.Help,
				Buckets: buckets,
			},
			config.Labels,
		)
		m.customHistograms[name] = histogram
		m.registry.MustRegister(histogram)
		slog.Debug("Registered custom histogram", "name", name)

	default:
		slog.Warn("Unknown metric type", "type", config.Type, "name", name)
	}
}

// sanitizeMetricName ensures metric name follows Prometheus conventions
func sanitizeMetricName(name string) string {
	// Replace invalid characters with underscores
	sanitized := strings.Map(func(r rune) rune {
		if (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') || r == '_' || r == ':' {
			return r
		}
		return '_'
	}, name)

	// Ensure it doesn't start with a number
	if len(sanitized) > 0 && sanitized[0] >= '0' && sanitized[0] <= '9' {
		sanitized = "_" + sanitized
	}

	return sanitized
}

// Standard metric recording methods

func (m *Metrics) RecordMessageReceived(queue, transport string) {
	m.messagesReceived.WithLabelValues(queue, transport).Inc()
}

func (m *Metrics) RecordMessageProcessed(queue, status string) {
	m.messagesProcessed.WithLabelValues(queue, status).Inc()
}

func (m *Metrics) RecordMessageSent(destinationQueue, messageType string) {
	m.messagesSent.WithLabelValues(destinationQueue, messageType).Inc()
}

func (m *Metrics) RecordMessageFailed(queue, reason string) {
	m.messagesFailed.WithLabelValues(queue, reason).Inc()
}

func (m *Metrics) RecordProcessingDuration(queue string, duration time.Duration) {
	m.processingDuration.WithLabelValues(queue).Observe(duration.Seconds())
}

func (m *Metrics) RecordRuntimeDuration(queue string, duration time.Duration) {
	m.runtimeDuration.WithLabelValues(queue).Observe(duration.Seconds())
}

func (m *Metrics) RecordQueueReceiveDuration(queue, transport string, duration time.Duration) {
	m.queueReceiveDuration.WithLabelValues(queue, transport).Observe(duration.Seconds())
}

func (m *Metrics) RecordQueueSendDuration(destinationQueue, transport string, duration time.Duration) {
	m.queueSendDuration.WithLabelValues(destinationQueue, transport).Observe(duration.Seconds())
}

func (m *Metrics) RecordMessageSize(direction string, size int) {
	m.messageSize.WithLabelValues(direction).Observe(float64(size))
}

func (m *Metrics) IncrementActiveEnvelopes() {
	m.activeMessages.Inc()
}

func (m *Metrics) DecrementActiveEnvelopes() {
	m.activeMessages.Dec()
}

func (m *Metrics) RecordRuntimeError(queue, errorType string) {
	m.runtimeErrors.WithLabelValues(queue, errorType).Inc()
}

// Custom metric recording methods

// IncrementCustomCounter increments a custom counter
func (m *Metrics) IncrementCustomCounter(name string, labelValues ...string) error {
	counter, exists := m.customCounters[name]
	if !exists {
		return fmt.Errorf("custom counter '%s' not found", name)
	}
	counter.WithLabelValues(labelValues...).Inc()
	return nil
}

// AddCustomCounter adds a value to a custom counter
func (m *Metrics) AddCustomCounter(name string, value float64, labelValues ...string) error {
	counter, exists := m.customCounters[name]
	if !exists {
		return fmt.Errorf("custom counter '%s' not found", name)
	}
	counter.WithLabelValues(labelValues...).Add(value)
	return nil
}

// SetCustomGauge sets a custom gauge value
func (m *Metrics) SetCustomGauge(name string, value float64, labelValues ...string) error {
	gauge, exists := m.customGauges[name]
	if !exists {
		return fmt.Errorf("custom gauge '%s' not found", name)
	}
	gauge.WithLabelValues(labelValues...).Set(value)
	return nil
}

// IncrementCustomGauge increments a custom gauge
func (m *Metrics) IncrementCustomGauge(name string, labelValues ...string) error {
	gauge, exists := m.customGauges[name]
	if !exists {
		return fmt.Errorf("custom gauge '%s' not found", name)
	}
	gauge.WithLabelValues(labelValues...).Inc()
	return nil
}

// DecrementCustomGauge decrements a custom gauge
func (m *Metrics) DecrementCustomGauge(name string, labelValues ...string) error {
	gauge, exists := m.customGauges[name]
	if !exists {
		return fmt.Errorf("custom gauge '%s' not found", name)
	}
	gauge.WithLabelValues(labelValues...).Dec()
	return nil
}

// ObserveCustomHistogram records an observation in a custom histogram
func (m *Metrics) ObserveCustomHistogram(name string, value float64, labelValues ...string) error {
	histogram, exists := m.customHistograms[name]
	if !exists {
		return fmt.Errorf("custom histogram '%s' not found", name)
	}
	histogram.WithLabelValues(labelValues...).Observe(value)
	return nil
}

// Handler returns an HTTP handler for Prometheus metrics endpoint
func (m *Metrics) Handler() http.Handler {
	return promhttp.HandlerFor(m.registry, promhttp.HandlerOpts{
		EnableOpenMetrics: true,
	})
}

// StartMetricsServer starts an HTTP server for Prometheus metrics
func (m *Metrics) StartMetricsServer(ctx context.Context, addr string) error {
	mux := http.NewServeMux()
	mux.Handle("/metrics", m.Handler())
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("OK"))
	})

	server := &http.Server{
		Addr:    addr,
		Handler: mux,
	}

	go func() {
		<-ctx.Done()
		slog.Info("Shutting down metrics server")
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdownCtx)
	}()

	slog.Info("Starting metrics server", "addr", addr)
	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		return fmt.Errorf("metrics server error: %w", err)
	}

	return nil
}
