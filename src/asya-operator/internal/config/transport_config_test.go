package config

import (
	"encoding/json"
	"os"
	"strings"
	"testing"

	corev1 "k8s.io/api/core/v1"
)

const (
	testUsername          = "guest"
	testTransportRabbitMQ = "rabbitmq"
	testTransportSQS      = "sqs"
)

func TestLoadTransportRegistry_EmptyConfig(t *testing.T) {
	_ = os.Setenv("ASYA_TRANSPORT_CONFIG", "")
	defer func() { _ = os.Unsetenv("ASYA_TRANSPORT_CONFIG") }()

	registry, err := LoadTransportRegistry()
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	if registry == nil {
		t.Fatal("Expected non-nil registry")
	}

	if registry.Transports == nil {
		t.Fatal("Expected non-nil Transports map")
	}

	if len(registry.Transports) != 0 {
		t.Errorf("Expected empty transports map, got %d items", len(registry.Transports))
	}
}

func TestLoadTransportRegistry_ValidRabbitMQConfig(t *testing.T) {
	configJSON := `{
		"transports": {
			"rabbitmq": {
				"type": "rabbitmq",
				"enabled": true,
				"config": {
					"host": "rabbitmq.default.svc.cluster.local",
					"port": 5672,
					"username": "` + testUsername + `"
				}
			}
		}
	}`

	_ = os.Setenv("ASYA_TRANSPORT_CONFIG", configJSON)
	defer func() { _ = os.Unsetenv("ASYA_TRANSPORT_CONFIG") }()

	registry, err := LoadTransportRegistry()
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	if len(registry.Transports) != 1 {
		t.Fatalf("Expected 1 transport, got %d", len(registry.Transports))
	}

	transport, ok := registry.Transports["rabbitmq"]
	if !ok {
		t.Fatal("Expected 'rabbitmq' transport to exist")
	}

	if transport.Type != testTransportRabbitMQ {
		t.Errorf("Expected type 'rabbitmq', got %s", transport.Type)
	}

	if !transport.Enabled {
		t.Error("Expected transport to be enabled")
	}

	config, ok := transport.Config.(*RabbitMQConfig)
	if !ok {
		t.Fatalf("Expected RabbitMQConfig type, got %T", transport.Config)
	}

	if config.Host != "rabbitmq.default.svc.cluster.local" {
		t.Errorf("Expected host 'rabbitmq.default.svc.cluster.local', got %s", config.Host)
	}

	if config.Port != 5672 {
		t.Errorf("Expected port 5672, got %d", config.Port)
	}

	if config.Username != testUsername {
		t.Errorf("Expected username %q, got %s", testUsername, config.Username)
	}
}

func TestLoadTransportRegistry_ValidSQSConfig(t *testing.T) {
	configJSON := `{
		"transports": {
			"sqs": {
				"type": "sqs",
				"enabled": true,
				"config": {
					"region": "us-east-1",
					"actorRoleArn": "arn:aws:iam::123456789012:role/asya-actor",
					"visibilityTimeout": 30,
					"waitTimeSeconds": 20
				}
			}
		}
	}`

	_ = os.Setenv("ASYA_TRANSPORT_CONFIG", configJSON)
	defer func() { _ = os.Unsetenv("ASYA_TRANSPORT_CONFIG") }()

	registry, err := LoadTransportRegistry()
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	transport, ok := registry.Transports["sqs"]
	if !ok {
		t.Fatal("Expected 'sqs' transport to exist")
	}

	config, ok := transport.Config.(*SQSConfig)
	if !ok {
		t.Fatalf("Expected SQSConfig type, got %T", transport.Config)
	}

	if config.Region != "us-east-1" {
		t.Errorf("Expected region 'us-east-1', got %s", config.Region)
	}

	if config.ActorRoleArn != "arn:aws:iam::123456789012:role/asya-actor" {
		t.Errorf("Expected actorRoleArn, got %s", config.ActorRoleArn)
	}

	if config.VisibilityTimeout != 30 {
		t.Errorf("Expected visibilityTimeout 30, got %d", config.VisibilityTimeout)
	}

	if config.WaitTimeSeconds != 20 {
		t.Errorf("Expected waitTimeSeconds 20, got %d", config.WaitTimeSeconds)
	}
}

func TestLoadTransportRegistry_MultipleTransports(t *testing.T) {
	configJSON := `{
		"transports": {
			"rabbitmq": {
				"type": "rabbitmq",
				"enabled": true,
				"config": {
					"host": "rabbitmq.default.svc.cluster.local",
					"port": 5672,
					"username": "` + testUsername + `"
				}
			},
			"sqs": {
				"type": "sqs",
				"enabled": true,
				"config": {
					"region": "us-east-1",
					"visibilityTimeout": 300,
					"waitTimeSeconds": 20
				}
			}
		}
	}`

	_ = os.Setenv("ASYA_TRANSPORT_CONFIG", configJSON)
	defer func() { _ = os.Unsetenv("ASYA_TRANSPORT_CONFIG") }()

	registry, err := LoadTransportRegistry()
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	if len(registry.Transports) != 2 {
		t.Fatalf("Expected 2 transports, got %d", len(registry.Transports))
	}

	if _, ok := registry.Transports["rabbitmq"]; !ok {
		t.Error("Expected 'rabbitmq' transport to exist")
	}

	if _, ok := registry.Transports["sqs"]; !ok {
		t.Error("Expected 'sqs' transport to exist")
	}
}

func TestLoadTransportRegistry_InvalidJSON(t *testing.T) {
	configJSON := `{"transports": invalid json`

	_ = os.Setenv("ASYA_TRANSPORT_CONFIG", configJSON)
	defer func() { _ = os.Unsetenv("ASYA_TRANSPORT_CONFIG") }()

	_, err := LoadTransportRegistry()
	if err == nil {
		t.Fatal("Expected error for invalid JSON, got nil")
	}
}

func TestLoadTransportRegistry_UnsupportedTransportType(t *testing.T) {
	configJSON := `{
		"transports": {
			"kafka": {
				"type": "kafka",
				"enabled": true,
				"config": {
					"brokers": ["localhost:9092"]
				}
			}
		}
	}`

	_ = os.Setenv("ASYA_TRANSPORT_CONFIG", configJSON)
	defer func() { _ = os.Unsetenv("ASYA_TRANSPORT_CONFIG") }()

	_, err := LoadTransportRegistry()
	if err == nil {
		t.Fatal("Expected error for unsupported transport type, got nil")
	}

	if err.Error() != "failed to parse config for transport 'kafka': unsupported transport type: kafka" {
		t.Errorf("Unexpected error message: %v", err)
	}
}

func TestLoadTransportRegistry_UnknownFieldAtTopLevel(t *testing.T) {
	configJSON := `{
		"transports": {
			"rabbitmq": {
				"type": "rabbitmq",
				"enabled": true,
				"config": {
					"host": "rabbitmq.svc",
					"port": 5672,
					"username": "guest"
				}
			}
		},
		"unknownTopLevelField": "should-fail"
	}`

	_ = os.Setenv("ASYA_TRANSPORT_CONFIG", configJSON)
	defer func() { _ = os.Unsetenv("ASYA_TRANSPORT_CONFIG") }()

	_, err := LoadTransportRegistry()
	if err == nil {
		t.Fatal("Expected error for unknown top-level field, got nil")
	}

	if !strings.Contains(err.Error(), "unknownTopLevelField") {
		t.Errorf("Expected error to mention 'unknownTopLevelField', got: %v", err)
	}
}

func TestLoadTransportRegistry_UnknownFieldInTransportConfig(t *testing.T) {
	configJSON := `{
		"transports": {
			"rabbitmq": {
				"type": "rabbitmq",
				"enabled": true,
				"unknownTransportField": "should-fail",
				"config": {
					"host": "rabbitmq.svc",
					"port": 5672,
					"username": "guest"
				}
			}
		}
	}`

	_ = os.Setenv("ASYA_TRANSPORT_CONFIG", configJSON)
	defer func() { _ = os.Unsetenv("ASYA_TRANSPORT_CONFIG") }()

	_, err := LoadTransportRegistry()
	if err == nil {
		t.Fatal("Expected error for unknown transport field, got nil")
	}

	if !strings.Contains(err.Error(), "unknownTransportField") {
		t.Errorf("Expected error to mention 'unknownTransportField', got: %v", err)
	}
}

func TestLoadTransportRegistry_UnknownFieldInRabbitMQConfig(t *testing.T) {
	configJSON := `{
		"transports": {
			"rabbitmq": {
				"type": "rabbitmq",
				"enabled": true,
				"config": {
					"host": "rabbitmq.svc",
					"port": 5672,
					"username": "guest",
					"unknownRabbitMQField": "should-fail"
				}
			}
		}
	}`

	_ = os.Setenv("ASYA_TRANSPORT_CONFIG", configJSON)
	defer func() { _ = os.Unsetenv("ASYA_TRANSPORT_CONFIG") }()

	_, err := LoadTransportRegistry()
	if err == nil {
		t.Fatal("Expected error for unknown RabbitMQ config field, got nil")
	}

	if !strings.Contains(err.Error(), "unknownRabbitMQField") {
		t.Errorf("Expected error to mention 'unknownRabbitMQField', got: %v", err)
	}
}

func TestLoadTransportRegistry_UnknownFieldInSQSConfig(t *testing.T) {
	configJSON := `{
		"transports": {
			"sqs": {
				"type": "sqs",
				"enabled": true,
				"config": {
					"region": "us-east-1",
					"visibilityTimeout": 300,
					"waitTimeSeconds": 20,
					"unknownSQSField": "should-fail"
				}
			}
		}
	}`

	_ = os.Setenv("ASYA_TRANSPORT_CONFIG", configJSON)
	defer func() { _ = os.Unsetenv("ASYA_TRANSPORT_CONFIG") }()

	_, err := LoadTransportRegistry()
	if err == nil {
		t.Fatal("Expected error for unknown SQS config field, got nil")
	}

	if !strings.Contains(err.Error(), "unknownSQSField") {
		t.Errorf("Expected error to mention 'unknownSQSField', got: %v", err)
	}
}

func TestLoadTransportRegistry_TypoInFieldName(t *testing.T) {
	tests := []struct {
		name        string
		configJSON  string
		expectedErr string
	}{
		{
			name: "typo in region field",
			configJSON: `{
				"transports": {
					"sqs": {
						"type": "sqs",
						"enabled": true,
						"config": {
							"reigon": "us-east-1",
							"visibilityTimeout": 300
						}
					}
				}
			}`,
			expectedErr: "reigon",
		},
		{
			name: "typo in host field",
			configJSON: `{
				"transports": {
					"rabbitmq": {
						"type": "rabbitmq",
						"enabled": true,
						"config": {
							"hsot": "rabbitmq.svc",
							"port": 5672
						}
					}
				}
			}`,
			expectedErr: "hsot",
		},
		{
			name: "typo in visibilityTimeout field",
			configJSON: `{
				"transports": {
					"sqs": {
						"type": "sqs",
						"enabled": true,
						"config": {
							"region": "us-east-1",
							"visibiltyTimeout": 300
						}
					}
				}
			}`,
			expectedErr: "visibiltyTimeout",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_ = os.Setenv("ASYA_TRANSPORT_CONFIG", tt.configJSON)
			defer func() { _ = os.Unsetenv("ASYA_TRANSPORT_CONFIG") }()

			_, err := LoadTransportRegistry()
			if err == nil {
				t.Fatal("Expected error for field typo, got nil")
			}

			if !strings.Contains(err.Error(), tt.expectedErr) {
				t.Errorf("Expected error to mention '%s', got: %v", tt.expectedErr, err)
			}
		})
	}
}

func TestParseTransportConfig_RabbitMQ(t *testing.T) {
	raw := &rawTransportConfig{
		Type:    "rabbitmq",
		Enabled: true,
		Config: map[string]interface{}{
			"host":     "localhost",
			"port":     float64(5672),
			"username": "user",
		},
	}

	config, err := parseTransportConfig(raw)
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	if config.Type != testTransportRabbitMQ {
		t.Errorf("Expected type 'rabbitmq', got %s", config.Type)
	}

	if !config.Enabled {
		t.Error("Expected enabled to be true")
	}

	rmqConfig, ok := config.Config.(*RabbitMQConfig)
	if !ok {
		t.Fatalf("Expected RabbitMQConfig, got %T", config.Config)
	}

	if rmqConfig.Host != "localhost" {
		t.Errorf("Expected host 'localhost', got %s", rmqConfig.Host)
	}

	if rmqConfig.Port != 5672 {
		t.Errorf("Expected port 5672, got %d", rmqConfig.Port)
	}
}

func TestParseTransportConfig_SQS(t *testing.T) {
	raw := &rawTransportConfig{
		Type:    "sqs",
		Enabled: false,
		Config: map[string]interface{}{
			"region":            "eu-west-1",
			"visibilityTimeout": float64(300),
			"waitTimeSeconds":   float64(20),
		},
	}

	config, err := parseTransportConfig(raw)
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	if config.Type != testTransportSQS {
		t.Errorf("Expected type 'sqs', got %s", config.Type)
	}

	if config.Enabled {
		t.Error("Expected enabled to be false")
	}

	sqsConfig, ok := config.Config.(*SQSConfig)
	if !ok {
		t.Fatalf("Expected SQSConfig, got %T", config.Config)
	}

	if sqsConfig.Region != "eu-west-1" {
		t.Errorf("Expected region 'eu-west-1', got %s", sqsConfig.Region)
	}
}

func TestParseTransportConfig_UnsupportedType(t *testing.T) {
	raw := &rawTransportConfig{
		Type:    "unknown",
		Enabled: true,
		Config:  map[string]interface{}{},
	}

	_, err := parseTransportConfig(raw)
	if err == nil {
		t.Fatal("Expected error for unsupported type, got nil")
	}
}

func TestGetTransport_Success(t *testing.T) {
	registry := &TransportRegistry{
		Transports: map[string]*TransportConfig{
			"rabbitmq": {
				Type:    "rabbitmq",
				Enabled: true,
				Config:  &RabbitMQConfig{Host: "localhost", Port: 5672},
			},
		},
	}

	transport, err := registry.GetTransport("rabbitmq")
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	if transport.Type != testTransportRabbitMQ {
		t.Errorf("Expected type 'rabbitmq', got %s", transport.Type)
	}
}

func TestGetTransport_NotFound(t *testing.T) {
	registry := &TransportRegistry{
		Transports: map[string]*TransportConfig{},
	}

	_, err := registry.GetTransport("nonexistent")
	if err == nil {
		t.Fatal("Expected error for nonexistent transport, got nil")
	}

	expectedMsg := "transport 'nonexistent' not found in operator configuration"
	if err.Error() != expectedMsg {
		t.Errorf("Expected error '%s', got '%s'", expectedMsg, err.Error())
	}
}

func TestGetTransport_Disabled(t *testing.T) {
	registry := &TransportRegistry{
		Transports: map[string]*TransportConfig{
			"rabbitmq": {
				Type:    "rabbitmq",
				Enabled: false,
				Config:  &RabbitMQConfig{},
			},
		},
	}

	_, err := registry.GetTransport("rabbitmq")
	if err == nil {
		t.Fatal("Expected error for disabled transport, got nil")
	}

	expectedMsg := "transport 'rabbitmq' is disabled in operator configuration"
	if err.Error() != expectedMsg {
		t.Errorf("Expected error '%s', got '%s'", expectedMsg, err.Error())
	}
}

func TestBuildEnvVars_RabbitMQ(t *testing.T) {
	config := &TransportConfig{
		Type:    "rabbitmq",
		Enabled: true,
		Config: &RabbitMQConfig{
			Host:     "rabbitmq.svc",
			Port:     5672,
			Username: "admin",
		},
	}

	env, err := config.BuildEnvVars()
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	expectedEnv := map[string]string{
		"ASYA_TRANSPORT":         "rabbitmq",
		"ASYA_RABBITMQ_HOST":     "rabbitmq.svc",
		"ASYA_RABBITMQ_PORT":     "5672",
		"ASYA_RABBITMQ_USERNAME": "admin",
	}

	for key, expectedValue := range expectedEnv {
		found := false
		for _, e := range env {
			if e.Name == key && e.Value == expectedValue {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("Expected env var %s=%s not found", key, expectedValue)
		}
	}
}

func TestBuildEnvVars_RabbitMQWithSecret(t *testing.T) {
	config := &TransportConfig{
		Type:    "rabbitmq",
		Enabled: true,
		Config: &RabbitMQConfig{
			Host:     "rabbitmq.svc",
			Port:     5672,
			Username: "admin",
			PasswordSecretRef: &corev1.SecretKeySelector{
				LocalObjectReference: corev1.LocalObjectReference{Name: "rabbitmq-secret"},
				Key:                  "password",
			},
		},
	}

	env, err := config.BuildEnvVars()
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	foundPasswordEnv := false
	for _, e := range env {
		if e.Name == "ASYA_RABBITMQ_PASSWORD" {
			foundPasswordEnv = true
			if e.ValueFrom == nil || e.ValueFrom.SecretKeyRef == nil {
				t.Error("Expected ValueFrom.SecretKeyRef to be set")
			} else {
				if e.ValueFrom.SecretKeyRef.Name != "rabbitmq-secret" {
					t.Errorf("Expected secret name 'rabbitmq-secret', got %s", e.ValueFrom.SecretKeyRef.Name)
				}
				if e.ValueFrom.SecretKeyRef.Key != "password" {
					t.Errorf("Expected secret key 'password', got %s", e.ValueFrom.SecretKeyRef.Key)
				}
			}
		}
	}

	if !foundPasswordEnv {
		t.Error("Expected ASYA_RABBITMQ_PASSWORD env var with secret reference")
	}
}

func TestBuildEnvVars_SQS(t *testing.T) {
	config := &TransportConfig{
		Type:    "sqs",
		Enabled: true,
		Config: &SQSConfig{
			Region: "us-west-2",
		},
	}

	env, err := config.BuildEnvVars()
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	expectedEnv := map[string]string{
		"ASYA_TRANSPORT":  "sqs",
		"ASYA_AWS_REGION": "us-west-2",
	}

	for key, expectedValue := range expectedEnv {
		found := false
		for _, e := range env {
			if e.Name == key && e.Value == expectedValue {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("Expected env var %s=%s not found", key, expectedValue)
		}
	}
}

func TestBuildEnvVars_InvalidConfigType(t *testing.T) {
	config := &TransportConfig{
		Type:    "rabbitmq",
		Enabled: true,
		Config:  &SQSConfig{},
	}

	_, err := config.BuildEnvVars()
	if err == nil {
		t.Fatal("Expected error for invalid config type, got nil")
	}

	expectedMsg := "invalid config type for RabbitMQ transport"
	if err.Error() != expectedMsg {
		t.Errorf("Expected error '%s', got '%s'", expectedMsg, err.Error())
	}
}

func TestRabbitMQConfig_ImplementsInterface(t *testing.T) {
	var _ TransportSpecificConfig = (*RabbitMQConfig)(nil)
}

func TestSQSConfig_ImplementsInterface(t *testing.T) {
	var _ TransportSpecificConfig = (*SQSConfig)(nil)
}

func TestLoadTransportRegistry_RabbitMQWithPasswordSecret(t *testing.T) {
	passwordSecretRef := map[string]interface{}{
		"name": "rabbitmq-secret",
		"key":  "password",
	}
	configJSON := map[string]interface{}{
		"transports": map[string]interface{}{
			"rabbitmq": map[string]interface{}{
				"type":    "rabbitmq",
				"enabled": true,
				"config": map[string]interface{}{
					"host":              "rabbitmq.svc",
					"port":              5672,
					"username":          "admin",
					"passwordSecretRef": passwordSecretRef,
				},
			},
		},
	}

	configBytes, _ := json.Marshal(configJSON)
	_ = os.Setenv("ASYA_TRANSPORT_CONFIG", string(configBytes))
	defer func() { _ = os.Unsetenv("ASYA_TRANSPORT_CONFIG") }()

	registry, err := LoadTransportRegistry()
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	transport := registry.Transports["rabbitmq"]
	config, ok := transport.Config.(*RabbitMQConfig)
	if !ok {
		t.Fatalf("Expected RabbitMQConfig, got %T", transport.Config)
	}

	if config.PasswordSecretRef == nil {
		t.Fatal("Expected PasswordSecretRef to be set")
	}

	if config.PasswordSecretRef.Name != "rabbitmq-secret" {
		t.Errorf("Expected secret name 'rabbitmq-secret', got %s", config.PasswordSecretRef.Name)
	}

	if config.PasswordSecretRef.Key != "password" {
		t.Errorf("Expected secret key 'password', got %s", config.PasswordSecretRef.Key)
	}
}

func TestLoadTransportRegistry_QueueManagementDefaults(t *testing.T) {
	configJSON := `{
		"transports": {
			"rabbitmq": {
				"type": "rabbitmq",
				"enabled": true,
				"config": {
					"host": "rabbitmq.default.svc.cluster.local",
					"port": 5672,
					"username": "guest"
				}
			}
		}
	}`

	_ = os.Setenv("ASYA_TRANSPORT_CONFIG", configJSON)
	defer func() { _ = os.Unsetenv("ASYA_TRANSPORT_CONFIG") }()

	registry, err := LoadTransportRegistry()
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	transport := registry.Transports["rabbitmq"]
	config, ok := transport.Config.(*RabbitMQConfig)
	if !ok {
		t.Fatalf("Expected RabbitMQConfig, got %T", transport.Config)
	}

	if !config.Queues.AutoCreate {
		t.Error("Expected AutoCreate default to be true")
	}

	if config.Queues.ForceRecreate {
		t.Error("Expected ForceRecreate default to be false")
	}
}

func TestLoadTransportRegistry_QueueManagementExplicit(t *testing.T) {
	configJSON := `{
		"transports": {
			"rabbitmq": {
				"type": "rabbitmq",
				"enabled": true,
				"config": {
					"host": "rabbitmq.default.svc.cluster.local",
					"port": 5672,
					"username": "guest",
					"queues": {
						"autoCreate": false,
						"forceRecreate": true
					}
				}
			}
		}
	}`

	_ = os.Setenv("ASYA_TRANSPORT_CONFIG", configJSON)
	defer func() { _ = os.Unsetenv("ASYA_TRANSPORT_CONFIG") }()

	registry, err := LoadTransportRegistry()
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	transport := registry.Transports["rabbitmq"]
	config, ok := transport.Config.(*RabbitMQConfig)
	if !ok {
		t.Fatalf("Expected RabbitMQConfig, got %T", transport.Config)
	}

	if config.Queues.AutoCreate {
		t.Error("Expected AutoCreate to be false")
	}

	if !config.Queues.ForceRecreate {
		t.Error("Expected ForceRecreate to be true")
	}
}

func TestLoadTransportRegistry_SQSQueueManagement(t *testing.T) {
	configJSON := `{
		"transports": {
			"sqs": {
				"type": "sqs",
				"enabled": true,
				"config": {
					"region": "us-east-1",
					"visibilityTimeout": 300,
					"waitTimeSeconds": 20,
					"queues": {
						"autoCreate": true,
						"forceRecreate": false
					}
				}
			}
		}
	}`

	_ = os.Setenv("ASYA_TRANSPORT_CONFIG", configJSON)
	defer func() { _ = os.Unsetenv("ASYA_TRANSPORT_CONFIG") }()

	registry, err := LoadTransportRegistry()
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	transport := registry.Transports["sqs"]
	config, ok := transport.Config.(*SQSConfig)
	if !ok {
		t.Fatalf("Expected SQSConfig, got %T", transport.Config)
	}

	if !config.Queues.AutoCreate {
		t.Error("Expected AutoCreate to be true")
	}

	if config.Queues.ForceRecreate {
		t.Error("Expected ForceRecreate to be false")
	}
}

func TestBuildEnvVars_RabbitMQQueueAutoCreate(t *testing.T) {
	config := &TransportConfig{
		Type:    "rabbitmq",
		Enabled: true,
		Config: &RabbitMQConfig{
			Host:     "rabbitmq.svc",
			Port:     5672,
			Username: "admin",
			Queues: QueueManagementConfig{
				AutoCreate:    true,
				ForceRecreate: false,
			},
		},
	}

	env, err := config.BuildEnvVars()
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	found := false
	for _, e := range env {
		if e.Name == "ASYA_QUEUE_AUTO_CREATE" {
			found = true
			if e.Value != "true" {
				t.Errorf("Expected ASYA_QUEUE_AUTO_CREATE=true, got %s", e.Value)
			}
		}
	}

	if !found {
		t.Error("Expected ASYA_QUEUE_AUTO_CREATE env var not found")
	}
}

func TestBuildEnvVars_RabbitMQQueueAutoCreateDisabled(t *testing.T) {
	config := &TransportConfig{
		Type:    "rabbitmq",
		Enabled: true,
		Config: &RabbitMQConfig{
			Host:     "rabbitmq.svc",
			Port:     5672,
			Username: "admin",
			Queues: QueueManagementConfig{
				AutoCreate:    false,
				ForceRecreate: false,
			},
		},
	}

	env, err := config.BuildEnvVars()
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	found := false
	for _, e := range env {
		if e.Name == "ASYA_QUEUE_AUTO_CREATE" {
			found = true
			if e.Value != "false" {
				t.Errorf("Expected ASYA_QUEUE_AUTO_CREATE=false, got %s", e.Value)
			}
		}
	}

	if !found {
		t.Error("Expected ASYA_QUEUE_AUTO_CREATE env var not found")
	}
}

func TestLoadTransportRegistry_RabbitMQDLQDefaults(t *testing.T) {
	configJSON := `{
		"transports": {
			"rabbitmq": {
				"type": "rabbitmq",
				"enabled": true,
				"config": {
					"host": "rabbitmq.default.svc.cluster.local",
					"port": 5672,
					"username": "guest"
				}
			}
		}
	}`

	_ = os.Setenv("ASYA_TRANSPORT_CONFIG", configJSON)
	defer func() { _ = os.Unsetenv("ASYA_TRANSPORT_CONFIG") }()

	registry, err := LoadTransportRegistry()
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	transport := registry.Transports["rabbitmq"]
	config, ok := transport.Config.(*RabbitMQConfig)
	if !ok {
		t.Fatalf("Expected RabbitMQConfig, got %T", transport.Config)
	}

	if config.Queues.DLQ.MaxRetryCount != 3 {
		t.Errorf("Expected DLQ MaxRetryCount default to be 3, got %d", config.Queues.DLQ.MaxRetryCount)
	}

	if config.Queues.DLQ.Enabled {
		t.Error("Expected DLQ Enabled default to be false")
	}
}

func TestLoadTransportRegistry_RabbitMQDLQExplicit(t *testing.T) {
	configJSON := `{
		"transports": {
			"rabbitmq": {
				"type": "rabbitmq",
				"enabled": true,
				"config": {
					"host": "rabbitmq.default.svc.cluster.local",
					"port": 5672,
					"username": "guest",
					"queues": {
						"dlq": {
							"enabled": true,
							"maxRetryCount": 5
						}
					}
				}
			}
		}
	}`

	_ = os.Setenv("ASYA_TRANSPORT_CONFIG", configJSON)
	defer func() { _ = os.Unsetenv("ASYA_TRANSPORT_CONFIG") }()

	registry, err := LoadTransportRegistry()
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	transport := registry.Transports["rabbitmq"]
	config, ok := transport.Config.(*RabbitMQConfig)
	if !ok {
		t.Fatalf("Expected RabbitMQConfig, got %T", transport.Config)
	}

	if !config.Queues.DLQ.Enabled {
		t.Error("Expected DLQ Enabled to be true")
	}

	if config.Queues.DLQ.MaxRetryCount != 5 {
		t.Errorf("Expected DLQ MaxRetryCount to be 5, got %d", config.Queues.DLQ.MaxRetryCount)
	}
}

func TestLoadTransportRegistry_SQSDLQDefaults(t *testing.T) {
	configJSON := `{
		"transports": {
			"sqs": {
				"type": "sqs",
				"enabled": true,
				"config": {
					"region": "us-east-1",
					"visibilityTimeout": 300,
					"waitTimeSeconds": 20
				}
			}
		}
	}`

	_ = os.Setenv("ASYA_TRANSPORT_CONFIG", configJSON)
	defer func() { _ = os.Unsetenv("ASYA_TRANSPORT_CONFIG") }()

	registry, err := LoadTransportRegistry()
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	transport := registry.Transports["sqs"]
	config, ok := transport.Config.(*SQSConfig)
	if !ok {
		t.Fatalf("Expected SQSConfig, got %T", transport.Config)
	}

	if config.Queues.DLQ.MaxRetryCount != 3 {
		t.Errorf("Expected DLQ MaxRetryCount default to be 3, got %d", config.Queues.DLQ.MaxRetryCount)
	}

	if config.Queues.DLQ.RetentionDays != 14 {
		t.Errorf("Expected DLQ RetentionDays default to be 14, got %d", config.Queues.DLQ.RetentionDays)
	}

	if config.Queues.DLQ.Enabled {
		t.Error("Expected DLQ Enabled default to be false")
	}
}

func TestLoadTransportRegistry_SQSDLQExplicit(t *testing.T) {
	configJSON := `{
		"transports": {
			"sqs": {
				"type": "sqs",
				"enabled": true,
				"config": {
					"region": "us-east-1",
					"visibilityTimeout": 300,
					"waitTimeSeconds": 20,
					"queues": {
						"dlq": {
							"enabled": true,
							"maxRetryCount": 5,
							"retentionDays": 7
						}
					}
				}
			}
		}
	}`

	_ = os.Setenv("ASYA_TRANSPORT_CONFIG", configJSON)
	defer func() { _ = os.Unsetenv("ASYA_TRANSPORT_CONFIG") }()

	registry, err := LoadTransportRegistry()
	if err != nil {
		t.Fatalf("Expected no error, got %v", err)
	}

	transport := registry.Transports["sqs"]
	config, ok := transport.Config.(*SQSConfig)
	if !ok {
		t.Fatalf("Expected SQSConfig, got %T", transport.Config)
	}

	if !config.Queues.DLQ.Enabled {
		t.Error("Expected DLQ Enabled to be true")
	}

	if config.Queues.DLQ.MaxRetryCount != 5 {
		t.Errorf("Expected DLQ MaxRetryCount to be 5, got %d", config.Queues.DLQ.MaxRetryCount)
	}

	if config.Queues.DLQ.RetentionDays != 7 {
		t.Errorf("Expected DLQ RetentionDays to be 7, got %d", config.Queues.DLQ.RetentionDays)
	}
}
