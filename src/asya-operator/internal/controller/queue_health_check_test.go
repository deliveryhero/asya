package controller

import (
	"os"
	"testing"
	"time"
)

func TestIsQueueManagementEnabled(t *testing.T) {
	tests := []struct {
		name     string
		envValue string
		expected bool
	}{
		{
			name:     "queue management enabled by default",
			envValue: "",
			expected: true,
		},
		{
			name:     "queue management explicitly disabled",
			envValue: "true",
			expected: false,
		},
		{
			name:     "queue management enabled with false value",
			envValue: "false",
			expected: true,
		},
		{
			name:     "queue management enabled with other value",
			envValue: "1",
			expected: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if tt.envValue != "" {
				t.Setenv("ASYA_DISABLE_QUEUE_MANAGEMENT", tt.envValue)
			}

			result := isQueueManagementEnabled()
			if result != tt.expected {
				t.Errorf("Expected %v, got %v", tt.expected, result)
			}
		})
	}
}

func TestQueueHealthCheckInterval(t *testing.T) {
	tests := []struct {
		name             string
		envValue         string
		expectedInterval time.Duration
	}{
		{
			name:             "default interval when env not set",
			envValue:         "",
			expectedInterval: 5 * time.Minute,
		},
		{
			name:             "custom interval from env",
			envValue:         "2m",
			expectedInterval: 2 * time.Minute,
		},
		{
			name:             "custom interval seconds",
			envValue:         "30s",
			expectedInterval: 30 * time.Second,
		},
		{
			name:             "invalid env uses default",
			envValue:         "invalid",
			expectedInterval: 5 * time.Minute,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if tt.envValue != "" {
				t.Setenv("ASYA_QUEUE_HEALTH_CHECK_INTERVAL", tt.envValue)
			}

			interval := defaultQueueHealthCheckInterval
			if envInterval := os.Getenv("ASYA_QUEUE_HEALTH_CHECK_INTERVAL"); envInterval != "" {
				if parsedInterval, err := time.ParseDuration(envInterval); err == nil {
					interval = parsedInterval
				}
			}

			if interval != tt.expectedInterval {
				t.Errorf("Expected interval %v, got %v", tt.expectedInterval, interval)
			}
		})
	}
}
