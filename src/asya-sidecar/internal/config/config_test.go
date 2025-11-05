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
			os.Setenv(pair[0], pair[1])
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
				"ASYA_QUEUE_NAME":      "test-queue",
				"ASYA_RABBITMQ_URL":    "amqp://localhost:5672/",
				"ASYA_RUNTIME_TIMEOUT": "10m",
			},
			expectError: false,
			validate: func(t *testing.T, cfg *Config) {
				if cfg.QueueName != "test-queue" {
					t.Errorf("QueueName = %v, want test-queue", cfg.QueueName)
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
			name:        "missing queue name",
			env:         map[string]string{},
			expectError: true,
		},
		{
			name: "default values",
			env: map[string]string{
				"ASYA_QUEUE_NAME": "test-queue",
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
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Clear and set env
			os.Clearenv()
			for k, v := range tt.env {
				os.Setenv(k, v)
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
