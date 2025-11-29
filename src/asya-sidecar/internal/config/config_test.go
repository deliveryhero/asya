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
				"ASYA_ACTOR_NAME":      "test-actor",
				"ASYA_RABBITMQ_URL":    "amqp://localhost:5672/",
				"ASYA_RUNTIME_TIMEOUT": "10m",
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
			},
			expectError: false,
			validate: func(t *testing.T, cfg *Config) {
				if cfg.RabbitMQURL != "amqp://guest:guest@localhost:5672/" {
					t.Errorf("Default RabbitMQURL = %v, want amqp://guest:guest@localhost:5672/", cfg.RabbitMQURL)
				}
				if cfg.RabbitMQExchange != "asya" {
					t.Errorf("Default RabbitMQExchange = %v, want asya", cfg.RabbitMQExchange)
				}
				if cfg.HappyEndQueue != "happy-end" {
					t.Errorf("Default HappyEndQueue = %v, want happy-end", cfg.HappyEndQueue)
				}
				if cfg.ErrorEndQueue != "error-end" {
					t.Errorf("Default ErrorEndQueue = %v, want error-end", cfg.ErrorEndQueue)
				}
			},
		},
		{
			name: "custom metrics configuration",
			env: map[string]string{
				"ASYA_ACTOR_NAME":     "test-actor",
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
				"ASYA_ACTOR_NAME":   "happy-end",
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
				"ASYA_ACTOR_NAME":      "test-actor",
				"ASYA_SOCKET_DIR":      "/custom/path",
				"ASYA_ACTOR_HAPPY_END": "custom-happy",
				"ASYA_ACTOR_ERROR_END": "custom-error",
			},
			expectError: false,
			validate: func(t *testing.T, cfg *Config) {
				if cfg.SocketPath != "/custom/path/asya-runtime.sock" {
					t.Errorf("SocketPath = %v, want /custom/path/asya-runtime.sock", cfg.SocketPath)
				}
				if cfg.HappyEndQueue != "custom-happy" {
					t.Errorf("HappyEndQueue = %v, want custom-happy", cfg.HappyEndQueue)
				}
				if cfg.ErrorEndQueue != "custom-error" {
					t.Errorf("ErrorEndQueue = %v, want custom-error", cfg.ErrorEndQueue)
				}
			},
		},
		{
			name: "RabbitMQ prefetch configuration",
			env: map[string]string{
				"ASYA_ACTOR_NAME":        "test-actor",
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
