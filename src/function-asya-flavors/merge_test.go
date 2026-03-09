package main

import (
	"testing"

	"github.com/google/go-cmp/cmp"
)

func TestMergeFlavors_EmptyList(t *testing.T) {
	result := MergeFlavors(nil)

	if len(result) != 0 {
		t.Errorf("expected empty map, got %v", result)
	}
}

func TestMergeFlavors_SingleFlavor(t *testing.T) {
	data := []map[string]interface{}{
		{
			"scaling": map[string]interface{}{
				"minReplicas": float64(1),
				"maxReplicas": float64(4),
			},
		},
	}

	result := MergeFlavors(data)

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

func TestMergeFlavors_ScalingFieldsMerge(t *testing.T) {
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

	result := MergeFlavors(data)

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

func TestMergeFlavors_EnvVarsMergeByName(t *testing.T) {
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

	result := MergeFlavors(data)

	envVars := getEnvVars(t, result)
	// mergeByName deep-merges containers with same name, so env vars accumulate
	if len(envVars) != 2 {
		t.Fatalf("expected 2 env vars (deep merge preserves both), got %d: %v", len(envVars), envVars)
	}

	envMap := make(map[string]string)
	for _, e := range envVars {
		env := e.(map[string]interface{})
		envMap[env["name"].(string)] = env["value"].(string)
	}
	if envMap["FOO"] != "bar" {
		t.Errorf("FOO: got %q, want %q", envMap["FOO"], "bar")
	}
	if envMap["BAZ"] != "qux" {
		t.Errorf("BAZ: got %q, want %q", envMap["BAZ"], "qux")
	}
}

func TestMergeFlavors_EnvVarOverrideByName(t *testing.T) {
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

	result := MergeFlavors(data)

	envVars := getEnvVars(t, result)
	if len(envVars) != 1 {
		t.Fatalf("expected 1 env var (merged by name), got %d", len(envVars))
	}

	env := envVars[0].(map[string]interface{})
	if env["value"] != "DEBUG" {
		t.Errorf("LOG_LEVEL: got %q, want %q (later flavor should win)", env["value"], "DEBUG")
	}
}

func TestMergeFlavors_ValueFromSecretKeyRef(t *testing.T) {
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

	result := MergeFlavors(data)

	envVars := getEnvVars(t, result)
	// mergeByName deep-merges containers with same name, so env vars accumulate
	if len(envVars) != 2 {
		t.Fatalf("expected 2 env vars (deep merge preserves both), got %d", len(envVars))
	}

	envMap := make(map[string]interface{})
	for _, e := range envVars {
		env := e.(map[string]interface{})
		envMap[env["name"].(string)] = env
	}

	plainVar := envMap["PLAIN_VAR"].(map[string]interface{})
	if plainVar["value"] != "hello" {
		t.Errorf("PLAIN_VAR: got %q, want %q", plainVar["value"], "hello")
	}

	secretVar := envMap["SECRET_VAR"].(map[string]interface{})
	secretRef := secretVar["valueFrom"].(map[string]interface{})["secretKeyRef"].(map[string]interface{})
	if secretRef["name"] != "my-secret" || secretRef["key"] != "api-key" {
		t.Errorf("SECRET_VAR secretKeyRef mismatch: %v", secretRef)
	}
}

func TestMergeFlavors_TolerationsReplacedAtomically(t *testing.T) {
	// PodSpec.Tolerations uses +listType=atomic in Kubernetes, meaning
	// the last flavor's tolerations replace earlier ones entirely.
	// Flavors that need both GPU and dedicated tolerations should include
	// all of them in a single flavor definition.
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

	result := MergeFlavors(data)

	tolerations := result["workload"].(map[string]interface{})["template"].(map[string]interface{})["spec"].(map[string]interface{})["tolerations"].([]interface{})

	// Only the last flavor's tolerations survive (atomic replace)
	if len(tolerations) != 1 {
		t.Fatalf("expected 1 toleration (atomic list replace), got %d", len(tolerations))
	}

	tol := tolerations[0].(map[string]interface{})
	if tol["key"] != "dedicated" {
		t.Errorf("expected toleration key %q, got %q", "dedicated", tol["key"])
	}
}

func TestMergeFlavors_TolerationsCombinedInSingleFlavor(t *testing.T) {
	// Correct usage: a single flavor bundles all needed tolerations
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

	result := MergeFlavors(data)

	tolerations := result["workload"].(map[string]interface{})["template"].(map[string]interface{})["spec"].(map[string]interface{})["tolerations"].([]interface{})

	if len(tolerations) != 2 {
		t.Fatalf("expected 2 tolerations from single flavor, got %d", len(tolerations))
	}
}

func TestMergeFlavors_ResourceOverride(t *testing.T) {
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

	result := MergeFlavors(data)

	containers := result["workload"].(map[string]interface{})["template"].(map[string]interface{})["spec"].(map[string]interface{})["containers"].([]interface{})
	container := containers[0].(map[string]interface{})
	limits := container["resources"].(map[string]interface{})["limits"].(map[string]interface{})

	if limits["memory"] != "16Gi" {
		t.Errorf("memory: got %v, want 16Gi (later flavor should override)", limits["memory"])
	}
	if limits["nvidia.com/gpu"] != "1" {
		t.Errorf("nvidia.com/gpu: got %v, want 1", limits["nvidia.com/gpu"])
	}
}

func TestDeepMerge_ActorInlineWins(t *testing.T) {
	flavorData := []map[string]interface{}{
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
										"name":  "FLAVOR_VAR",
										"value": "from-flavor",
									},
								},
							},
						},
					},
				},
			},
		},
	}

	merged := MergeFlavors(flavorData)

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

	result := DeepMerge(merged, actorSpec)

	// Actor's minReplicas=2 should override flavor's minReplicas=1
	scaling := result["scaling"].(map[string]interface{})
	if scaling["minReplicas"] != float64(2) {
		t.Errorf("minReplicas: got %v, want 2 (actor should override)", scaling["minReplicas"])
	}
	// Flavor's cooldownPeriod should be preserved
	if scaling["cooldownPeriod"] != float64(600) {
		t.Errorf("cooldownPeriod: got %v, want 600 (should be preserved from flavor)", scaling["cooldownPeriod"])
	}

	// mergeByName deep-merges containers with same name, so env vars accumulate
	envVars := getEnvVars(t, result)

	envMap := make(map[string]string)
	for _, e := range envVars {
		env := e.(map[string]interface{})
		if v, ok := env["value"].(string); ok {
			envMap[env["name"].(string)] = v
		}
	}

	// Actor's LOG_LEVEL=DEBUG should override flavor's LOG_LEVEL=INFO
	if envMap["LOG_LEVEL"] != "DEBUG" {
		t.Errorf("LOG_LEVEL: got %q, want %q (actor should override)", envMap["LOG_LEVEL"], "DEBUG")
	}
	// Actor's ASYA_HANDLER should be present
	if envMap["ASYA_HANDLER"] != "model.inference" {
		t.Errorf("ASYA_HANDLER: got %q, want %q", envMap["ASYA_HANDLER"], "model.inference")
	}
	// FLAVOR_VAR is preserved (deep merge keeps flavor env vars alongside actor env vars)
	if envMap["FLAVOR_VAR"] != "from-flavor" {
		t.Errorf("FLAVOR_VAR: got %q, want %q (should be preserved from flavor)", envMap["FLAVOR_VAR"], "from-flavor")
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
