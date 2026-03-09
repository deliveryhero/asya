package webhook

import (
	"testing"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"

	"github.com/deliveryhero/asya/asya-injector/internal/injection"
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
			}) {
				if cfg.Transport != "sqs" {
					t.Errorf("expected transport 'sqs', got '%s'", cfg.Transport)
				}
			},
		},
		{
			name: "full spec",
			asyncActor: &unstructured.Unstructured{
				Object: map[string]interface{}{
					"spec": map[string]interface{}{
						"transport": "rabbitmq",
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
			}) {
				if cfg.Transport != "rabbitmq" {
					t.Errorf("expected transport 'rabbitmq', got '%s'", cfg.Transport)
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
				}{
					Transport:              cfg.Transport,
					QueueURL:               cfg.QueueURL,
					Handler:                cfg.Handler,
					SidecarImage:           cfg.SidecarImage,
					SidecarImagePullPolicy: cfg.SidecarImagePullPolicy,
					SidecarEnvNames:        envNames,
					SidecarEnvValues:       envValues,
				}
				tt.checks(t, &check)
			}
		})
	}
}

func TestExtractActorConfig_SecretRefs(t *testing.T) {
	tests := []struct {
		name           string
		secretRefsSpec []interface{}
		wantRefs       int
		check          func(t *testing.T, refs []injection.SecretRef)
	}{
		{
			name: "happy path: one secret one key",
			secretRefsSpec: []interface{}{
				map[string]interface{}{
					"secretName": "openai-creds",
					"keys": []interface{}{
						map[string]interface{}{"key": "api_key", "envVar": "OPENAI_API_KEY"},
					},
				},
			},
			wantRefs: 1,
			check: func(t *testing.T, refs []injection.SecretRef) {
				t.Helper()
				if refs[0].SecretName != "openai-creds" {
					t.Errorf("secretName: got %q, want %q", refs[0].SecretName, "openai-creds")
				}
				if refs[0].Keys[0].Key != "api_key" || refs[0].Keys[0].EnvVar != "OPENAI_API_KEY" {
					t.Errorf("key mapping wrong: %+v", refs[0].Keys[0])
				}
			},
		},
		{
			name: "empty secretName is skipped",
			secretRefsSpec: []interface{}{
				map[string]interface{}{
					"secretName": "",
					"keys": []interface{}{
						map[string]interface{}{"key": "k", "envVar": "V"},
					},
				},
			},
			wantRefs: 0,
			check:    nil,
		},
		{
			name: "key with empty key field is skipped",
			secretRefsSpec: []interface{}{
				map[string]interface{}{
					"secretName": "my-secret",
					"keys": []interface{}{
						map[string]interface{}{"key": "", "envVar": "SOME_VAR"},
					},
				},
			},
			wantRefs: 0, // no valid keys → whole ref dropped
			check:    nil,
		},
		{
			name: "key with empty envVar is skipped",
			secretRefsSpec: []interface{}{
				map[string]interface{}{
					"secretName": "my-secret",
					"keys": []interface{}{
						map[string]interface{}{"key": "some_key", "envVar": ""},
					},
				},
			},
			wantRefs: 0,
			check:    nil,
		},
		{
			name: "valid and invalid keys in same ref: only valid key retained",
			secretRefsSpec: []interface{}{
				map[string]interface{}{
					"secretName": "mixed-secret",
					"keys": []interface{}{
						map[string]interface{}{"key": "good_key", "envVar": "GOOD_VAR"},
						map[string]interface{}{"key": "", "envVar": "BAD_VAR"},
					},
				},
			},
			wantRefs: 1,
			check: func(t *testing.T, refs []injection.SecretRef) {
				t.Helper()
				if len(refs[0].Keys) != 1 {
					t.Errorf("expected 1 valid key, got %d", len(refs[0].Keys))
				}
				if refs[0].Keys[0].Key != "good_key" {
					t.Errorf("wrong key retained: %q", refs[0].Keys[0].Key)
				}
			},
		},
		{
			name: "multiple secretRefs all included",
			secretRefsSpec: []interface{}{
				map[string]interface{}{
					"secretName": "secret-a",
					"keys": []interface{}{
						map[string]interface{}{"key": "k1", "envVar": "VAR1"},
					},
				},
				map[string]interface{}{
					"secretName": "secret-b",
					"keys": []interface{}{
						map[string]interface{}{"key": "k2", "envVar": "VAR2"},
					},
				},
			},
			wantRefs: 2,
			check: func(t *testing.T, refs []injection.SecretRef) {
				t.Helper()
				if refs[0].SecretName != "secret-a" || refs[1].SecretName != "secret-b" {
					t.Errorf("wrong secrets: %v %v", refs[0].SecretName, refs[1].SecretName)
				}
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			asyncActor := &unstructured.Unstructured{
				Object: map[string]interface{}{
					"spec": map[string]interface{}{
						"transport":  "sqs",
						"secretRefs": tt.secretRefsSpec,
					},
					"status": map[string]interface{}{
						"conditions": []interface{}{
							map[string]interface{}{"type": "Ready", "status": "True"},
						},
					},
				},
			}

			config, err := extractActorConfig(asyncActor)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if len(config.SecretRefs) != tt.wantRefs {
				t.Fatalf("expected %d SecretRefs, got %d", tt.wantRefs, len(config.SecretRefs))
			}
			if tt.check != nil {
				tt.check(t, config.SecretRefs)
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
