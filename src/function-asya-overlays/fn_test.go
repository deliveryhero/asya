package main

import (
	"context"
	"testing"

	"github.com/crossplane/function-sdk-go/logging"
	fnv1 "github.com/crossplane/function-sdk-go/proto/v1"
	"google.golang.org/protobuf/types/known/structpb"
)

func TestRunFunction_NoOverlays(t *testing.T) {
	f := &Function{log: logging.NewNopLogger()}

	xr := mustNewStruct(t, map[string]interface{}{
		"apiVersion": "asya.sh/v1alpha1",
		"kind":       "XAsyncActor",
		"spec": map[string]interface{}{
			"actor":     "test-actor",
			"transport": "sqs",
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

	// No context key should be set when there are no overlays
	if rsp.GetContext() != nil {
		fields := rsp.GetContext().GetFields()
		if _, ok := fields[ContextKeyResolvedSpec]; ok {
			t.Error("context key should not be set when there are no overlays")
		}
	}

	// No requirements should be set
	if rsp.Requirements != nil && len(rsp.Requirements.Resources) > 0 {
		t.Error("no requirements should be set when there are no overlays")
	}
}

func TestRunFunction_EmptyOverlaysArray(t *testing.T) {
	f := &Function{log: logging.NewNopLogger()}

	xr := mustNewStruct(t, map[string]interface{}{
		"apiVersion": "asya.sh/v1alpha1",
		"kind":       "XAsyncActor",
		"spec": map[string]interface{}{
			"actor":     "test-actor",
			"transport": "sqs",
			"overlays":  []interface{}{},
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

	if rsp.GetContext() != nil {
		fields := rsp.GetContext().GetFields()
		if _, ok := fields[ContextKeyResolvedSpec]; ok {
			t.Error("context key should not be set for empty overlays array")
		}
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
			"overlays":  []interface{}{"gpu-t4", "openai-keys"},
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

	// Requirements should be set for both overlays
	if rsp.Requirements == nil || rsp.Requirements.Resources == nil {
		t.Fatal("requirements should be set")
	}

	for _, overlay := range []string{"gpu-t4", "openai-keys"} {
		key := overlayResourceKey(overlay)
		sel, ok := rsp.Requirements.Resources[key]
		if !ok {
			t.Errorf("missing requirement for overlay %q", overlay)
			continue
		}

		if sel.ApiVersion != EnvConfigAPIVersion {
			t.Errorf("overlay %q: apiVersion = %q, want %q", overlay, sel.ApiVersion, EnvConfigAPIVersion)
		}
		if sel.Kind != EnvConfigKind {
			t.Errorf("overlay %q: kind = %q, want %q", overlay, sel.Kind, EnvConfigKind)
		}

		matchLabels := sel.GetMatchLabels()
		if matchLabels == nil {
			t.Errorf("overlay %q: missing matchLabels", overlay)
			continue
		}

		label, ok := matchLabels.Labels[OverlayLabel]
		if !ok || label != overlay {
			t.Errorf("overlay %q: label = %q, want %q", overlay, label, overlay)
		}
	}
}

func TestRunFunction_WaitsForResources(t *testing.T) {
	f := &Function{log: logging.NewNopLogger()}

	xr := mustNewStruct(t, map[string]interface{}{
		"apiVersion": "asya.sh/v1alpha1",
		"kind":       "XAsyncActor",
		"spec": map[string]interface{}{
			"actor":     "test-actor",
			"transport": "sqs",
			"overlays":  []interface{}{"gpu-t4"},
		},
	})

	req := &fnv1.RunFunctionRequest{
		Observed: &fnv1.State{
			Composite: &fnv1.Resource{Resource: xr},
		},
		// No RequiredResources yet
	}

	rsp, err := f.RunFunction(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}

	// Context key should NOT be set since resources aren't available yet
	if rsp.GetContext() != nil {
		fields := rsp.GetContext().GetFields()
		if _, ok := fields[ContextKeyResolvedSpec]; ok {
			t.Error("context key should not be set while waiting for resources")
		}
	}

	// Requirements should still be set
	if rsp.Requirements == nil || len(rsp.Requirements.Resources) == 0 {
		t.Error("requirements should be set even while waiting")
	}
}

func TestRunFunction_MergesSingleOverlay(t *testing.T) {
	f := &Function{log: logging.NewNopLogger()}

	xr := mustNewStruct(t, map[string]interface{}{
		"apiVersion": "asya.sh/v1alpha1",
		"kind":       "XAsyncActor",
		"spec": map[string]interface{}{
			"actor":     "test-actor",
			"transport": "sqs",
			"overlays":  []interface{}{"gpu-t4"},
			"workload": map[string]interface{}{
				"template": map[string]interface{}{
					"spec": map[string]interface{}{
						"containers": []interface{}{
							map[string]interface{}{
								"name":  "asya-runtime",
								"image": "my-model:v1",
							},
						},
					},
				},
			},
		},
	})

	envConfig := mustNewStruct(t, map[string]interface{}{
		"apiVersion": "apiextensions.crossplane.io/v1beta1",
		"kind":       "EnvironmentConfig",
		"metadata": map[string]interface{}{
			"name": "gpu-t4",
			"labels": map[string]interface{}{
				"asya.sh/overlay": "gpu-t4",
			},
		},
		"data": map[string]interface{}{
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
								"resources": map[string]interface{}{
									"limits": map[string]interface{}{
										"nvidia.com/gpu": "1",
									},
								},
							},
						},
					},
				},
			},
		},
	})

	req := &fnv1.RunFunctionRequest{
		Observed: &fnv1.State{
			Composite: &fnv1.Resource{Resource: xr},
		},
		RequiredResources: map[string]*fnv1.Resources{
			"overlay-gpu-t4": {
				Items: []*fnv1.Resource{
					{Resource: envConfig},
				},
			},
		},
	}

	rsp, err := f.RunFunction(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}

	// Context key should be set with the resolved spec
	resolvedValue := getContextValue(t, rsp, ContextKeyResolvedSpec)
	resolved := resolvedValue.GetStructValue().AsMap()

	// Overlay's scaling should be present, but actor's minReplicas not set so overlay's value preserved
	scaling := resolved["scaling"].(map[string]interface{})
	if scaling["minReplicas"] != float64(1) {
		t.Errorf("minReplicas: got %v, want 1 (from overlay)", scaling["minReplicas"])
	}

	// Actor's image should be present (inline override)
	containers := resolved["workload"].(map[string]interface{})["template"].(map[string]interface{})["spec"].(map[string]interface{})["containers"].([]interface{})
	container := containers[0].(map[string]interface{})
	if container["image"] != "my-model:v1" {
		t.Errorf("image: got %v, want my-model:v1 (actor inline override)", container["image"])
	}

	// Overlay's GPU resources should also be present (merged)
	resources := container["resources"].(map[string]interface{})
	limits := resources["limits"].(map[string]interface{})
	if limits["nvidia.com/gpu"] != "1" {
		t.Errorf("nvidia.com/gpu: got %v, want 1 (from overlay)", limits["nvidia.com/gpu"])
	}
}

func TestRunFunction_MissingOverlayData(t *testing.T) {
	f := &Function{log: logging.NewNopLogger()}

	xr := mustNewStruct(t, map[string]interface{}{
		"apiVersion": "asya.sh/v1alpha1",
		"kind":       "XAsyncActor",
		"spec": map[string]interface{}{
			"actor":     "test-actor",
			"transport": "sqs",
			"overlays":  []interface{}{"empty-overlay"},
			"workload": map[string]interface{}{
				"template": map[string]interface{}{
					"spec": map[string]interface{}{
						"containers": []interface{}{
							map[string]interface{}{
								"name":  "asya-runtime",
								"image": "my-app:v1",
							},
						},
					},
				},
			},
		},
	})

	// EnvironmentConfig without a data field
	envConfig := mustNewStruct(t, map[string]interface{}{
		"apiVersion": "apiextensions.crossplane.io/v1beta1",
		"kind":       "EnvironmentConfig",
		"metadata": map[string]interface{}{
			"name": "empty-overlay",
		},
	})

	req := &fnv1.RunFunctionRequest{
		Observed: &fnv1.State{
			Composite: &fnv1.Resource{Resource: xr},
		},
		RequiredResources: map[string]*fnv1.Resources{
			"overlay-empty-overlay": {
				Items: []*fnv1.Resource{
					{Resource: envConfig},
				},
			},
		},
	}

	rsp, err := f.RunFunction(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}

	// Should not fail; context should be set with actor's own spec
	resolvedValue := getContextValue(t, rsp, ContextKeyResolvedSpec)
	resolved := resolvedValue.GetStructValue().AsMap()

	containers := resolved["workload"].(map[string]interface{})["template"].(map[string]interface{})["spec"].(map[string]interface{})["containers"].([]interface{})
	container := containers[0].(map[string]interface{})
	if container["image"] != "my-app:v1" {
		t.Errorf("image: got %v, want my-app:v1", container["image"])
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
		},
	})

	// Simulate a previous function having set desired state
	desiredXR := mustNewStruct(t, map[string]interface{}{
		"apiVersion": "asya.sh/v1alpha1",
		"kind":       "XAsyncActor",
		"status": map[string]interface{}{
			"phase": "Creating",
		},
	})

	req := &fnv1.RunFunctionRequest{
		Observed: &fnv1.State{
			Composite: &fnv1.Resource{Resource: xr},
		},
		Desired: &fnv1.State{
			Composite: &fnv1.Resource{Resource: desiredXR},
		},
	}

	rsp, err := f.RunFunction(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}

	// Desired state from previous function should be preserved
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

// getContextValue retrieves a value from the response context, failing the test if absent.
func getContextValue(t *testing.T, rsp *fnv1.RunFunctionResponse, key string) *structpb.Value {
	t.Helper()

	ctx := rsp.GetContext()
	if ctx == nil {
		t.Fatalf("response context is nil, expected key %q", key)
	}

	fields := ctx.GetFields()
	v, ok := fields[key]
	if !ok {
		t.Fatalf("context key %q not found", key)
	}

	return v
}
