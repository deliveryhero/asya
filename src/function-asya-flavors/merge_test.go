package main

import (
	"testing"

	"github.com/google/go-cmp/cmp"
)

func TestMergeFlavors_EmptyList(t *testing.T) {
	result, err := MergeFlavors(nil)
	if err != nil {
		t.Fatal(err)
	}
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

	result, err := MergeFlavors(data)
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

func TestMergeFlavors_ScalingConflictErrors(t *testing.T) {
	data := []map[string]interface{}{
		{"scaling": map[string]interface{}{"minReplicas": float64(1)}},
		{"scaling": map[string]interface{}{"maxReplicas": float64(4)}},
	}

	_, err := MergeFlavors(data)
	if err == nil {
		t.Error("expected error for scaling defined in multiple flavors, got nil")
	}
}

func TestMergeFlavors_ResourcesConflictErrors(t *testing.T) {
	data := []map[string]interface{}{
		{"resources": map[string]interface{}{"limits": map[string]interface{}{"cpu": "1"}}},
		{"resources": map[string]interface{}{"limits": map[string]interface{}{"cpu": "2"}}},
	}

	_, err := MergeFlavors(data)
	if err == nil {
		t.Error("expected error for resources defined in multiple flavors, got nil")
	}
}

func TestMergeFlavors_TolerationsAppended(t *testing.T) {
	data := []map[string]interface{}{
		{
			"tolerations": []interface{}{
				map[string]interface{}{"key": "nvidia.com/gpu", "operator": "Exists"},
			},
		},
		{
			"tolerations": []interface{}{
				map[string]interface{}{"key": "dedicated", "operator": "Equal", "value": "ml"},
			},
		},
	}

	result, err := MergeFlavors(data)
	if err != nil {
		t.Fatal(err)
	}

	tolerations, ok := result["tolerations"].([]interface{})
	if !ok {
		t.Fatal("tolerations missing from result")
	}
	if len(tolerations) != 2 {
		t.Errorf("expected 2 tolerations (appended), got %d", len(tolerations))
	}
}

func TestMergeFlavors_StateProxyAppended(t *testing.T) {
	data := []map[string]interface{}{
		{
			"stateProxy": []interface{}{
				map[string]interface{}{"name": "s3-state", "mount": map[string]interface{}{"path": "/state"}},
			},
		},
		{
			"stateProxy": []interface{}{
				map[string]interface{}{"name": "redis-cache", "mount": map[string]interface{}{"path": "/cache"}},
			},
		},
	}

	result, err := MergeFlavors(data)
	if err != nil {
		t.Fatal(err)
	}

	sp, ok := result["stateProxy"].([]interface{})
	if !ok {
		t.Fatal("stateProxy missing from result")
	}
	if len(sp) != 2 {
		t.Errorf("expected 2 stateProxy entries (appended), got %d", len(sp))
	}
}

func TestMergeFlavors_NodeSelectorMergedNoConflict(t *testing.T) {
	data := []map[string]interface{}{
		{"nodeSelector": map[string]interface{}{"accelerator": "nvidia"}},
		{"nodeSelector": map[string]interface{}{"zone": "us-east-1a"}},
	}

	result, err := MergeFlavors(data)
	if err != nil {
		t.Fatal(err)
	}

	ns, ok := result["nodeSelector"].(map[string]interface{})
	if !ok {
		t.Fatal("nodeSelector missing")
	}
	if ns["accelerator"] != "nvidia" || ns["zone"] != "us-east-1a" {
		t.Errorf("unexpected nodeSelector: %v", ns)
	}
}

func TestMergeFlavors_NodeSelectorConflictErrors(t *testing.T) {
	data := []map[string]interface{}{
		{"nodeSelector": map[string]interface{}{"zone": "us-east-1a"}},
		{"nodeSelector": map[string]interface{}{"zone": "us-west-2a"}},
	}

	_, err := MergeFlavors(data)
	if err == nil {
		t.Error("expected error for conflicting nodeSelector key, got nil")
	}
}

func TestMergeFlavors_LastFlavorWinsForOtherFields(t *testing.T) {
	data := []map[string]interface{}{
		{"sidecar": map[string]interface{}{"image": "sidecar:v1"}},
		{"sidecar": map[string]interface{}{"image": "sidecar:v2"}},
	}

	result, err := MergeFlavors(data)
	if err != nil {
		t.Fatal(err)
	}

	sidecar, ok := result["sidecar"].(map[string]interface{})
	if !ok {
		t.Fatal("sidecar missing")
	}
	if sidecar["image"] != "sidecar:v2" {
		t.Errorf("expected last flavor to win, got %v", sidecar["image"])
	}
}

func TestApplyActorInline_WinsOverFlavor(t *testing.T) {
	base := map[string]interface{}{
		"scaling": map[string]interface{}{"minReplicas": float64(1)},
		"env":     []interface{}{map[string]interface{}{"name": "LOG_LEVEL", "value": "INFO"}},
	}
	actor := map[string]interface{}{
		"env":     []interface{}{map[string]interface{}{"name": "LOG_LEVEL", "value": "DEBUG"}},
		"handler": "my_module.handle",
	}

	result := ApplyActorInline(base, actor)

	envs, ok := result["env"].([]interface{})
	if !ok || len(envs) != 1 {
		t.Fatalf("expected 1 env var from actor, got %v", result["env"])
	}
	env := envs[0].(map[string]interface{})
	if env["value"] != "DEBUG" {
		t.Errorf("actor env should override flavor env, got %v", env["value"])
	}

	if result["scaling"] == nil {
		t.Error("scaling from flavor should be preserved")
	}

	if result["handler"] != "my_module.handle" {
		t.Error("actor handler should be present")
	}
}
