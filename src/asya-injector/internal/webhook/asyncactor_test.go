package webhook

import (
	"testing"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

func TestIsAsyncActorReady(t *testing.T) {
	tests := []struct {
		name      string
		asyncActor *unstructured.Unstructured
		expected  bool
		wantErr   bool
	}{
		{
			name: "no status",
			asyncActor: &unstructured.Unstructured{
				Object: map[string]interface{}{
					"spec": map[string]interface{}{},
				},
			},
			expected: false,
			wantErr:  false,
		},
		{
			name: "empty conditions",
			asyncActor: &unstructured.Unstructured{
				Object: map[string]interface{}{
					"status": map[string]interface{}{
						"conditions": []interface{}{},
					},
				},
			},
			expected: false,
			wantErr:  false,
		},
		{
			name: "Ready=True",
			asyncActor: &unstructured.Unstructured{
				Object: map[string]interface{}{
					"status": map[string]interface{}{
						"conditions": []interface{}{
							map[string]interface{}{
								"type":   "Ready",
								"status": "True",
							},
						},
					},
				},
			},
			expected: true,
			wantErr:  false,
		},
		{
			name: "Ready=False",
			asyncActor: &unstructured.Unstructured{
				Object: map[string]interface{}{
					"status": map[string]interface{}{
						"conditions": []interface{}{
							map[string]interface{}{
								"type":   "Ready",
								"status": "False",
							},
						},
					},
				},
			},
			expected: false,
			wantErr:  false,
		},
		{
			name: "Synced=True (Crossplane)",
			asyncActor: &unstructured.Unstructured{
				Object: map[string]interface{}{
					"status": map[string]interface{}{
						"conditions": []interface{}{
							map[string]interface{}{
								"type":   "Synced",
								"status": "True",
							},
						},
					},
				},
			},
			expected: true,
			wantErr:  false,
		},
		{
			name: "multiple conditions, Ready is True",
			asyncActor: &unstructured.Unstructured{
				Object: map[string]interface{}{
					"status": map[string]interface{}{
						"conditions": []interface{}{
							map[string]interface{}{
								"type":   "Synced",
								"status": "True",
							},
							map[string]interface{}{
								"type":   "Ready",
								"status": "True",
							},
						},
					},
				},
			},
			expected: true,
			wantErr:  false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result, err := isAsyncActorReady(tt.asyncActor)

			if (err != nil) != tt.wantErr {
				t.Errorf("isAsyncActorReady() error = %v, wantErr %v", err, tt.wantErr)
				return
			}

			if result != tt.expected {
				t.Errorf("isAsyncActorReady() = %v, expected %v", result, tt.expected)
			}
		})
	}
}

func TestExtractActorConfig(t *testing.T) {
	tests := []struct {
		name       string
		asyncActor *unstructured.Unstructured
		wantErr    bool
		checks     func(*testing.T, *struct {
			ActorName              string
			Namespace              string
			Transport              string
			QueueURL               string
			Handler                string
			SidecarImage           string
			SidecarImagePullPolicy string
			SidecarEnvNames        []string
			SidecarEnvValues       []string
			Region                 string
		})
	}{
		{
			name: "minimal spec",
			asyncActor: &unstructured.Unstructured{
				Object: map[string]interface{}{
					"spec": map[string]interface{}{},
				},
			},
			wantErr: false,
			checks: func(t *testing.T, cfg *struct {
				ActorName              string
				Namespace              string
				Transport              string
				QueueURL               string
				Handler                string
				SidecarImage           string
				SidecarImagePullPolicy string
				SidecarEnvNames        []string
				SidecarEnvValues       []string
				Region                 string
			}) {
				if cfg.Transport != "sqs" {
					t.Errorf("expected transport 'sqs', got '%s'", cfg.Transport)
				}
				if cfg.Region != "us-east-1" {
					t.Errorf("expected region 'us-east-1', got '%s'", cfg.Region)
				}
			},
		},
		{
			name: "full spec",
			asyncActor: &unstructured.Unstructured{
				Object: map[string]interface{}{
					"spec": map[string]interface{}{
						"transport": "rabbitmq",
						"region":    "eu-west-1",
						"workload": map[string]interface{}{
							"handler": "my_module.process",
						},
						"sidecar": map[string]interface{}{
							"image": "custom-sidecar:v2",
						},
					},
					"status": map[string]interface{}{
						"queueUrl": "http://localhost/queue",
					},
				},
			},
			wantErr: false,
			checks: func(t *testing.T, cfg *struct {
				ActorName              string
				Namespace              string
				Transport              string
				QueueURL               string
				Handler                string
				SidecarImage           string
				SidecarImagePullPolicy string
				SidecarEnvNames        []string
				SidecarEnvValues       []string
				Region                 string
			}) {
				if cfg.Transport != "rabbitmq" {
					t.Errorf("expected transport 'rabbitmq', got '%s'", cfg.Transport)
				}
				if cfg.Region != "eu-west-1" {
					t.Errorf("expected region 'eu-west-1', got '%s'", cfg.Region)
				}
				if cfg.Handler != "my_module.process" {
					t.Errorf("expected handler 'my_module.process', got '%s'", cfg.Handler)
				}
				if cfg.SidecarImage != "custom-sidecar:v2" {
					t.Errorf("expected sidecarImage 'custom-sidecar:v2', got '%s'", cfg.SidecarImage)
				}
				if cfg.QueueURL != "http://localhost/queue" {
					t.Errorf("expected queueUrl 'http://localhost/queue', got '%s'", cfg.QueueURL)
				}
			},
		},
		{
			name: "sidecar with imagePullPolicy and env",
			asyncActor: &unstructured.Unstructured{
				Object: map[string]interface{}{
					"spec": map[string]interface{}{
						"transport": "sqs",
						"sidecar": map[string]interface{}{
							"image":           "custom:v1",
							"imagePullPolicy": "Always",
							"env": []interface{}{
								map[string]interface{}{
									"name":  "ASYA_LOG_LEVEL",
									"value": "debug",
								},
								map[string]interface{}{
									"name":  "MY_VAR",
									"value": "my-value",
								},
							},
						},
					},
				},
			},
			wantErr: false,
			checks: func(t *testing.T, cfg *struct {
				ActorName              string
				Namespace              string
				Transport              string
				QueueURL               string
				Handler                string
				SidecarImage           string
				SidecarImagePullPolicy string
				SidecarEnvNames        []string
				SidecarEnvValues       []string
				Region                 string
			}) {
				if cfg.SidecarImage != "custom:v1" {
					t.Errorf("expected sidecarImage 'custom:v1', got '%s'", cfg.SidecarImage)
				}
				if cfg.SidecarImagePullPolicy != "Always" {
					t.Errorf("expected imagePullPolicy 'Always', got '%s'", cfg.SidecarImagePullPolicy)
				}
				if len(cfg.SidecarEnvNames) != 2 {
					t.Fatalf("expected 2 env vars, got %d", len(cfg.SidecarEnvNames))
				}
				if cfg.SidecarEnvNames[0] != "ASYA_LOG_LEVEL" || cfg.SidecarEnvValues[0] != "debug" {
					t.Errorf("expected first env ASYA_LOG_LEVEL=debug, got %s=%s", cfg.SidecarEnvNames[0], cfg.SidecarEnvValues[0])
				}
				if cfg.SidecarEnvNames[1] != "MY_VAR" || cfg.SidecarEnvValues[1] != "my-value" {
					t.Errorf("expected second env MY_VAR=my-value, got %s=%s", cfg.SidecarEnvNames[1], cfg.SidecarEnvValues[1])
				}
			},
		},
		{
			name: "sidecar without imagePullPolicy and env",
			asyncActor: &unstructured.Unstructured{
				Object: map[string]interface{}{
					"spec": map[string]interface{}{
						"transport": "sqs",
						"sidecar": map[string]interface{}{
							"image": "custom:v1",
						},
					},
				},
			},
			wantErr: false,
			checks: func(t *testing.T, cfg *struct {
				ActorName              string
				Namespace              string
				Transport              string
				QueueURL               string
				Handler                string
				SidecarImage           string
				SidecarImagePullPolicy string
				SidecarEnvNames        []string
				SidecarEnvValues       []string
				Region                 string
			}) {
				if cfg.SidecarImagePullPolicy != "" {
					t.Errorf("expected empty imagePullPolicy, got '%s'", cfg.SidecarImagePullPolicy)
				}
				if len(cfg.SidecarEnvNames) != 0 {
					t.Errorf("expected no env vars, got %d", len(cfg.SidecarEnvNames))
				}
			},
		},
		{
			name: "no spec",
			asyncActor: &unstructured.Unstructured{
				Object: map[string]interface{}{},
			},
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg, err := extractActorConfig(tt.asyncActor)

			if (err != nil) != tt.wantErr {
				t.Errorf("extractActorConfig() error = %v, wantErr %v", err, tt.wantErr)
				return
			}

			if err == nil && tt.checks != nil {
				// Extract env names/values for easy checking
				var envNames, envValues []string
				for _, ev := range cfg.SidecarEnv {
					envNames = append(envNames, ev.Name)
					envValues = append(envValues, ev.Value)
				}

				// Convert to anonymous struct for checking
				check := struct {
					ActorName              string
					Namespace              string
					Transport              string
					QueueURL               string
					Handler                string
					SidecarImage           string
					SidecarImagePullPolicy string
					SidecarEnvNames        []string
					SidecarEnvValues       []string
					Region                 string
				}{
					Transport:              cfg.Transport,
					QueueURL:               cfg.QueueURL,
					Handler:                cfg.Handler,
					SidecarImage:           cfg.SidecarImage,
					SidecarImagePullPolicy: cfg.SidecarImagePullPolicy,
					SidecarEnvNames:        envNames,
					SidecarEnvValues:       envValues,
					Region:                 cfg.Region,
				}
				tt.checks(t, &check)
			}
		})
	}
}

func TestExtractResiliencyConfig(t *testing.T) {
	t.Run("no resiliency section", func(t *testing.T) {
		asyncActor := &unstructured.Unstructured{
			Object: map[string]interface{}{
				"spec": map[string]interface{}{
					"transport": "sqs",
				},
			},
		}

		cfg, err := extractActorConfig(asyncActor)
		if err != nil {
			t.Fatalf("extractActorConfig() error: %v", err)
		}
		if cfg.Resiliency != nil {
			t.Error("expected nil Resiliency when section is absent")
		}
	})

	t.Run("full resiliency config", func(t *testing.T) {
		asyncActor := &unstructured.Unstructured{
			Object: map[string]interface{}{
				"spec": map[string]interface{}{
					"transport": "sqs",
					"resiliency": map[string]interface{}{
						"retry": map[string]interface{}{
							"policy":             "exponential",
							"maxAttempts":        int64(5),
							"initialInterval":    "1s",
							"maxInterval":        "300s",
							"backoffCoefficient": float64(2.0),
							"jitter":             true,
						},
						"nonRetryableErrors": []interface{}{"ValueError", "KeyError"},
						"actorTimeout":       "30s",
					},
				},
			},
		}

		cfg, err := extractActorConfig(asyncActor)
		if err != nil {
			t.Fatalf("extractActorConfig() error: %v", err)
		}
		if cfg.Resiliency == nil {
			t.Fatal("expected non-nil Resiliency")
		}
		if cfg.Resiliency.Retry == nil {
			t.Fatal("expected non-nil Retry config")
		}
		if cfg.Resiliency.Retry.Policy != "exponential" {
			t.Errorf("expected policy 'exponential', got '%s'", cfg.Resiliency.Retry.Policy)
		}
		if cfg.Resiliency.Retry.MaxAttempts != "5" {
			t.Errorf("expected maxAttempts '5', got '%s'", cfg.Resiliency.Retry.MaxAttempts)
		}
		if cfg.Resiliency.Retry.InitialInterval != "1s" {
			t.Errorf("expected initialInterval '1s', got '%s'", cfg.Resiliency.Retry.InitialInterval)
		}
		if cfg.Resiliency.Retry.MaxInterval != "300s" {
			t.Errorf("expected maxInterval '300s', got '%s'", cfg.Resiliency.Retry.MaxInterval)
		}
		if cfg.Resiliency.Retry.BackoffCoefficient != "2" {
			t.Errorf("expected backoffCoefficient '2', got '%s'", cfg.Resiliency.Retry.BackoffCoefficient)
		}
		if cfg.Resiliency.Retry.Jitter != "true" {
			t.Errorf("expected jitter 'true', got '%s'", cfg.Resiliency.Retry.Jitter)
		}
		if cfg.Resiliency.NonRetryableErrors != "ValueError,KeyError" {
			t.Errorf("expected nonRetryableErrors 'ValueError,KeyError', got '%s'", cfg.Resiliency.NonRetryableErrors)
		}
		if cfg.Resiliency.ActorTimeout != "30s" {
			t.Errorf("expected actorTimeout '30s', got '%s'", cfg.Resiliency.ActorTimeout)
		}
	})

	t.Run("resiliency with only actorTimeout", func(t *testing.T) {
		asyncActor := &unstructured.Unstructured{
			Object: map[string]interface{}{
				"spec": map[string]interface{}{
					"transport": "sqs",
					"resiliency": map[string]interface{}{
						"actorTimeout": "60s",
					},
				},
			},
		}

		cfg, err := extractActorConfig(asyncActor)
		if err != nil {
			t.Fatalf("extractActorConfig() error: %v", err)
		}
		if cfg.Resiliency == nil {
			t.Fatal("expected non-nil Resiliency")
		}
		if cfg.Resiliency.Retry != nil {
			t.Error("expected nil Retry when not specified")
		}
		if cfg.Resiliency.ActorTimeout != "60s" {
			t.Errorf("expected actorTimeout '60s', got '%s'", cfg.Resiliency.ActorTimeout)
		}
	})
}
