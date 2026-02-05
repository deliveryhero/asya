package metrics

import (
	"testing"
	"time"

	"github.com/deliveryhero/asya/asya-sidecar/internal/config"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/testutil"
)

func TestNewMetrics(t *testing.T) {
	tests := []struct {
		name                string
		namespace           string
		customMetricsConfig []config.CustomMetricConfig
		expectedCustomCount int
	}{
		{
			name:                "without custom metrics",
			namespace:           "test_actor",
			customMetricsConfig: []config.CustomMetricConfig{},
			expectedCustomCount: 0,
		},
		{
			name:      "with custom counter",
			namespace: "test_actor",
			customMetricsConfig: []config.CustomMetricConfig{
				{
					Name:   "my_custom_counter",
					Type:   "counter",
					Help:   "A custom counter",
					Labels: []string{"label1"},
				},
			},
			expectedCustomCount: 1,
		},
		{
			name:      "with custom gauge",
			namespace: "test_actor",
			customMetricsConfig: []config.CustomMetricConfig{
				{
					Name:   "my_custom_gauge",
					Type:   "gauge",
					Help:   "A custom gauge",
					Labels: []string{"label1"},
				},
			},
			expectedCustomCount: 1,
		},
		{
			name:      "with custom histogram",
			namespace: "test_actor",
			customMetricsConfig: []config.CustomMetricConfig{
				{
					Name:   "my_custom_histogram",
					Type:   "histogram",
					Help:   "A custom histogram",
					Labels: []string{"label1"},
				},
			},
			expectedCustomCount: 1,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			m := NewMetrics(tt.namespace, tt.customMetricsConfig)

			if m == nil {
				t.Fatal("NewMetrics returned nil")
			}

			if m.registry == nil {
				t.Error("Registry is nil")
			}

			if m.messagesReceived == nil {
				t.Error("messagesReceived is nil")
			}

			if m.messagesProcessed == nil {
				t.Error("messagesProcessed is nil")
			}

			customMetricCount := len(m.customCounters) + len(m.customGauges) + len(m.customHistograms)
			if customMetricCount != tt.expectedCustomCount {
				t.Errorf("Expected %d custom metrics, got %d", tt.expectedCustomCount, customMetricCount)
			}
		})
	}
}

func TestMetrics_RecordMessageReceived(t *testing.T) {
	m := NewMetrics("test", []config.CustomMetricConfig{})

	m.RecordMessageReceived("test-queue", "rabbitmq")

	count := testutil.CollectAndCount(m.messagesReceived)
	if count != 1 {
		t.Errorf("Expected 1 metric, got %d", count)
	}

	value := testutil.ToFloat64(m.messagesReceived.With(prometheus.Labels{
		"queue":     "test-queue",
		"transport": "rabbitmq",
	}))

	if value != 1.0 {
		t.Errorf("Expected value 1.0, got %f", value)
	}
}

func TestMetrics_RecordMessageProcessed(t *testing.T) {
	m := NewMetrics("test", []config.CustomMetricConfig{})

	m.RecordMessageProcessed("test-queue", "success")

	value := testutil.ToFloat64(m.messagesProcessed.With(prometheus.Labels{
		"queue":  "test-queue",
		"status": "success",
	}))

	if value != 1.0 {
		t.Errorf("Expected value 1.0, got %f", value)
	}
}

func TestMetrics_RecordMessageSent(t *testing.T) {
	m := NewMetrics("test", []config.CustomMetricConfig{})

	m.RecordMessageSent("next-queue", "routing")

	value := testutil.ToFloat64(m.messagesSent.With(prometheus.Labels{
		"destination_queue": "next-queue",
		"message_type":      "routing",
	}))

	if value != 1.0 {
		t.Errorf("Expected value 1.0, got %f", value)
	}
}

func TestMetrics_RecordMessageFailed(t *testing.T) {
	m := NewMetrics("test", []config.CustomMetricConfig{})

	m.RecordMessageFailed("test-queue", "parse_error")

	value := testutil.ToFloat64(m.messagesFailed.With(prometheus.Labels{
		"queue":  "test-queue",
		"reason": "parse_error",
	}))

	if value != 1.0 {
		t.Errorf("Expected value 1.0, got %f", value)
	}
}

func TestMetrics_RecordDurations(t *testing.T) {
	m := NewMetrics("test", []config.CustomMetricConfig{})

	m.RecordProcessingDuration("test-queue", 100*time.Millisecond)
	m.RecordRuntimeDuration("test-queue", 50*time.Millisecond)
	m.RecordQueueReceiveDuration("test-queue", "rabbitmq", 10*time.Millisecond)
	m.RecordQueueSendDuration("next-queue", "rabbitmq", 5*time.Millisecond)

	// Check that histograms have observations
	if testutil.CollectAndCount(m.processingDuration) == 0 {
		t.Error("processingDuration has no observations")
	}

	if testutil.CollectAndCount(m.runtimeDuration) == 0 {
		t.Error("runtimeDuration has no observations")
	}

	if testutil.CollectAndCount(m.queueReceiveDuration) == 0 {
		t.Error("queueReceiveDuration has no observations")
	}

	if testutil.CollectAndCount(m.queueSendDuration) == 0 {
		t.Error("queueSendDuration has no observations")
	}
}

func TestMetrics_RecordMessageSize(t *testing.T) {
	m := NewMetrics("test", []config.CustomMetricConfig{})

	m.RecordMessageSize("received", 1024)
	m.RecordMessageSize("sent", 512)

	if testutil.CollectAndCount(m.messageSize) == 0 {
		t.Error("messageSize has no observations")
	}
}

func TestMetrics_ActiveEnvelopes(t *testing.T) {
	m := NewMetrics("test", []config.CustomMetricConfig{})

	m.IncrementActiveEnvelopes()
	value := testutil.ToFloat64(m.activeMessages)
	if value != 1.0 {
		t.Errorf("Expected active messages 1.0, got %f", value)
	}

	m.IncrementActiveEnvelopes()
	value = testutil.ToFloat64(m.activeMessages)
	if value != 2.0 {
		t.Errorf("Expected active messages 2.0, got %f", value)
	}

	m.DecrementActiveEnvelopes()
	value = testutil.ToFloat64(m.activeMessages)
	if value != 1.0 {
		t.Errorf("Expected active messages 1.0 after decrement, got %f", value)
	}
}

func TestMetrics_RecordRuntimeError(t *testing.T) {
	m := NewMetrics("test", []config.CustomMetricConfig{})

	m.RecordRuntimeError("test-queue", "connection_timeout")

	value := testutil.ToFloat64(m.runtimeErrors.With(prometheus.Labels{
		"queue":      "test-queue",
		"error_type": "connection_timeout",
	}))

	if value != 1.0 {
		t.Errorf("Expected value 1.0, got %f", value)
	}
}

func TestMetrics_CustomCounter(t *testing.T) {
	customConfig := []config.CustomMetricConfig{
		{
			Name:   "my_counter",
			Type:   "counter",
			Help:   "Test counter",
			Labels: []string{"label1"},
		},
	}

	m := NewMetrics("test", customConfig)

	_ = m.IncrementCustomCounter("my_counter", "value1")
	_ = m.AddCustomCounter("my_counter", 5, "value1")

	if len(m.customCounters) != 1 {
		t.Errorf("Expected 1 custom counter, got %d", len(m.customCounters))
	}

	counter, exists := m.customCounters["my_counter"]
	if !exists {
		t.Fatal("Custom counter 'my_counter' not found")
	}

	value := testutil.ToFloat64(counter.With(prometheus.Labels{"label1": "value1"}))
	if value != 6.0 {
		t.Errorf("Expected counter value 6.0, got %f", value)
	}
}

func TestMetrics_CustomGauge(t *testing.T) {
	customConfig := []config.CustomMetricConfig{
		{
			Name:   "my_gauge",
			Type:   "gauge",
			Help:   "Test gauge",
			Labels: []string{"label1"},
		},
	}

	m := NewMetrics("test", customConfig)

	_ = m.SetCustomGauge("my_gauge", 10, "value1")
	_ = m.IncrementCustomGauge("my_gauge", "value1")
	_ = m.DecrementCustomGauge("my_gauge", "value1")

	if len(m.customGauges) != 1 {
		t.Errorf("Expected 1 custom gauge, got %d", len(m.customGauges))
	}

	gauge, exists := m.customGauges["my_gauge"]
	if !exists {
		t.Fatal("Custom gauge 'my_gauge' not found")
	}

	value := testutil.ToFloat64(gauge.With(prometheus.Labels{"label1": "value1"}))
	if value != 10.0 {
		t.Errorf("Expected gauge value 10.0, got %f", value)
	}
}

func TestMetrics_CustomHistogram(t *testing.T) {
	customConfig := []config.CustomMetricConfig{
		{
			Name:   "my_histogram",
			Type:   "histogram",
			Help:   "Test histogram",
			Labels: []string{"label1"},
		},
	}

	m := NewMetrics("test", customConfig)

	_ = m.ObserveCustomHistogram("my_histogram", 0.5, "value1")

	if len(m.customHistograms) != 1 {
		t.Errorf("Expected 1 custom histogram, got %d", len(m.customHistograms))
	}

	_, exists := m.customHistograms["my_histogram"]
	if !exists {
		t.Fatal("Custom histogram 'my_histogram' not found")
	}
}

func TestMetrics_Handler(t *testing.T) {
	m := NewMetrics("test", []config.CustomMetricConfig{})

	handler := m.Handler()
	if handler == nil {
		t.Error("Handler returned nil")
	}
}

func TestSanitizeMetricName(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"simple_name", "simple_name"},
		{"name-with-dashes", "name_with_dashes"},
		{"name.with.dots", "name_with_dots"},
		{"name with spaces", "name_with_spaces"},
		{"UPPERCASE", "UPPERCASE"},
		{"mix123ED", "mix123ED"},
	}

	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			result := sanitizeMetricName(tt.input)
			if result != tt.expected {
				t.Errorf("sanitizeMetricName(%q) = %q, want %q", tt.input, result, tt.expected)
			}
		})
	}
}
