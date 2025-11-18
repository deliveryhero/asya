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
	// Transport configuration
	TransportType string

	// RabbitMQ configuration
	RabbitMQURL      string
	RabbitMQExchange string
	RabbitMQPrefetch int

	// SQS configuration
	SQSBaseURL           string
	SQSRegion            string
	SQSVisibilityTimeout int32 // seconds
	SQSWaitTimeSeconds   int32

	// Runtime communication
	SocketPath string
	Timeout    time.Duration

	// End queues
	HappyEndQueue string
	ErrorEndQueue string

	// End actor mode
	// When true, the sidecar will NOT route responses from the runtime.
	// This is used for end actors (happy-end, error-end) that consume
	// envelopes but don't produce new ones to route.
	IsEndActor bool

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
	cfg := &Config{
		// Transport configuration
		TransportType: getEnv("ASYA_TRANSPORT", "rabbitmq"),

		// RabbitMQ configuration
		RabbitMQURL:      buildRabbitMQURL(),
		RabbitMQExchange: getEnv("ASYA_RABBITMQ_EXCHANGE", "asya"),
		RabbitMQPrefetch: getEnvInt("ASYA_RABBITMQ_PREFETCH", 1),

		// SQS configuration
		SQSBaseURL:           getEnv("ASYA_SQS_ENDPOINT", ""),
		SQSRegion:            getEnv("ASYA_AWS_REGION", "us-east-1"),
		SQSVisibilityTimeout: getEnvInt32("ASYA_SQS_VISIBILITY_TIMEOUT", 0),
		SQSWaitTimeSeconds:   getEnvInt32("ASYA_SQS_WAIT_TIME_SECONDS", 20),

		// Runtime communication - hard-coded, managed by operator
		// ASYA_SOCKET_DIR is for internal testing only - DO NOT set in production
		SocketPath: "", // Will be set below
		Timeout:    getEnvDuration("ASYA_RUNTIME_TIMEOUT", 5*time.Minute),

		// End queues
		HappyEndQueue: getEnv("ASYA_ACTOR_HAPPY_END", "happy-end"),
		ErrorEndQueue: getEnv("ASYA_ACTOR_ERROR_END", "error-end"),
		IsEndActor:    getEnvBool("ASYA_IS_END_ACTOR", false),

		// Progress reporting
		GatewayURL: getEnv("ASYA_GATEWAY_URL", ""),
		ActorName:  getEnv("ASYA_ACTOR_NAME", ""),

		// Metrics defaults
		MetricsEnabled:   getEnvBool("ASYA_METRICS_ENABLED", true),
		MetricsAddr:      getEnv("ASYA_METRICS_ADDR", ":8080"),
		MetricsNamespace: getEnv("ASYA_METRICS_NAMESPACE", "asya_actor"),
	}

	// Set socket path (allow ASYA_SOCKET_DIR override for testing only)
	socketDir := getEnv("ASYA_SOCKET_DIR", "/var/run/asya")
	cfg.SocketPath = socketDir + "/asya-runtime.sock"

	// Load custom metrics configuration
	if customMetricsJSON := getEnv("ASYA_CUSTOM_METRICS", ""); customMetricsJSON != "" {
		var customMetrics []CustomMetricConfig
		if err := json.Unmarshal([]byte(customMetricsJSON), &customMetrics); err != nil {
			return nil, fmt.Errorf("failed to parse ASYA_CUSTOM_METRICS: %w", err)
		}
		cfg.CustomMetrics = customMetrics
	}

	// Validate
	if cfg.ActorName == "" {
		return nil, fmt.Errorf("ASYA_ACTOR_NAME is required")
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

func getEnvInt32(key string, defaultValue int32) int32 {
	if value := os.Getenv(key); value != "" {
		if i, err := strconv.ParseInt(value, 10, 32); err == nil {
			return int32(i)
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

func buildRabbitMQURL() string {
	if url := os.Getenv("ASYA_RABBITMQ_URL"); url != "" {
		return url
	}

	host := getEnv("ASYA_RABBITMQ_HOST", "localhost")
	port := getEnv("ASYA_RABBITMQ_PORT", "5672")
	username := getEnv("ASYA_RABBITMQ_USERNAME", "guest")
	password := getEnv("ASYA_RABBITMQ_PASSWORD", "guest")

	return fmt.Sprintf("amqp://%s:%s@%s:%s/", username, password, host, port)
}
