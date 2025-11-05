package config

import (
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	// Queue configuration
	QueueName string

	// RabbitMQ configuration
	RabbitMQURL      string
	RabbitMQExchange string
	RabbitMQPrefetch int

	// Runtime communication
	SocketPath string
	Timeout    time.Duration

	// Terminal queues
	HappyEndQueue string
	ErrorEndQueue string

	// Terminal actor mode
	// When true, the sidecar will NOT route responses from the runtime.
	// This is used for terminal actors (happy-end, error-end) that consume
	// messages but don't produce new ones to route.
	IsTerminal bool

	// Gateway integration for progress reporting
	GatewayURL string
	ActorName  string

	// Metrics configuration
	MetricsEnabled   bool
	MetricsAddr      string
	MetricsNamespace string
	CustomMetrics    []CustomMetricConfig
}

// CustomMetricConfig defines configuration for a custom metric
type CustomMetricConfig struct {
	Name    string    `json:"name"`
	Type    string    `json:"type"` // counter, gauge, histogram
	Help    string    `json:"help"`
	Labels  []string  `json:"labels"`
	Buckets []float64 `json:"buckets,omitempty"` // for histograms only
}

func LoadFromEnv() (*Config, error) {
	// Read queue name first (required)
	queueName := getEnv("ASYA_QUEUE_NAME", "")

	cfg := &Config{
		// Queue configuration
		QueueName:        queueName,
		RabbitMQURL:      getEnv("ASYA_RABBITMQ_URL", "amqp://guest:guest@localhost:5672/"),
		RabbitMQExchange: getEnv("ASYA_RABBITMQ_EXCHANGE", "asya"),
		RabbitMQPrefetch: getEnvInt("ASYA_RABBITMQ_PREFETCH", 1),
		SocketPath:       getEnv("ASYA_SOCKET_PATH", "/tmp/sockets/app.sock"),
		Timeout:          getEnvDuration("ASYA_RUNTIME_TIMEOUT", 5*time.Minute),
		HappyEndQueue:    getEnv("ASYA_STEP_HAPPY_END", "happy-end"),
		ErrorEndQueue:    getEnv("ASYA_STEP_ERROR_END", "error-end"),
		IsTerminal:       getEnvBool("ASYA_IS_TERMINAL", false),

		// Progress reporting
		GatewayURL: getEnv("ASYA_GATEWAY_URL", ""),
		ActorName:  getEnv("ASYA_ACTOR_NAME", queueName),

		// Metrics defaults
		MetricsEnabled:   getEnvBool("ASYA_METRICS_ENABLED", true),
		MetricsAddr:      getEnv("ASYA_METRICS_ADDR", ":8080"),
		MetricsNamespace: getEnv("ASYA_METRICS_NAMESPACE", "asya_actor"),
	}

	// Load custom metrics configuration
	if customMetricsJSON := getEnv("ASYA_CUSTOM_METRICS", ""); customMetricsJSON != "" {
		var customMetrics []CustomMetricConfig
		if err := json.Unmarshal([]byte(customMetricsJSON), &customMetrics); err != nil {
			return nil, fmt.Errorf("failed to parse ASYA_CUSTOM_METRICS: %w", err)
		}
		cfg.CustomMetrics = customMetrics
	}

	// Validate
	if cfg.QueueName == "" {
		return nil, fmt.Errorf("ASYA_QUEUE_NAME is required")
	}

	return cfg, nil
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

func getEnvInt(key string, defaultValue int) int {
	if value := os.Getenv(key); value != "" {
		if i, err := strconv.Atoi(value); err == nil {
			return i
		}
	}
	return defaultValue
}

func getEnvDuration(key string, defaultValue time.Duration) time.Duration {
	if value := os.Getenv(key); value != "" {
		if d, err := time.ParseDuration(value); err == nil {
			return d
		}
	}
	return defaultValue
}

func getEnvBool(key string, defaultValue bool) bool {
	if value := os.Getenv(key); value != "" {
		switch strings.ToLower(value) {
		case "true", "1", "yes", "on":
			return true
		case "false", "0", "no", "off":
			return false
		}
	}
	return defaultValue
}
