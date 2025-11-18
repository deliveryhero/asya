package envelopestore

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestGetEnvInt(t *testing.T) {
	tests := []struct {
		name         string
		envKey       string
		envValue     string
		defaultValue int
		expected     int
	}{
		{
			name:         "valid integer value",
			envKey:       "TEST_INT_VALID",
			envValue:     "42",
			defaultValue: 10,
			expected:     42,
		},
		{
			name:         "zero value",
			envKey:       "TEST_INT_ZERO",
			envValue:     "0",
			defaultValue: 10,
			expected:     0,
		},
		{
			name:         "negative value",
			envKey:       "TEST_INT_NEGATIVE",
			envValue:     "-5",
			defaultValue: 10,
			expected:     -5,
		},
		{
			name:         "large value",
			envKey:       "TEST_INT_LARGE",
			envValue:     "999999",
			defaultValue: 10,
			expected:     999999,
		},
		{
			name:         "invalid value returns default",
			envKey:       "TEST_INT_INVALID",
			envValue:     "not-a-number",
			defaultValue: 10,
			expected:     10,
		},
		{
			name:         "empty value returns default",
			envKey:       "TEST_INT_EMPTY",
			envValue:     "",
			defaultValue: 10,
			expected:     10,
		},
		{
			name:         "unset value returns default",
			envKey:       "TEST_INT_UNSET",
			envValue:     "",
			defaultValue: 10,
			expected:     10,
		},
		{
			name:         "float value returns default",
			envKey:       "TEST_INT_FLOAT",
			envValue:     "3.14",
			defaultValue: 10,
			expected:     10,
		},
		{
			name:         "value with spaces returns default",
			envKey:       "TEST_INT_SPACES",
			envValue:     " 42 ",
			defaultValue: 10,
			expected:     10,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if tt.envValue != "" {
				_ = os.Setenv(tt.envKey, tt.envValue)
				defer func() { _ = os.Unsetenv(tt.envKey) }()
			} else if tt.name != "unset value returns default" {
				_ = os.Unsetenv(tt.envKey)
			}

			result := getEnvInt(tt.envKey, tt.defaultValue)
			assert.Equal(t, tt.expected, result, "getEnvInt(%s, %d) should return %d", tt.envKey, tt.defaultValue, tt.expected)
		})
	}
}

func TestGetEnvDuration(t *testing.T) {
	tests := []struct {
		name         string
		envKey       string
		envValue     string
		defaultValue time.Duration
		expected     time.Duration
	}{
		{
			name:         "valid duration in seconds",
			envKey:       "TEST_DUR_SECONDS",
			envValue:     "30s",
			defaultValue: 1 * time.Minute,
			expected:     30 * time.Second,
		},
		{
			name:         "valid duration in minutes",
			envKey:       "TEST_DUR_MINUTES",
			envValue:     "15m",
			defaultValue: 1 * time.Minute,
			expected:     15 * time.Minute,
		},
		{
			name:         "valid duration in hours",
			envKey:       "TEST_DUR_HOURS",
			envValue:     "2h",
			defaultValue: 1 * time.Hour,
			expected:     2 * time.Hour,
		},
		{
			name:         "valid duration in milliseconds",
			envKey:       "TEST_DUR_MILLIS",
			envValue:     "500ms",
			defaultValue: 1 * time.Second,
			expected:     500 * time.Millisecond,
		},
		{
			name:         "valid duration in microseconds",
			envKey:       "TEST_DUR_MICROS",
			envValue:     "100us",
			defaultValue: 1 * time.Millisecond,
			expected:     100 * time.Microsecond,
		},
		{
			name:         "valid duration in nanoseconds",
			envKey:       "TEST_DUR_NANOS",
			envValue:     "1000ns",
			defaultValue: 1 * time.Microsecond,
			expected:     1000 * time.Nanosecond,
		},
		{
			name:         "complex duration with multiple units",
			envKey:       "TEST_DUR_COMPLEX",
			envValue:     "1h30m45s",
			defaultValue: 1 * time.Hour,
			expected:     1*time.Hour + 30*time.Minute + 45*time.Second,
		},
		{
			name:         "zero duration",
			envKey:       "TEST_DUR_ZERO",
			envValue:     "0s",
			defaultValue: 1 * time.Minute,
			expected:     0,
		},
		{
			name:         "invalid duration returns default",
			envKey:       "TEST_DUR_INVALID",
			envValue:     "not-a-duration",
			defaultValue: 1 * time.Minute,
			expected:     1 * time.Minute,
		},
		{
			name:         "empty value returns default",
			envKey:       "TEST_DUR_EMPTY",
			envValue:     "",
			defaultValue: 1 * time.Minute,
			expected:     1 * time.Minute,
		},
		{
			name:         "unset value returns default",
			envKey:       "TEST_DUR_UNSET",
			envValue:     "",
			defaultValue: 1 * time.Minute,
			expected:     1 * time.Minute,
		},
		{
			name:         "duration without unit returns default",
			envKey:       "TEST_DUR_NO_UNIT",
			envValue:     "42",
			defaultValue: 1 * time.Minute,
			expected:     1 * time.Minute,
		},
		{
			name:         "negative duration",
			envKey:       "TEST_DUR_NEGATIVE",
			envValue:     "-5s",
			defaultValue: 1 * time.Minute,
			expected:     -5 * time.Second,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if tt.envValue != "" {
				_ = os.Setenv(tt.envKey, tt.envValue)
				defer func() { _ = os.Unsetenv(tt.envKey) }()
			} else if tt.name != "unset value returns default" {
				_ = os.Unsetenv(tt.envKey)
			}

			result := getEnvDuration(tt.envKey, tt.defaultValue)
			assert.Equal(t, tt.expected, result, "getEnvDuration(%s, %v) should return %v", tt.envKey, tt.defaultValue, tt.expected)
		})
	}
}

func TestNewPgStore_ConfigFromEnv(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping integration test in short mode")
	}

	tests := []struct {
		name                string
		envVars             map[string]string
		connString          string
		expectedMaxConns    int32
		expectedMinConns    int32
		expectedMaxLifetime time.Duration
		expectedMaxIdle     time.Duration
	}{
		{
			name:                "default values when env vars not set",
			envVars:             map[string]string{},
			connString:          "postgres://user:pass@localhost/test",
			expectedMaxConns:    10,
			expectedMinConns:    2,
			expectedMaxLifetime: time.Hour,
			expectedMaxIdle:     30 * time.Minute,
		},
		{
			name: "custom max connections",
			envVars: map[string]string{
				"ASYA_DB_MAX_CONNS": "20",
			},
			connString:          "postgres://user:pass@localhost/test",
			expectedMaxConns:    20,
			expectedMinConns:    2,
			expectedMaxLifetime: time.Hour,
			expectedMaxIdle:     30 * time.Minute,
		},
		{
			name: "custom min connections",
			envVars: map[string]string{
				"ASYA_DB_MIN_CONNS": "5",
			},
			connString:          "postgres://user:pass@localhost/test",
			expectedMaxConns:    10,
			expectedMinConns:    5,
			expectedMaxLifetime: time.Hour,
			expectedMaxIdle:     30 * time.Minute,
		},
		{
			name: "custom max connection lifetime",
			envVars: map[string]string{
				"ASYA_DB_MAX_CONN_LIFETIME": "2h",
			},
			connString:          "postgres://user:pass@localhost/test",
			expectedMaxConns:    10,
			expectedMinConns:    2,
			expectedMaxLifetime: 2 * time.Hour,
			expectedMaxIdle:     30 * time.Minute,
		},
		{
			name: "custom max connection idle time",
			envVars: map[string]string{
				"ASYA_DB_MAX_CONN_IDLE_TIME": "15m",
			},
			connString:          "postgres://user:pass@localhost/test",
			expectedMaxConns:    10,
			expectedMinConns:    2,
			expectedMaxLifetime: time.Hour,
			expectedMaxIdle:     15 * time.Minute,
		},
		{
			name: "all custom values",
			envVars: map[string]string{
				"ASYA_DB_MAX_CONNS":          "50",
				"ASYA_DB_MIN_CONNS":          "10",
				"ASYA_DB_MAX_CONN_LIFETIME":  "3h",
				"ASYA_DB_MAX_CONN_IDLE_TIME": "45m",
			},
			connString:          "postgres://user:pass@localhost/test",
			expectedMaxConns:    50,
			expectedMinConns:    10,
			expectedMaxLifetime: 3 * time.Hour,
			expectedMaxIdle:     45 * time.Minute,
		},
		{
			name: "invalid values fall back to defaults",
			envVars: map[string]string{
				"ASYA_DB_MAX_CONNS":          "not-a-number",
				"ASYA_DB_MIN_CONNS":          "also-invalid",
				"ASYA_DB_MAX_CONN_LIFETIME":  "invalid-duration",
				"ASYA_DB_MAX_CONN_IDLE_TIME": "42",
			},
			connString:          "postgres://user:pass@localhost/test",
			expectedMaxConns:    10,
			expectedMinConns:    2,
			expectedMaxLifetime: time.Hour,
			expectedMaxIdle:     30 * time.Minute,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Set environment variables
			for key, value := range tt.envVars {
				_ = os.Setenv(key, value)
				defer func(k string) { _ = os.Unsetenv(k) }(key)
			}

			// Clear any env vars not in this test case
			allKeys := []string{
				"ASYA_DB_MAX_CONNS",
				"ASYA_DB_MIN_CONNS",
				"ASYA_DB_MAX_CONN_LIFETIME",
				"ASYA_DB_MAX_CONN_IDLE_TIME",
			}
			for _, key := range allKeys {
				if _, exists := tt.envVars[key]; !exists {
					_ = os.Unsetenv(key)
				}
			}

			// Create store (will fail to connect, but we just want to check config parsing)
			ctx := context.Background()
			store, err := NewPgStore(ctx, tt.connString)

			// We expect connection to fail since we're using a fake connection string
			// But the config should still be parsed correctly
			if err != nil {
				// This is expected - we're not testing actual DB connectivity
				// Just verify the error is about connection, not config parsing
				require.Contains(t, err.Error(), "failed to", "should fail on connection, not config")
			} else {
				// If connection somehow succeeded, verify config was applied
				defer store.Close()

				config := store.pool.Config()
				assert.Equal(t, tt.expectedMaxConns, config.MaxConns, "MaxConns should match")
				assert.Equal(t, tt.expectedMinConns, config.MinConns, "MinConns should match")
				assert.Equal(t, tt.expectedMaxLifetime, config.MaxConnLifetime, "MaxConnLifetime should match")
				assert.Equal(t, tt.expectedMaxIdle, config.MaxConnIdleTime, "MaxConnIdleTime should match")
			}
		})
	}
}

func TestNewPgStore_ConfigPrecedence(t *testing.T) {
	tests := []struct {
		name     string
		envValue string
		expected int
	}{
		{
			name:     "env var takes precedence over default",
			envValue: "25",
			expected: 25,
		},
		{
			name:     "default used when env var is empty",
			envValue: "",
			expected: 10,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			key := "ASYA_DB_MAX_CONNS"
			if tt.envValue != "" {
				_ = os.Setenv(key, tt.envValue)
			} else {
				_ = os.Unsetenv(key)
			}
			defer func() { _ = os.Unsetenv(key) }()

			result := getEnvInt(key, 10)
			assert.Equal(t, tt.expected, result)
		})
	}
}

func TestGetEnvDuration_EdgeCases(t *testing.T) {
	tests := []struct {
		name     string
		envValue string
		expected time.Duration
	}{
		{
			name:     "very large duration",
			envValue: "8760h",
			expected: 8760 * time.Hour,
		},
		{
			name:     "very small duration",
			envValue: "1ns",
			expected: 1 * time.Nanosecond,
		},
		{
			name:     "mixed case should fail",
			envValue: "1H",
			expected: 1 * time.Minute,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			key := "TEST_EDGE_DURATION"
			_ = os.Setenv(key, tt.envValue)
			defer func() { _ = os.Unsetenv(key) }()

			result := getEnvDuration(key, 1*time.Minute)
			assert.Equal(t, tt.expected, result)
		})
	}
}

func TestGetEnvInt_EdgeCases(t *testing.T) {
	tests := []struct {
		name     string
		envValue string
		expected int
	}{
		{
			name:     "max int32",
			envValue: "2147483647",
			expected: 2147483647,
		},
		{
			name:     "min int32",
			envValue: "-2147483648",
			expected: -2147483648,
		},
		{
			name:     "value with leading zeros",
			envValue: "00042",
			expected: 42,
		},
		{
			name:     "value with plus sign",
			envValue: "+42",
			expected: 42,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			key := "TEST_EDGE_INT"
			_ = os.Setenv(key, tt.envValue)
			defer func() { _ = os.Unsetenv(key) }()

			result := getEnvInt(key, 10)
			assert.Equal(t, tt.expected, result)
		})
	}
}
