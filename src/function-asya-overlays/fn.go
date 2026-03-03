package main

import (
	"context"

	"github.com/crossplane/function-sdk-go/errors"
	"github.com/crossplane/function-sdk-go/logging"
	fnv1 "github.com/crossplane/function-sdk-go/proto/v1"
	"github.com/crossplane/function-sdk-go/request"
	"github.com/crossplane/function-sdk-go/resource"
	"github.com/crossplane/function-sdk-go/response"
	"google.golang.org/protobuf/types/known/structpb"
)

const (
	// ContextKeyResolvedSpec is the context key where the resolved (merged) spec is stored.
	// Downstream composition functions (e.g., Go templates) read from this key
	// instead of the raw XR spec when overlays are active.
	ContextKeyResolvedSpec = "asya/resolved-spec"

	// EnvConfigAPIVersion is the Crossplane EnvironmentConfig API version.
	EnvConfigAPIVersion = "apiextensions.crossplane.io/v1beta1"

	// EnvConfigKind is the Kubernetes kind for EnvironmentConfig resources.
	EnvConfigKind = "EnvironmentConfig"

	// OverlayLabel is the label key used to identify overlay EnvironmentConfigs.
	OverlayLabel = "asya.sh/overlay"
)

// Function implements the function-asya-overlays composition function.
type Function struct {
	fnv1.UnimplementedFunctionRunnerServiceServer
	log logging.Logger
}

// RunFunction resolves overlay EnvironmentConfigs and merges them into a unified spec.
//
// The function operates in two phases within Crossplane's reconciliation loop:
//  1. Request phase: reads spec.overlays from the XR and sets resource requirements
//     for each overlay's EnvironmentConfig (matched by label asya.sh/overlay=<name>).
//  2. Merge phase: once Crossplane provides the EnvironmentConfigs, applies strategic
//     merge patch in spec.overlays order, then applies the actor's inline spec as the
//     final override. The resolved spec is written to the context key asya/resolved-spec.
func (f *Function) RunFunction(_ context.Context, req *fnv1.RunFunctionRequest) (*fnv1.RunFunctionResponse, error) {
	f.log.Info("Running function", "tag", req.GetMeta().GetTag())

	rsp := response.To(req, response.DefaultTTL)

	if err := f.run(req, rsp); err != nil {
		response.Fatal(rsp, err)
	}

	return rsp, nil
}

// run contains the core overlay resolution logic. Errors are returned to
// RunFunction which handles them uniformly via response.Fatal.
func (f *Function) run(req *fnv1.RunFunctionRequest, rsp *fnv1.RunFunctionResponse) error {
	oxr, err := request.GetObservedCompositeResource(req)
	if err != nil {
		return errors.Wrapf(err, "cannot get observed composite resource")
	}

	overlays := getOverlays(oxr)
	if len(overlays) == 0 {
		f.log.Debug("No overlays specified, skipping")
		return nil
	}

	f.log.Info("Processing overlays", "overlays", overlays)

	// Always set requirements so Crossplane fetches the EnvironmentConfigs.
	setRequirements(rsp, overlays)

	required, err := request.GetRequiredResources(req)
	if err != nil {
		return errors.Wrapf(err, "cannot get required resources")
	}

	if !allOverlaysAvailable(required, overlays) {
		f.log.Info("Waiting for overlay EnvironmentConfigs")
		response.Normalf(rsp, "Waiting for %d overlay EnvironmentConfigs", len(overlays))
		return nil
	}

	overlayData := extractOverlayData(required, overlays, f.log)

	merged, err := MergeOverlays(overlayData)
	if err != nil {
		return errors.Wrapf(err, "cannot merge overlays")
	}

	actorSpec := extractActorInlineSpec(oxr)
	if actorSpec != nil {
		merged, err = ApplyStrategicMerge(merged, actorSpec)
		if err != nil {
			return errors.Wrapf(err, "cannot apply actor inline spec override")
		}
	}

	value, err := structpb.NewValue(merged)
	if err != nil {
		return errors.Wrapf(err, "cannot convert resolved spec to context value")
	}

	response.SetContextKey(rsp, ContextKeyResolvedSpec, value)
	response.Normalf(rsp, "Applied %d overlays: %v", len(overlays), overlays)
	f.log.Info("Overlays applied", "count", len(overlays))

	return nil
}

// getOverlays reads spec.overlays from the observed composite resource.
func getOverlays(oxr *resource.Composite) []string {
	spec, ok := oxr.Resource.Object["spec"].(map[string]interface{})
	if !ok {
		return nil
	}

	overlaysRaw, ok := spec["overlays"]
	if !ok {
		return nil
	}

	overlaysSlice, ok := overlaysRaw.([]interface{})
	if !ok {
		return nil
	}

	overlays := make([]string, 0, len(overlaysSlice))
	for _, o := range overlaysSlice {
		if s, ok := o.(string); ok {
			overlays = append(overlays, s)
		}
	}

	return overlays
}

// overlayResourceKey returns the requirements map key for a given overlay name.
func overlayResourceKey(overlay string) string {
	return "overlay-" + overlay
}

// setRequirements populates resource requirements on the response so Crossplane
// fetches the EnvironmentConfig for each overlay by label.
func setRequirements(rsp *fnv1.RunFunctionResponse, overlays []string) {
	if rsp.Requirements == nil {
		rsp.Requirements = &fnv1.Requirements{}
	}
	if rsp.Requirements.Resources == nil {
		rsp.Requirements.Resources = make(map[string]*fnv1.ResourceSelector)
	}

	for _, overlay := range overlays {
		rsp.Requirements.Resources[overlayResourceKey(overlay)] = &fnv1.ResourceSelector{
			ApiVersion: EnvConfigAPIVersion,
			Kind:       EnvConfigKind,
			Match: &fnv1.ResourceSelector_MatchLabels{
				MatchLabels: &fnv1.MatchLabels{
					Labels: map[string]string{
						OverlayLabel: overlay,
					},
				},
			},
		}
	}
}

// allOverlaysAvailable returns true if every requested overlay has at least one
// matching EnvironmentConfig in the required resources.
func allOverlaysAvailable(required map[string][]resource.Required, overlays []string) bool {
	for _, overlay := range overlays {
		resources, ok := required[overlayResourceKey(overlay)]
		if !ok || len(resources) == 0 {
			return false
		}
	}

	return true
}

// extractOverlayData reads the data field from each overlay's EnvironmentConfig
// in spec.overlays order, returning a slice of partial AsyncActor specs.
func extractOverlayData(required map[string][]resource.Required, overlays []string, log logging.Logger) []map[string]interface{} {
	result := make([]map[string]interface{}, 0, len(overlays))

	for _, overlay := range overlays {
		resources := required[overlayResourceKey(overlay)]
		if len(resources) == 0 {
			continue
		}

		if len(resources) > 1 {
			log.Info("Multiple EnvironmentConfigs match overlay label, using first", "overlay", overlay, "count", len(resources))
		}

		envConfig := resources[0].Resource
		dataRaw, ok := envConfig.Object["data"]
		if !ok {
			log.Info("Overlay EnvironmentConfig has no data field, skipping", "overlay", overlay)
			continue
		}

		data, ok := dataRaw.(map[string]interface{})
		if !ok {
			log.Info("Overlay EnvironmentConfig data is not a map, skipping", "overlay", overlay)
			continue
		}

		result = append(result, data)
	}

	return result
}

// extractActorInlineSpec returns the overlay-mergeable fields from the XR spec
// (scaling, workload). These are applied as the final override so the actor's
// own configuration always wins over overlay values.
func extractActorInlineSpec(oxr *resource.Composite) map[string]interface{} {
	spec, ok := oxr.Resource.Object["spec"].(map[string]interface{})
	if !ok {
		return nil
	}

	result := make(map[string]interface{})
	for _, field := range []string{"scaling", "workload"} {
		if v, ok := spec[field]; ok {
			result[field] = v
		}
	}

	if len(result) == 0 {
		return nil
	}

	return result
}
