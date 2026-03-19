package config

import (
	"os"
	"testing"
	"time"
)

func TestLoadFromEnv(t *testing.T) {
	// Save and restore original env
	origEnv := os.Environ()
	defer func() {
		os.Clearenv()
		for _, e := range origEnv {
			pair := splitEnv(e)
			_ = os.Setenv(pair[0], pair[1])
		}
	}()

	tests := []struct {
		name        string
		env         map[string]string
		expectError bool
		validate    func(*testing.T, *Config)
	}{
		{
			name: "valid RabbitMQ config",
			env: map[string]string{
				"ASYA_ACTOR_NAME":               "test-actor",
				"ASYA_NAMESPACE":                "default",
				"ASYA_RABBITMQ_URL":             "amqp://localhost:5672/",
				"ASYA_RESILIENCY_ACTOR_TIMEOUT": "10m",
			},
			expectError: false,
			validate: func(t *testing.T, cfg *Config) {
				if cfg.ActorName != "test-actor" {
					t.Errorf("ActorName = %v, want test-actor", cfg.ActorName)
				}
				if cfg.RabbitMQURL != "amqp://localhost:5672/" {
					t.Errorf("RabbitMQURL = %v, want amqp://localhost:5672/", cfg.RabbitMQURL)
				}
				if cfg.Timeout != 10*time.Minute {
					t.Errorf("Timeout = %v, want 10m", cfg.Timeout)
				}
				if cfg.Resiliency != nil {
					t.Error("Resiliency should be nil when only actor timeout is set")
				}
			},
		},
		{
			name:        "missing actor name",
			env:         map[string]string{},
			expectError: true,
		},
		{
			name: "default values",
			env: map[string]string{
				"ASYA_ACTOR_NAME": "test-actor",
				"ASYA_NAMESPACE":  "default",
			},
			expectError: false,
			validate: func(t *testing.T, cfg *Config) {
				if cfg.RabbitMQURL != "amqp://guest:guest@localhost:5672/" {
					t.Errorf("Default RabbitMQURL = %v, want amqp://guest:guest@localhost:5672/", cfg.RabbitMQURL)
				}
				if cfg.RabbitMQExchange != "asya" {
					t.Errorf("Default RabbitMQExchange = %v, want asya", cfg.RabbitMQExchange)
				}
				if cfg.SinkQueue != "x-sink" {
					t.Errorf("Default SinkQueue = %v, want x-sink", cfg.SinkQueue)
				}
				if cfg.SumpQueue != "x-sump" {
					t.Errorf("Default SumpQueue = %v, want x-sump", cfg.SumpQueue)
				}
			},
		},
		{
			name: "custom metrics configuration",
			env: map[string]string{
				"ASYA_ACTOR_NAME":     "test-actor",
				"ASYA_NAMESPACE":      "default",
				"ASYA_CUSTOM_METRICS": `[{"name":"custom_counter","type":"counter","help":"Test counter","labels":["label1"]}]`,
			},
			expectError: false,
			validate: func(t *testing.T, cfg *Config) {
				if len(cfg.CustomMetrics) != 1 {
					t.Errorf("CustomMetrics length = %v, want 1", len(cfg.CustomMetrics))
				}
				if len(cfg.CustomMetrics) > 0 && cfg.CustomMetrics[0].Name != "custom_counter" {
					t.Errorf("CustomMetrics[0].Name = %v, want custom_counter", cfg.CustomMetrics[0].Name)
				}
			},
		},
		{
			name: "invalid custom metrics JSON",
			env: map[string]string{
				"ASYA_ACTOR_NAME":     "test-actor",
				"ASYA_CUSTOM_METRICS": `{invalid json`,
			},
			expectError: true,
		},
		{
			name: "end actor configuration",
			env: map[string]string{
				"ASYA_ACTOR_NAME":   "x-sink",
				"ASYA_NAMESPACE":    "default",
				"ASYA_IS_END_ACTOR": "true",
			},
			expectError: false,
			validate: func(t *testing.T, cfg *Config) {
				if !cfg.IsEndActor {
					t.Error("IsEndActor should be true")
				}
			},
		},
		{
			name: "SQS configuration",
			env: map[string]string{
				"ASYA_ACTOR_NAME":   "test-actor",
				"ASYA_NAMESPACE":    "default",
				"ASYA_TRANSPORT":    "sqs",
				"ASYA_SQS_ENDPOINT": "https://sqs.us-west-2.amazonaws.com/123456789",
				"ASYA_AWS_REGION":   "us-west-2",
			},
			expectError: false,
			validate: func(t *testing.T, cfg *Config) {
				if cfg.TransportType != "sqs" {
					t.Errorf("TransportType = %v, want sqs", cfg.TransportType)
				}
				if cfg.SQSBaseURL != "https://sqs.us-west-2.amazonaws.com/123456789" {
					t.Errorf("SQSBaseURL = %v", cfg.SQSBaseURL)
				}
				if cfg.SQSRegion != "us-west-2" {
					t.Errorf("SQSRegion = %v, want us-west-2", cfg.SQSRegion)
				}
			},
		},
		{
			name: "gateway URL and metrics configuration",
			env: map[string]string{
				"ASYA_ACTOR_NAME":        "test-actor",
				"ASYA_NAMESPACE":         "default",
				"ASYA_GATEWAY_URL":       "http://gateway:8080",
				"ASYA_METRICS_ENABLED":   "false",
				"ASYA_METRICS_ADDR":      ":9090",
				"ASYA_METRICS_NAMESPACE": "custom_namespace",
			},
			expectError: false,
			validate: func(t *testing.T, cfg *Config) {
				if cfg.GatewayURL != "http://gateway:8080" {
					t.Errorf("GatewayURL = %v, want http://gateway:8080", cfg.GatewayURL)
				}
				if cfg.MetricsEnabled {
					t.Error("MetricsEnabled should be false")
				}
				if cfg.MetricsAddr != ":9090" {
					t.Errorf("MetricsAddr = %v, want :9090", cfg.MetricsAddr)
				}
				if cfg.MetricsNamespace != "custom_namespace" {
					t.Errorf("MetricsNamespace = %v, want custom_namespace", cfg.MetricsNamespace)
				}
			},
		},
		{
			name: "custom sockets dir and custom queues",
			env: map[string]string{
				"ASYA_ACTOR_NAME": "test-actor",
				"ASYA_NAMESPACE":  "default",
				"ASYA_SOCKET_DIR": "/custom/path",
				"ASYA_ACTOR_SINK": "custom-happy",
				"ASYA_ACTOR_SUMP": "custom-error",
			},
			expectError: false,
			validate: func(t *testing.T, cfg *Config) {
				if cfg.SocketPath != "/custom/path/asya-runtime.sock" {
					t.Errorf("SocketPath = %v, want /custom/path/asya-runtime.sock", cfg.SocketPath)
				}
				if cfg.SinkQueue != "custom-happy" {
					t.Errorf("SinkQueue = %v, want custom-happy", cfg.SinkQueue)
				}
				if cfg.SumpQueue != "custom-error" {
					t.Errorf("SumpQueue = %v, want custom-error", cfg.SumpQueue)
				}
			},
		},
		{
			name: "RabbitMQ prefetch configuration",
			env: map[string]string{
				"ASYA_ACTOR_NAME":        "test-actor",
				"ASYA_NAMESPACE":         "default",
				"ASYA_RABBITMQ_PREFETCH": "10",
			},
			expectError: false,
			validate: func(t *testing.T, cfg *Config) {
				if cfg.RabbitMQPrefetch != 10 {
					t.Errorf("RabbitMQPrefetch = %v, want 10", cfg.RabbitMQPrefetch)
				}
			},
		},
		{
			name: "RabbitMQ URL from individual env vars",
			env: map[string]string{
				"ASYA_ACTOR_NAME":        "test-actor",
				"ASYA_NAMESPACE":         "default",
				"ASYA_RABBITMQ_HOST":     "rabbitmq.svc.cluster.local",
				"ASYA_RABBITMQ_PORT":     "5672",
				"ASYA_RABBITMQ_USERNAME": "user",
				"ASYA_RABBITMQ_PASSWORD": "pass",
			},
			expectError: false,
			validate: func(t *testing.T, cfg *Config) {
				expected := "amqp://user:pass@rabbitmq.svc.cluster.local:5672/"
				if cfg.RabbitMQURL != expected {
					t.Errorf("RabbitMQURL = %v, want %v", cfg.RabbitMQURL, expected)
				}
			},
		},
		{
			name: "RabbitMQ URL env var takes precedence",
			env: map[string]string{
				"ASYA_ACTOR_NAME":        "test-actor",
				"ASYA_NAMESPACE":         "default",
				"ASYA_RABBITMQ_URL":      "amqp://override:override@override:5672/",
				"ASYA_RABBITMQ_HOST":     "rabbitmq.svc.cluster.local",
				"ASYA_RABBITMQ_PORT":     "5672",
				"ASYA_RABBITMQ_USERNAME": "user",
				"ASYA_RABBITMQ_PASSWORD": "pass",
			},
			expectError: false,
			validate: func(t *testing.T, cfg *Config) {
				expected := "amqp://override:override@override:5672/"
				if cfg.RabbitMQURL != expected {
					t.Errorf("RabbitMQURL = %v, want %v", cfg.RabbitMQURL, expected)
				}
			},
		},
		{
			name: "no resiliency config when env vars absent",
			env: map[string]string{
				"ASYA_ACTOR_NAME": "test-actor",
				"ASYA_NAMESPACE":  "default",
			},
			validate: func(t *testing.T, cfg *Config) {
				if cfg.Resiliency != nil {
					t.Error("Resiliency should be nil when no ASYA_RESILIENCY_* vars set")
				}
			},
		},
		{
			name: "policies and rules from JSON env vars",
			env: map[string]string{
				"ASYA_ACTOR_NAME": "test-actor",
				"ASYA_NAMESPACE":  "default",
				"ASYA_RESILIENCY_POLICIES": `{"default":{"maxAttempts":3,"backoff":"exponential","initialDelay":"1s","maxInterval":"300s","jitter":true},"retryFast":{"maxAttempts":5,"backoff":"exponential","initialDelay":"500ms","maxInterval":"60s"}}`,
				"ASYA_RESILIENCY_RULES":    `[{"errors":["ConnectionError","NetworkError"],"policy":"retryFast"}]`,
			},
			expectError: false,
			validate: func(t *testing.T, cfg *Config) {
				if cfg.Resiliency == nil {
					t.Fatal("Resiliency should not be nil")
				}
				if len(cfg.Resiliency.Policies) != 2 {
					t.Errorf("Policies count = %d, want 2", len(cfg.Resiliency.Policies))
				}
				def, ok := cfg.Resiliency.Policies["default"]
				if !ok {
					t.Fatal("Policies should have 'default'")
				}
				if def.MaxAttempts != 3 {
					t.Errorf("default.MaxAttempts = %d, want 3", def.MaxAttempts)
				}
				if def.InitialDelay.Duration() != time.Second {
					t.Errorf("default.InitialDelay = %v, want 1s", def.InitialDelay.Duration())
				}
				if !def.Jitter {
					t.Error("default.Jitter should be true")
				}
				if len(cfg.Resiliency.Rules) != 1 {
					t.Errorf("Rules count = %d, want 1", len(cfg.Resiliency.Rules))
				}
				if cfg.Resiliency.Rules[0].Policy != "retryFast" {
					t.Errorf("Rules[0].Policy = %q, want 'retryFast'", cfg.Resiliency.Rules[0].Policy)
				}
			},
		},
		{
			name: "only actor timeout does not activate resiliency",
			env: map[string]string{
				"ASYA_ACTOR_NAME":               "test-actor",
				"ASYA_NAMESPACE":                "default",
				"ASYA_RESILIENCY_ACTOR_TIMEOUT": "10m",
			},
			expectError: false,
			validate: func(t *testing.T, cfg *Config) {
				if cfg.Resiliency != nil {
					t.Error("Resiliency should be nil when only actor timeout is set")
				}
			},
		},
		{
			name: "invalid JSON in ASYA_RESILIENCY_POLICIES fails",
			env: map[string]string{
				"ASYA_ACTOR_NAME":          "test-actor",
				"ASYA_NAMESPACE":           "default",
				"ASYA_RESILIENCY_POLICIES": `{invalid`,
			},
			expectError: true,
		},
		{
			name: "invalid duration in policy fails",
			env: map[string]string{
				"ASYA_ACTOR_NAME":          "test-actor",
				"ASYA_NAMESPACE":           "default",
				"ASYA_RESILIENCY_POLICIES": `{"default":{"initialDelay":"notaduration"}}`,
			},
			expectError: true,
		},
		{
			name: "rules-only config is valid",
			env: map[string]string{
				"ASYA_ACTOR_NAME":       "test-actor",
				"ASYA_NAMESPACE":        "default",
				"ASYA_RESILIENCY_RULES": `[{"errors":["ValueError"],"policy":"noRetry"}]`,
			},
			expectError: false,
			validate: func(t *testing.T, cfg *Config) {
				if cfg.Resiliency == nil {
					t.Fatal("Resiliency should not be nil")
				}
				if len(cfg.Resiliency.Rules) != 1 {
					t.Errorf("Rules count = %d, want 1", len(cfg.Resiliency.Rules))
				}
			},
		},
		{
			name: "actor timeout alone does not activate resiliency",
			env: map[string]string{
				"ASYA_ACTOR_NAME":               "test-actor",
				"ASYA_NAMESPACE":                "default",
				"ASYA_RESILIENCY_ACTOR_TIMEOUT": "30s",
			},
			validate: func(t *testing.T, cfg *Config) {
				if cfg.Timeout != 30*time.Second {
					t.Errorf("Timeout = %v, want 30s", cfg.Timeout)
				}
				if cfg.Resiliency != nil {
					t.Error("Resiliency should be nil when only actor timeout is set")
				}
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Clear and set env
			os.Clearenv()
			for k, v := range tt.env {
				_ = os.Setenv(k, v)
			}

			cfg, err := LoadFromEnv()

			if tt.expectError {
				if err == nil {
					t.Error("Expected error but got nil")
				}
				return
			}

			if err != nil {
				t.Fatalf("Unexpected error: %v", err)
			}

			if tt.validate != nil {
				tt.validate(t, cfg)
			}
		})
	}
}

func splitEnv(s string) [2]string {
	for i := 0; i < len(s); i++ {
		if s[i] == '=' {
			return [2]string{s[:i], s[i+1:]}
		}
	}
	return [2]string{s, ""}
}
