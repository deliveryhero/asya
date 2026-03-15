package main

import (
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
)

func TestMergeFlavors_EmptyList(t *testing.T) {
	result, err := MergeFlavors(nil, nil)
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

	result, err := MergeFlavors(data, []string{"gpu-t4"})
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

func TestMergeFlavors_ScalarConflictErrors(t *testing.T) {
	data := []map[string]interface{}{
		{"replicas": float64(2)},
		{"replicas": float64(4)},
	}

	_, err := MergeFlavors(data, []string{"flavor-a", "flavor-b"})
	if err == nil {
		t.Fatal("expected error for scalar conflict, got nil")
	}
	if !strings.Contains(err.Error(), `"flavor-a"`) || !strings.Contains(err.Error(), `"flavor-b"`) {
		t.Errorf("error should mention flavor names, got: %s", err)
	}
}

func TestMergeFlavors_MapConflictOnSameKeyErrors(t *testing.T) {
	data := []map[string]interface{}{
		{"scaling": map[string]interface{}{"minReplicas": float64(1)}},
		{"scaling": map[string]interface{}{"minReplicas": float64(2)}},
	}

	_, err := MergeFlavors(data, []string{"flavor-a", "flavor-b"})
	if err == nil {
		t.Fatal("expected error for map key conflict, got nil")
	}
	if !strings.Contains(err.Error(), "scaling.minReplicas") {
		t.Errorf("error should mention conflicting key path, got: %s", err)
	}
}

func TestMergeFlavors_MapMergeDistinctKeys(t *testing.T) {
	data := []map[string]interface{}{
		{"scaling": map[string]interface{}{"minReplicas": float64(1)}},
		{"scaling": map[string]interface{}{"maxReplicas": float64(10)}},
	}

	result, err := MergeFlavors(data, []string{"flavor-a", "flavor-b"})
	if err != nil {
		t.Fatal(err)
	}

	scaling := result["scaling"].(map[string]interface{})
	if scaling["minReplicas"] != float64(1) || scaling["maxReplicas"] != float64(10) {
		t.Errorf("expected merged map keys, got %v", scaling)
	}
}

func TestMergeFlavors_ResourcesDeepConflictErrors(t *testing.T) {
	data := []map[string]interface{}{
		{"resources": map[string]interface{}{"limits": map[string]interface{}{"cpu": "1"}}},
		{"resources": map[string]interface{}{"limits": map[string]interface{}{"cpu": "2"}}},
	}

	_, err := MergeFlavors(data, []string{"flavor-a", "flavor-b"})
	if err == nil {
		t.Fatal("expected error for resources leaf key conflict, got nil")
	}
	if !strings.Contains(err.Error(), "resources.limits.cpu") {
		t.Errorf("error should mention full conflicting key path, got: %s", err)
	}
}

func TestMergeFlavors_ResourcesDeepMergeDistinctLeafKeys(t *testing.T) {
	data := []map[string]interface{}{
		{"resources": map[string]interface{}{"limits": map[string]interface{}{"cpu": "500m"}}},
		{"resources": map[string]interface{}{"limits": map[string]interface{}{"memory": "4Gi"}}},
	}

	result, err := MergeFlavors(data, []string{"cpu-flavor", "memory-flavor"})
	if err != nil {
		t.Fatalf("distinct leaf keys should merge without error, got: %s", err)
	}

	resources := result["resources"].(map[string]interface{})
	limits := resources["limits"].(map[string]interface{})
	if limits["cpu"] != "500m" {
		t.Errorf("expected cpu=500m from cpu-flavor, got %v", limits["cpu"])
	}
	if limits["memory"] != "4Gi" {
		t.Errorf("expected memory=4Gi from memory-flavor, got %v", limits["memory"])
	}
}

func TestMergeFlavors_ResourcesRequestsAndLimitsMerge(t *testing.T) {
	data := []map[string]interface{}{
		{"resources": map[string]interface{}{"limits": map[string]interface{}{"nvidia.com/gpu": "1"}}},
		{"resources": map[string]interface{}{"requests": map[string]interface{}{"memory": "4Gi"}}},
	}

	result, err := MergeFlavors(data, []string{"gpu-flavor", "memory-flavor"})
	if err != nil {
		t.Fatalf("requests and limits from different flavors should merge, got: %s", err)
	}

	resources := result["resources"].(map[string]interface{})
	limits := resources["limits"].(map[string]interface{})
	requests := resources["requests"].(map[string]interface{})
	if limits["nvidia.com/gpu"] != "1" {
		t.Errorf("expected gpu limit from gpu-flavor, got %v", limits["nvidia.com/gpu"])
	}
	if requests["memory"] != "4Gi" {
		t.Errorf("expected memory request from memory-flavor, got %v", requests["memory"])
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

	result, err := MergeFlavors(data, []string{"gpu", "dedicated"})
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

	result, err := MergeFlavors(data, []string{"state-flavor", "cache-flavor"})
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

func TestMergeFlavors_VolumeMountsAppended(t *testing.T) {
	data := []map[string]interface{}{
		{
			"volumeMounts": []interface{}{
				map[string]interface{}{"name": "data", "mountPath": "/data"},
			},
		},
		{
			"volumeMounts": []interface{}{
				map[string]interface{}{"name": "config", "mountPath": "/config"},
			},
		},
	}

	result, err := MergeFlavors(data, []string{"data-flavor", "config-flavor"})
	if err != nil {
		t.Fatal(err)
	}

	mounts, ok := result["volumeMounts"].([]interface{})
	if !ok {
		t.Fatal("volumeMounts missing from result")
	}
	if len(mounts) != 2 {
		t.Errorf("expected 2 volumeMounts (appended), got %d", len(mounts))
	}
}

func TestMergeFlavors_NodeSelectorMergedNoConflict(t *testing.T) {
	data := []map[string]interface{}{
		{"nodeSelector": map[string]interface{}{"accelerator": "nvidia"}},
		{"nodeSelector": map[string]interface{}{"zone": "us-east-1a"}},
	}

	result, err := MergeFlavors(data, []string{"gpu", "zone"})
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

	_, err := MergeFlavors(data, []string{"east", "west"})
	if err == nil {
		t.Error("expected error for conflicting nodeSelector key, got nil")
	}
	if !strings.Contains(err.Error(), "nodeSelector.zone") {
		t.Errorf("error should mention conflicting key path, got: %s", err)
	}
}

func TestMergeFlavors_SidecarMapConflictErrors(t *testing.T) {
	data := []map[string]interface{}{
		{"sidecar": map[string]interface{}{"image": "sidecar:v1"}},
		{"sidecar": map[string]interface{}{"image": "sidecar:v2"}},
	}

	_, err := MergeFlavors(data, []string{"flavor-a", "flavor-b"})
	if err == nil {
		t.Fatal("expected error for sidecar.image conflict, got nil")
	}
	if !strings.Contains(err.Error(), "sidecar.image") {
		t.Errorf("error should mention conflicting key path, got: %s", err)
	}
}

func TestMergeFlavors_SidecarMapMergeDistinctKeys(t *testing.T) {
	data := []map[string]interface{}{
		{"sidecar": map[string]interface{}{"image": "sidecar:v1"}},
		{"sidecar": map[string]interface{}{"resources": map[string]interface{}{"limits": map[string]interface{}{"cpu": "100m"}}}},
	}

	result, err := MergeFlavors(data, []string{"flavor-a", "flavor-b"})
	if err != nil {
		t.Fatal(err)
	}

	sidecar := result["sidecar"].(map[string]interface{})
	if sidecar["image"] != "sidecar:v1" {
		t.Errorf("expected sidecar.image from flavor-a, got %v", sidecar["image"])
	}
	if sidecar["resources"] == nil {
		t.Error("expected sidecar.resources from flavor-b")
	}
}

func TestMergeFlavors_TypeMismatchListVsScalarErrors(t *testing.T) {
	data := []map[string]interface{}{
		{"tolerations": []interface{}{map[string]interface{}{"key": "gpu"}}},
		{"tolerations": "not-a-list"},
	}

	_, err := MergeFlavors(data, []string{"flavor-a", "flavor-b"})
	if err == nil {
		t.Fatal("expected error for type mismatch (list vs scalar), got nil")
	}
	if !strings.Contains(err.Error(), "conflicting types") {
		t.Errorf("error should mention conflicting types, got: %s", err)
	}
}

func TestMergeFlavors_TypeMismatchMapVsScalarErrors(t *testing.T) {
	data := []map[string]interface{}{
		{"scaling": map[string]interface{}{"minReplicas": float64(1)}},
		{"scaling": "not-a-map"},
	}

	_, err := MergeFlavors(data, []string{"flavor-a", "flavor-b"})
	if err == nil {
		t.Fatal("expected error for type mismatch (map vs scalar), got nil")
	}
	if !strings.Contains(err.Error(), "conflicting types") {
		t.Errorf("error should mention conflicting types, got: %s", err)
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
