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

	// Pub/Sub configuration
	PubSubProjectID string
	PubSubEndpoint  string

	// Socket transport configuration (local Docker Compose testing only)
	MeshDir string

	// Runtime communication
	SocketPath string
	Timeout    time.Duration

	// End queues
	SinkQueue string
	SumpQueue string

	// End actor mode
	// When true, the sidecar will NOT route responses from the runtime.
	// This is used for end actors (x-sink, x-sump) that consume
	// messages but don't produce new ones to route.
	IsEndActor bool

	// Gateway integration for progress reporting
	GatewayURL string
	ActorName  string
	Namespace  string

	// Metrics configuration
	MetricsEnabled   bool
	MetricsAddr      string
	MetricsNamespace string
	CustomMetrics    []CustomMetricConfig

	// Resiliency configuration (optional, nil means no retry)
	Resiliency *ResiliencyConfig
}

// RetryPolicy defines the retry backoff strategy.
type RetryPolicy string

const (
	RetryPolicyConstant    RetryPolicy = "constant"
	RetryPolicyExponential RetryPolicy = "exponential"
)

// Resiliency environment variable keys.
const (
	envResiliencyRetryPolicy      = "ASYA_RESILIENCY_RETRY_POLICY"
	envResiliencyRetryMaxAttempts = "ASYA_RESILIENCY_RETRY_MAX_ATTEMPTS"
	envResiliencyRetryInitial     = "ASYA_RESILIENCY_RETRY_INITIAL_INTERVAL"
	envResiliencyRetryMax         = "ASYA_RESILIENCY_RETRY_MAX_INTERVAL"
	envResiliencyRetryCoefficient = "ASYA_RESILIENCY_RETRY_BACKOFF_COEFFICIENT"
	envResiliencyRetryJitter      = "ASYA_RESILIENCY_RETRY_JITTER"
	envResiliencyNonRetryable     = "ASYA_RESILIENCY_NON_RETRYABLE_ERRORS"
)

// resiliencyEnvKeys lists ASYA_RESILIENCY_* env var keys that activate retry logic.
// ASYA_RESILIENCY_ACTOR_TIMEOUT is intentionally excluded: it controls Config.Timeout
// (the per-call timeout) and does not activate retry behaviour on its own.
var resiliencyEnvKeys = []string{
	envResiliencyRetryPolicy,
	envResiliencyRetryMaxAttempts,
	envResiliencyRetryInitial,
	envResiliencyRetryMax,
	envResiliencyRetryCoefficient,
	envResiliencyRetryJitter,
	envResiliencyNonRetryable,
}

// ResiliencyConfig holds optional retry configuration for an actor.
// When nil, the actor does not retry (single attempt).
// The per-call timeout (ASYA_RESILIENCY_ACTOR_TIMEOUT) lives in Config.Timeout,
// not here, because it applies independently of retry logic.
type ResiliencyConfig struct {
	Retry              RetryConfig
	NonRetryableErrors []string
}

// RetryConfig holds retry-specific parameters.
type RetryConfig struct {
	Policy             RetryPolicy
	MaxAttempts        int
	InitialInterval    time.Duration
	MaxInterval        time.Duration
	BackoffCoefficient float64
	Jitter             bool
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

		// Pub/Sub configuration
		PubSubProjectID: getEnv("ASYA_PUBSUB_PROJECT_ID", ""),
		PubSubEndpoint:  getEnv("ASYA_PUBSUB_ENDPOINT", ""),

		// Socket transport configuration (local Docker Compose testing only)
		MeshDir: getEnv("ASYA_SOCKET_MESH_DIR", "/var/run/asya/mesh"),

		// Runtime communication - hard-coded, managed by operator
		// ASYA_SOCKET_DIR is for internal testing only - DO NOT set in production
		SocketPath: "", // Will be set below
		Timeout:    getEnvDuration("ASYA_RESILIENCY_ACTOR_TIMEOUT", 5*time.Minute),

		// End queues
		SinkQueue:  getEnv("ASYA_ACTOR_SINK", "x-sink"),
		SumpQueue:  getEnv("ASYA_ACTOR_SUMP", "x-sump"),
		IsEndActor: getEnvBool("ASYA_IS_END_ACTOR", false),

		// Progress reporting
		GatewayURL: getEnv("ASYA_GATEWAY_URL", ""),
		ActorName:  getEnv("ASYA_ACTOR_NAME", ""),
		Namespace:  getEnv("ASYA_NAMESPACE", ""),

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

	// Load resiliency configuration (optional)
	resiliency, err := loadResiliencyConfig()
	if err != nil {
		return nil, err
	}
	cfg.Resiliency = resiliency

	// Validate
	if cfg.ActorName == "" {
		return nil, fmt.Errorf("ASYA_ACTOR_NAME is required")
	}
	if cfg.Namespace == "" {
		return nil, fmt.Errorf("ASYA_NAMESPACE is required")
	}

	return cfg, nil
}

// loadResiliencyConfig parses ASYA_RESILIENCY_* env vars into a ResiliencyConfig.
// Returns nil if no resiliency env vars are set (actor does not retry).
func loadResiliencyConfig() (*ResiliencyConfig, error) {
	// Check if any resiliency env var is set
	if !hasResiliencyConfig() {
		return nil, nil
	}

	policy := RetryPolicy(getEnv(envResiliencyRetryPolicy, "exponential"))
	if policy != RetryPolicyConstant && policy != RetryPolicyExponential {
		return nil, fmt.Errorf("%s must be 'constant' or 'exponential', got %q", envResiliencyRetryPolicy, policy)
	}

	maxAttempts := getEnvInt(envResiliencyRetryMaxAttempts, 3)
	if maxAttempts < 0 {
		return nil, fmt.Errorf("%s must be >= 0, got %d", envResiliencyRetryMaxAttempts, maxAttempts)
	}

	initialInterval := getEnvDuration(envResiliencyRetryInitial, time.Second)
	if initialInterval <= 0 {
		return nil, fmt.Errorf("%s must be > 0, got %v", envResiliencyRetryInitial, initialInterval)
	}

	maxInterval := getEnvDuration(envResiliencyRetryMax, 300*time.Second)
	if maxInterval <= 0 {
		return nil, fmt.Errorf("%s must be > 0, got %v", envResiliencyRetryMax, maxInterval)
	}

	coefficient := getEnvFloat64(envResiliencyRetryCoefficient, 2.0)
	if coefficient < 1.0 {
		return nil, fmt.Errorf("%s must be >= 1.0, got %v", envResiliencyRetryCoefficient, coefficient)
	}

	jitter := getEnvBool(envResiliencyRetryJitter, true)

	var nonRetryable []string
	if raw := os.Getenv(envResiliencyNonRetryable); raw != "" {
		for _, s := range strings.Split(raw, ",") {
			if trimmed := strings.TrimSpace(s); trimmed != "" {
				nonRetryable = append(nonRetryable, trimmed)
			}
		}
	}

	return &ResiliencyConfig{
		Retry: RetryConfig{
			Policy:             policy,
			MaxAttempts:        maxAttempts,
			InitialInterval:    initialInterval,
			MaxInterval:        maxInterval,
			BackoffCoefficient: coefficient,
			Jitter:             jitter,
		},
		NonRetryableErrors: nonRetryable,
	}, nil
}

// hasResiliencyConfig checks if any ASYA_RESILIENCY_* env var is set.
func hasResiliencyConfig() bool {
	for _, key := range resiliencyEnvKeys {
		if os.Getenv(key) != "" {
			return true
		}
	}
	return false
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

func getEnvFloat64(key string, defaultValue float64) float64 {
	if value := os.Getenv(key); value != "" {
		if f, err := strconv.ParseFloat(value, 64); err == nil {
			return f
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
