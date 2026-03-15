package main

import (
	"context"
	"testing"

	"github.com/crossplane/function-sdk-go/logging"
	fnv1 "github.com/crossplane/function-sdk-go/proto/v1"
	"google.golang.org/protobuf/types/known/structpb"
)

func TestRunFunction_NoFlavors(t *testing.T) {
	f := &Function{log: logging.NewNopLogger()}

	xr := mustNewStruct(t, map[string]interface{}{
		"apiVersion": "asya.sh/v1alpha1",
		"kind":       "XAsyncActor",
		"spec": map[string]interface{}{
			"actor":     "test-actor",
			"transport": "sqs",
			"image":     "my-app:v1",
			"handler":   "my_module.handle",
		},
	})

	req := &fnv1.RunFunctionRequest{
		Observed: &fnv1.State{
			Composite: &fnv1.Resource{Resource: xr},
		},
	}

	rsp, err := f.RunFunction(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}

	if rsp.Requirements != nil && len(rsp.Requirements.Resources) > 0 {
		t.Error("no requirements should be set when there are no flavors")
	}
}

func TestRunFunction_SetsRequirements(t *testing.T) {
	f := &Function{log: logging.NewNopLogger()}

	xr := mustNewStruct(t, map[string]interface{}{
		"apiVersion": "asya.sh/v1alpha1",
		"kind":       "XAsyncActor",
		"spec": map[string]interface{}{
			"actor":     "test-actor",
			"transport": "sqs",
			"image":     "my-llm:latest",
			"handler":   "model.inference",
			"flavors":   []interface{}{"gpu-t4", "openai-keys"},
		},
	})

	req := &fnv1.RunFunctionRequest{
		Observed: &fnv1.State{Composite: &fnv1.Resource{Resource: xr}},
	}

	rsp, err := f.RunFunction(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}

	if rsp.Requirements == nil || rsp.Requirements.Resources == nil {
		t.Fatal("requirements should be set")
	}
	for _, flavor := range []string{"gpu-t4", "openai-keys"} {
		key := flavorResourceKey(flavor)
		sel, ok := rsp.Requirements.Resources[key]
		if !ok {
			t.Errorf("missing requirement for flavor %q", flavor)
			continue
		}
		if sel.ApiVersion != EnvConfigAPIVersion {
			t.Errorf("flavor %q: apiVersion = %q, want %q", flavor, sel.ApiVersion, EnvConfigAPIVersion)
		}
		matchName := sel.GetMatchName()
		if matchName != flavor {
			t.Errorf("flavor %q: matchName = %q, want %q", flavor, matchName, flavor)
		}
	}
}

func TestRunFunction_MergesSingleFlavor_FlatSpec(t *testing.T) {
	f := &Function{log: logging.NewNopLogger()}

	xr := mustNewStruct(t, map[string]interface{}{
		"apiVersion": "asya.sh/v1alpha1",
		"kind":       "XAsyncActor",
		"spec": map[string]interface{}{
			"actor":     "test-actor",
			"transport": "sqs",
			"image":     "my-model:v1",
			"handler":   "model.inference",
			"flavors":   []interface{}{"gpu-t4"},
		},
	})

	envConfig := mustNewStruct(t, map[string]interface{}{
		"apiVersion": "apiextensions.crossplane.io/v1beta1",
		"kind":       "EnvironmentConfig",
		"metadata": map[string]interface{}{
			"name":   "gpu-t4",
			"labels": map[string]interface{}{"asya.sh/flavor": "gpu-t4"},
		},
		"data": map[string]interface{}{
			"scaling": map[string]interface{}{
				"minReplicas":    float64(1),
				"cooldownPeriod": float64(600),
			},
			"resources": map[string]interface{}{
				"limits": map[string]interface{}{"nvidia.com/gpu": "1"},
			},
			"tolerations": []interface{}{
				map[string]interface{}{"key": "nvidia.com/gpu", "operator": "Exists", "effect": "NoSchedule"},
			},
			"nodeSelector": map[string]interface{}{"accelerator": "nvidia-tesla-t4"},
		},
	})

	req := &fnv1.RunFunctionRequest{
		Observed: &fnv1.State{Composite: &fnv1.Resource{Resource: xr}},
		Desired: &fnv1.State{
			Composite: &fnv1.Resource{Resource: mustNewStruct(t, map[string]interface{}{
				"apiVersion": "asya.sh/v1alpha1",
				"kind":       "XAsyncActor",
			})},
		},
		RequiredResources: map[string]*fnv1.Resources{
			"flavor-gpu-t4": {Items: []*fnv1.Resource{{Resource: envConfig}}},
		},
	}

	rsp, err := f.RunFunction(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}

	resolved := rsp.Desired.Composite.Resource.AsMap()["spec"].(map[string]interface{})

	scaling := resolved["scaling"].(map[string]interface{})
	if scaling["minReplicas"] != float64(1) {
		t.Errorf("minReplicas: got %v, want 1", scaling["minReplicas"])
	}

	if resolved["image"] != "my-model:v1" {
		t.Errorf("image: got %v, want my-model:v1 (actor wins)", resolved["image"])
	}

	resources, ok := resolved["resources"].(map[string]interface{})
	if !ok {
		t.Fatal("resources not found after merge")
	}
	limits := resources["limits"].(map[string]interface{})
	if limits["nvidia.com/gpu"] != "1" {
		t.Errorf("nvidia.com/gpu: got %v, want 1", limits["nvidia.com/gpu"])
	}

	tolerations, ok := resolved["tolerations"].([]interface{})
	if !ok || len(tolerations) == 0 {
		t.Fatal("tolerations not found after merge")
	}
}

func TestRunFunction_ActorEnvReplacesFlavorEnv(t *testing.T) {
	f := &Function{log: logging.NewNopLogger()}

	xr := mustNewStruct(t, map[string]interface{}{
		"apiVersion": "asya.sh/v1alpha1",
		"kind":       "XAsyncActor",
		"spec": map[string]interface{}{
			"actor":     "test-actor",
			"transport": "sqs",
			"image":     "my-app:v1",
			"handler":   "module.handle",
			"flavors":   []interface{}{"base-flavor"},
			"env": []interface{}{
				map[string]interface{}{"name": "LOG_LEVEL", "value": "DEBUG"},
			},
		},
	})

	envConfig := mustNewStruct(t, map[string]interface{}{
		"apiVersion": "apiextensions.crossplane.io/v1beta1",
		"kind":       "EnvironmentConfig",
		"metadata": map[string]interface{}{
			"name":   "base-flavor",
			"labels": map[string]interface{}{"asya.sh/flavor": "base-flavor"},
		},
		"data": map[string]interface{}{
			"env": []interface{}{
				map[string]interface{}{"name": "LOG_LEVEL", "value": "INFO"},
				map[string]interface{}{"name": "FLAVOR_VAR", "value": "from-flavor"},
			},
		},
	})

	req := &fnv1.RunFunctionRequest{
		Observed: &fnv1.State{Composite: &fnv1.Resource{Resource: xr}},
		Desired: &fnv1.State{
			Composite: &fnv1.Resource{Resource: mustNewStruct(t, map[string]interface{}{
				"apiVersion": "asya.sh/v1alpha1",
				"kind":       "XAsyncActor",
			})},
		},
		RequiredResources: map[string]*fnv1.Resources{
			"flavor-base-flavor": {Items: []*fnv1.Resource{{Resource: envConfig}}},
		},
	}

	rsp, err := f.RunFunction(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}

	resolved := rsp.Desired.Composite.Resource.AsMap()["spec"].(map[string]interface{})
	envs, ok := resolved["env"].([]interface{})
	if !ok {
		t.Fatal("env missing from resolved spec")
	}

	// Actor's env replaces flavor's env entirely (actor inline wins)
	if len(envs) != 1 {
		t.Errorf("expected 1 env var (actor replaces flavor), got %d: %v", len(envs), envs)
	}
	env := envs[0].(map[string]interface{})
	if env["value"] != "DEBUG" {
		t.Errorf("LOG_LEVEL: got %v, want DEBUG (actor wins)", env["value"])
	}
}

func TestRunFunction_FlavorConflictReturnsError(t *testing.T) {
	f := &Function{log: logging.NewNopLogger()}

	xr := mustNewStruct(t, map[string]interface{}{
		"apiVersion": "asya.sh/v1alpha1",
		"kind":       "XAsyncActor",
		"spec": map[string]interface{}{
			"actor":     "test-actor",
			"transport": "sqs",
			"image":     "my-app:v1",
			"handler":   "module.handle",
			"flavors":   []interface{}{"flavor-a", "flavor-b"},
		},
	})

	envConfigA := mustNewStruct(t, map[string]interface{}{
		"apiVersion": "apiextensions.crossplane.io/v1beta1",
		"kind":       "EnvironmentConfig",
		"metadata": map[string]interface{}{
			"name":   "flavor-a",
			"labels": map[string]interface{}{"asya.sh/flavor": "flavor-a"},
		},
		"data": map[string]interface{}{
			"scaling": map[string]interface{}{"minReplicas": float64(1)},
		},
	})
	envConfigB := mustNewStruct(t, map[string]interface{}{
		"apiVersion": "apiextensions.crossplane.io/v1beta1",
		"kind":       "EnvironmentConfig",
		"metadata": map[string]interface{}{
			"name":   "flavor-b",
			"labels": map[string]interface{}{"asya.sh/flavor": "flavor-b"},
		},
		"data": map[string]interface{}{
			"scaling": map[string]interface{}{"minReplicas": float64(2)},
		},
	})

	req := &fnv1.RunFunctionRequest{
		Observed: &fnv1.State{Composite: &fnv1.Resource{Resource: xr}},
		Desired: &fnv1.State{
			Composite: &fnv1.Resource{Resource: mustNewStruct(t, map[string]interface{}{
				"apiVersion": "asya.sh/v1alpha1",
				"kind":       "XAsyncActor",
			})},
		},
		RequiredResources: map[string]*fnv1.Resources{
			"flavor-flavor-a": {Items: []*fnv1.Resource{{Resource: envConfigA}}},
			"flavor-flavor-b": {Items: []*fnv1.Resource{{Resource: envConfigB}}},
		},
	}

	rsp, err := f.RunFunction(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}

	// The function should mark the response as Fatal
	if rsp.Results == nil {
		t.Fatal("expected fatal result for flavor conflict, got empty results")
	}
	hasFatal := false
	for _, r := range rsp.Results {
		if r.Severity == fnv1.Severity_SEVERITY_FATAL {
			hasFatal = true
			break
		}
	}
	if !hasFatal {
		t.Error("expected SEVERITY_FATAL result for flavor scaling conflict")
	}
}

func TestRunFunction_PreservesDesiredState(t *testing.T) {
	f := &Function{log: logging.NewNopLogger()}

	xr := mustNewStruct(t, map[string]interface{}{
		"apiVersion": "asya.sh/v1alpha1",
		"kind":       "XAsyncActor",
		"spec": map[string]interface{}{
			"actor":     "test-actor",
			"transport": "sqs",
			"image":     "my-app:v1",
			"handler":   "module.handle",
		},
	})

	desiredXR := mustNewStruct(t, map[string]interface{}{
		"apiVersion": "asya.sh/v1alpha1",
		"kind":       "XAsyncActor",
		"status":     map[string]interface{}{"phase": "Creating"},
	})

	req := &fnv1.RunFunctionRequest{
		Observed: &fnv1.State{Composite: &fnv1.Resource{Resource: xr}},
		Desired:  &fnv1.State{Composite: &fnv1.Resource{Resource: desiredXR}},
	}

	rsp, err := f.RunFunction(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}

	if rsp.Desired == nil || rsp.Desired.Composite == nil {
		t.Fatal("desired state should be preserved")
	}
	status := rsp.Desired.Composite.Resource.AsMap()["status"].(map[string]interface{})
	if status["phase"] != "Creating" {
		t.Errorf("desired phase should be preserved, got %v", status["phase"])
	}
}

// mustNewStruct creates a structpb.Struct from a Go map, failing the test on error.
func mustNewStruct(t *testing.T, m map[string]interface{}) *structpb.Struct {
	t.Helper()
	s, err := structpb.NewStruct(m)
	if err != nil {
		t.Fatalf("cannot create struct: %v", err)
	}
	return s
}
