package main

import (
	"testing"

	"github.com/google/go-cmp/cmp"
)

func TestMergeOverlays_EmptyList(t *testing.T) {
	result, err := MergeOverlays(nil)
	if err != nil {
		t.Fatal(err)
	}

	if len(result) != 0 {
		t.Errorf("expected empty map, got %v", result)
	}
}

func TestMergeOverlays_SingleOverlay(t *testing.T) {
	data := []map[string]interface{}{
		{
			"scaling": map[string]interface{}{
				"minReplicas": float64(1),
				"maxReplicas": float64(4),
			},
		},
	}

	result, err := MergeOverlays(data)
	if err != nil {
		t.Fatal(err)
	}

	want := map[string]interface{}{
		"scaling": map[string]interface{}{
			"minReplicas": float64(1),
			"maxReplicas": float64(4),
		},
	}

	if diff := cmp.Diff(want, result); diff != "" {
		t.Errorf("mismatch (-want +got):\n%s", diff)
	}
}

func TestMergeOverlays_ScalingFieldsMerge(t *testing.T) {
	data := []map[string]interface{}{
		{
			"scaling": map[string]interface{}{
				"minReplicas":    float64(1),
				"cooldownPeriod": float64(600),
			},
		},
		{
			"scaling": map[string]interface{}{
				"maxReplicas": float64(4),
			},
		},
	}

	result, err := MergeOverlays(data)
	if err != nil {
		t.Fatal(err)
	}

	scaling := result["scaling"].(map[string]interface{})

	if scaling["minReplicas"] != float64(1) {
		t.Errorf("minReplicas: got %v, want 1", scaling["minReplicas"])
	}
	if scaling["maxReplicas"] != float64(4) {
		t.Errorf("maxReplicas: got %v, want 4", scaling["maxReplicas"])
	}
	if scaling["cooldownPeriod"] != float64(600) {
		t.Errorf("cooldownPeriod: got %v, want 600", scaling["cooldownPeriod"])
	}
}

func TestMergeOverlays_EnvVarsMergeByName(t *testing.T) {
	data := []map[string]interface{}{
		{
			"workload": map[string]interface{}{
				"template": map[string]interface{}{
					"spec": map[string]interface{}{
						"containers": []interface{}{
							map[string]interface{}{
								"name": "asya-runtime",
								"env": []interface{}{
									map[string]interface{}{
										"name":  "FOO",
										"value": "bar",
									},
								},
							},
						},
					},
				},
			},
		},
		{
			"workload": map[string]interface{}{
				"template": map[string]interface{}{
					"spec": map[string]interface{}{
						"containers": []interface{}{
							map[string]interface{}{
								"name": "asya-runtime",
								"env": []interface{}{
									map[string]interface{}{
										"name":  "BAZ",
										"value": "qux",
									},
								},
							},
						},
					},
				},
			},
		},
	}

	result, err := MergeOverlays(data)
	if err != nil {
		t.Fatal(err)
	}

	envVars := getEnvVars(t, result)
	if len(envVars) != 2 {
		t.Fatalf("expected 2 env vars, got %d: %v", len(envVars), envVars)
	}

	envNames := make(map[string]string)
	for _, e := range envVars {
		env := e.(map[string]interface{})
		envNames[env["name"].(string)] = env["value"].(string)
	}

	if envNames["FOO"] != "bar" {
		t.Errorf("FOO: got %q, want %q", envNames["FOO"], "bar")
	}
	if envNames["BAZ"] != "qux" {
		t.Errorf("BAZ: got %q, want %q", envNames["BAZ"], "qux")
	}
}

func TestMergeOverlays_EnvVarOverrideByName(t *testing.T) {
	data := []map[string]interface{}{
		{
			"workload": map[string]interface{}{
				"template": map[string]interface{}{
					"spec": map[string]interface{}{
						"containers": []interface{}{
							map[string]interface{}{
								"name": "asya-runtime",
								"env": []interface{}{
									map[string]interface{}{
										"name":  "LOG_LEVEL",
										"value": "INFO",
									},
								},
							},
						},
					},
				},
			},
		},
		{
			"workload": map[string]interface{}{
				"template": map[string]interface{}{
					"spec": map[string]interface{}{
						"containers": []interface{}{
							map[string]interface{}{
								"name": "asya-runtime",
								"env": []interface{}{
									map[string]interface{}{
										"name":  "LOG_LEVEL",
										"value": "DEBUG",
									},
								},
							},
						},
					},
				},
			},
		},
	}

	result, err := MergeOverlays(data)
	if err != nil {
		t.Fatal(err)
	}

	envVars := getEnvVars(t, result)
	if len(envVars) != 1 {
		t.Fatalf("expected 1 env var (merged by name), got %d", len(envVars))
	}

	env := envVars[0].(map[string]interface{})
	if env["value"] != "DEBUG" {
		t.Errorf("LOG_LEVEL: got %q, want %q (later overlay should win)", env["value"], "DEBUG")
	}
}

func TestMergeOverlays_ValueFromSecretKeyRef(t *testing.T) {
	data := []map[string]interface{}{
		{
			"workload": map[string]interface{}{
				"template": map[string]interface{}{
					"spec": map[string]interface{}{
						"containers": []interface{}{
							map[string]interface{}{
								"name": "asya-runtime",
								"env": []interface{}{
									map[string]interface{}{
										"name":  "PLAIN_VAR",
										"value": "hello",
									},
								},
							},
						},
					},
				},
			},
		},
		{
			"workload": map[string]interface{}{
				"template": map[string]interface{}{
					"spec": map[string]interface{}{
						"containers": []interface{}{
							map[string]interface{}{
								"name": "asya-runtime",
								"env": []interface{}{
									map[string]interface{}{
										"name": "SECRET_VAR",
										"valueFrom": map[string]interface{}{
											"secretKeyRef": map[string]interface{}{
												"name": "my-secret",
												"key":  "api-key",
											},
										},
									},
								},
							},
						},
					},
				},
			},
		},
	}

	result, err := MergeOverlays(data)
	if err != nil {
		t.Fatal(err)
	}

	envVars := getEnvVars(t, result)
	if len(envVars) != 2 {
		t.Fatalf("expected 2 env vars, got %d", len(envVars))
	}

	envMap := make(map[string]map[string]interface{})
	for _, e := range envVars {
		env := e.(map[string]interface{})
		envMap[env["name"].(string)] = env
	}

	if envMap["PLAIN_VAR"]["value"] != "hello" {
		t.Errorf("PLAIN_VAR value mismatch")
	}

	secretRef := envMap["SECRET_VAR"]["valueFrom"].(map[string]interface{})["secretKeyRef"].(map[string]interface{})
	if secretRef["name"] != "my-secret" || secretRef["key"] != "api-key" {
		t.Errorf("SECRET_VAR secretKeyRef mismatch: %v", secretRef)
	}
}

func TestMergeOverlays_TolerationsReplacedAtomically(t *testing.T) {
	// PodSpec.Tolerations uses +listType=atomic in Kubernetes, meaning
	// the last overlay's tolerations replace earlier ones entirely.
	// Overlays that need both GPU and dedicated tolerations should include
	// all of them in a single overlay definition.
	data := []map[string]interface{}{
		{
			"workload": map[string]interface{}{
				"template": map[string]interface{}{
					"spec": map[string]interface{}{
						"tolerations": []interface{}{
							map[string]interface{}{
								"key":      "nvidia.com/gpu",
								"operator": "Exists",
								"effect":   "NoSchedule",
							},
						},
					},
				},
			},
		},
		{
			"workload": map[string]interface{}{
				"template": map[string]interface{}{
					"spec": map[string]interface{}{
						"tolerations": []interface{}{
							map[string]interface{}{
								"key":      "dedicated",
								"operator": "Equal",
								"value":    "ml-workloads",
								"effect":   "NoSchedule",
							},
						},
					},
				},
			},
		},
	}

	result, err := MergeOverlays(data)
	if err != nil {
		t.Fatal(err)
	}

	tolerations := result["workload"].(map[string]interface{})["template"].(map[string]interface{})["spec"].(map[string]interface{})["tolerations"].([]interface{})

	// Only the last overlay's tolerations survive (atomic replace)
	if len(tolerations) != 1 {
		t.Fatalf("expected 1 toleration (atomic list replace), got %d", len(tolerations))
	}

	tol := tolerations[0].(map[string]interface{})
	if tol["key"] != "dedicated" {
		t.Errorf("expected toleration key %q, got %q", "dedicated", tol["key"])
	}
}

func TestMergeOverlays_TolerationsCombinedInSingleOverlay(t *testing.T) {
	// Correct usage: a single overlay bundles all needed tolerations
	data := []map[string]interface{}{
		{
			"workload": map[string]interface{}{
				"template": map[string]interface{}{
					"spec": map[string]interface{}{
						"tolerations": []interface{}{
							map[string]interface{}{
								"key":      "nvidia.com/gpu",
								"operator": "Exists",
								"effect":   "NoSchedule",
							},
							map[string]interface{}{
								"key":      "dedicated",
								"operator": "Equal",
								"value":    "ml-workloads",
								"effect":   "NoSchedule",
							},
						},
					},
				},
			},
		},
	}

	result, err := MergeOverlays(data)
	if err != nil {
		t.Fatal(err)
	}

	tolerations := result["workload"].(map[string]interface{})["template"].(map[string]interface{})["spec"].(map[string]interface{})["tolerations"].([]interface{})

	if len(tolerations) != 2 {
		t.Fatalf("expected 2 tolerations from single overlay, got %d", len(tolerations))
	}
}

func TestMergeOverlays_ResourceOverride(t *testing.T) {
	data := []map[string]interface{}{
		{
			"workload": map[string]interface{}{
				"template": map[string]interface{}{
					"spec": map[string]interface{}{
						"containers": []interface{}{
							map[string]interface{}{
								"name": "asya-runtime",
								"resources": map[string]interface{}{
									"limits": map[string]interface{}{
										"memory": "8Gi",
										"cpu":    "2",
									},
								},
							},
						},
					},
				},
			},
		},
		{
			"workload": map[string]interface{}{
				"template": map[string]interface{}{
					"spec": map[string]interface{}{
						"containers": []interface{}{
							map[string]interface{}{
								"name": "asya-runtime",
								"resources": map[string]interface{}{
									"limits": map[string]interface{}{
										"memory":          "16Gi",
										"nvidia.com/gpu":  "1",
									},
								},
							},
						},
					},
				},
			},
		},
	}

	result, err := MergeOverlays(data)
	if err != nil {
		t.Fatal(err)
	}

	containers := result["workload"].(map[string]interface{})["template"].(map[string]interface{})["spec"].(map[string]interface{})["containers"].([]interface{})
	container := containers[0].(map[string]interface{})
	limits := container["resources"].(map[string]interface{})["limits"].(map[string]interface{})

	if limits["memory"] != "16Gi" {
		t.Errorf("memory: got %v, want 16Gi (later overlay should override)", limits["memory"])
	}
	if limits["nvidia.com/gpu"] != "1" {
		t.Errorf("nvidia.com/gpu: got %v, want 1", limits["nvidia.com/gpu"])
	}
}

func TestApplyStrategicMerge_ActorInlineWins(t *testing.T) {
	overlayData := []map[string]interface{}{
		{
			"scaling": map[string]interface{}{
				"minReplicas":    float64(1),
				"cooldownPeriod": float64(600),
			},
			"workload": map[string]interface{}{
				"template": map[string]interface{}{
					"spec": map[string]interface{}{
						"containers": []interface{}{
							map[string]interface{}{
								"name": "asya-runtime",
								"env": []interface{}{
									map[string]interface{}{
										"name":  "LOG_LEVEL",
										"value": "INFO",
									},
									map[string]interface{}{
										"name":  "OVERLAY_VAR",
										"value": "from-overlay",
									},
								},
							},
						},
					},
				},
			},
		},
	}

	merged, err := MergeOverlays(overlayData)
	if err != nil {
		t.Fatal(err)
	}

	actorSpec := map[string]interface{}{
		"scaling": map[string]interface{}{
			"minReplicas": float64(2),
		},
		"workload": map[string]interface{}{
			"template": map[string]interface{}{
				"spec": map[string]interface{}{
					"containers": []interface{}{
						map[string]interface{}{
							"name":  "asya-runtime",
							"image": "my-llm:v1",
							"env": []interface{}{
								map[string]interface{}{
									"name":  "LOG_LEVEL",
									"value": "DEBUG",
								},
								map[string]interface{}{
									"name":  "ASYA_HANDLER",
									"value": "model.inference",
								},
							},
						},
					},
				},
			},
		},
	}

	result, err := ApplyStrategicMerge(merged, actorSpec)
	if err != nil {
		t.Fatal(err)
	}

	// Actor's minReplicas=2 should override overlay's minReplicas=1
	scaling := result["scaling"].(map[string]interface{})
	if scaling["minReplicas"] != float64(2) {
		t.Errorf("minReplicas: got %v, want 2 (actor should override)", scaling["minReplicas"])
	}
	// Overlay's cooldownPeriod should be preserved
	if scaling["cooldownPeriod"] != float64(600) {
		t.Errorf("cooldownPeriod: got %v, want 600 (should be preserved from overlay)", scaling["cooldownPeriod"])
	}

	envVars := getEnvVars(t, result)

	envMap := make(map[string]string)
	for _, e := range envVars {
		env := e.(map[string]interface{})
		if v, ok := env["value"].(string); ok {
			envMap[env["name"].(string)] = v
		}
	}

	// Actor's LOG_LEVEL=DEBUG should override overlay's LOG_LEVEL=INFO
	if envMap["LOG_LEVEL"] != "DEBUG" {
		t.Errorf("LOG_LEVEL: got %q, want %q (actor should override)", envMap["LOG_LEVEL"], "DEBUG")
	}
	// Overlay's OVERLAY_VAR should be preserved
	if envMap["OVERLAY_VAR"] != "from-overlay" {
		t.Errorf("OVERLAY_VAR: got %q, want %q (should be preserved from overlay)", envMap["OVERLAY_VAR"], "from-overlay")
	}
	// Actor's ASYA_HANDLER should be present
	if envMap["ASYA_HANDLER"] != "model.inference" {
		t.Errorf("ASYA_HANDLER: got %q, want %q", envMap["ASYA_HANDLER"], "model.inference")
	}
}

// getEnvVars extracts env vars from the first container in the merged result.
func getEnvVars(t *testing.T, result map[string]interface{}) []interface{} {
	t.Helper()

	workload, ok := result["workload"].(map[string]interface{})
	if !ok {
		t.Fatal("missing workload")
	}
	template, ok := workload["template"].(map[string]interface{})
	if !ok {
		t.Fatal("missing template")
	}
	spec, ok := template["spec"].(map[string]interface{})
	if !ok {
		t.Fatal("missing spec")
	}
	containers, ok := spec["containers"].([]interface{})
	if !ok || len(containers) == 0 {
		t.Fatal("missing containers")
	}
	container, ok := containers[0].(map[string]interface{})
	if !ok {
		t.Fatal("container is not a map")
	}
	envVars, ok := container["env"].([]interface{})
	if !ok {
		t.Fatal("missing env")
	}

	return envVars
}
