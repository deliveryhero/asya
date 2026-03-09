package main

import (
	"context"

	"github.com/crossplane/function-sdk-go/errors"
	"github.com/crossplane/function-sdk-go/logging"
	fnv1 "github.com/crossplane/function-sdk-go/proto/v1"
	"github.com/crossplane/function-sdk-go/request"
	"github.com/crossplane/function-sdk-go/resource"
	"github.com/crossplane/function-sdk-go/response"
)

const (
	// EnvConfigAPIVersion is the Crossplane EnvironmentConfig API version.
	EnvConfigAPIVersion = "apiextensions.crossplane.io/v1beta1"

	// EnvConfigKind is the Kubernetes kind for EnvironmentConfig resources.
	EnvConfigKind = "EnvironmentConfig"

	// FlavorLabel is the label key used to identify flavor EnvironmentConfigs.
	FlavorLabel = "asya.sh/flavor"
)

// infrastructureFields are spec fields managed by the composition pipeline,
// not by flavors. These are excluded from the actor-wins override.
var infrastructureFields = map[string]bool{
	"actor":             true,
	"transport":         true,
	"flavors":           true,
	"region":            true,
	"gcpProject":        true,
	"providerConfigRef": true,
	"irsa":              true,
}

// Function implements the function-asya-flavors composition function.
type Function struct {
	fnv1.UnimplementedFunctionRunnerServiceServer
	log logging.Logger
}

// RunFunction resolves flavor EnvironmentConfigs and merges them into a unified spec.
//
// The function operates in two phases within Crossplane's reconciliation loop:
//  1. Request phase: reads spec.flavors from the XR and sets resource requirements
//     for each flavor's EnvironmentConfig (matched by label asya.sh/flavor=<name>).
//  2. Merge phase: once Crossplane provides the EnvironmentConfigs, applies deep
//     merge in spec.flavors order, then applies the actor's inline spec as the
//     final override. The resolved spec is written back onto the XR's desired state.
func (f *Function) RunFunction(_ context.Context, req *fnv1.RunFunctionRequest) (*fnv1.RunFunctionResponse, error) {
	f.log.Info("Running function", "tag", req.GetMeta().GetTag())

	rsp := response.To(req, response.DefaultTTL)

	if err := f.run(req, rsp); err != nil {
		response.Fatal(rsp, err)
	}

	return rsp, nil
}

// run contains the core flavor resolution logic. Errors are returned to
// RunFunction which handles them uniformly via response.Fatal.
func (f *Function) run(req *fnv1.RunFunctionRequest, rsp *fnv1.RunFunctionResponse) error {
	oxr, err := request.GetObservedCompositeResource(req)
	if err != nil {
		return errors.Wrapf(err, "cannot get observed composite resource")
	}

	flavors := getFlavors(oxr)
	if len(flavors) == 0 {
		f.log.Debug("No flavors specified, skipping")
		return nil
	}

	f.log.Info("Processing flavors", "flavors", flavors)

	// Always set requirements so Crossplane fetches the EnvironmentConfigs.
	setRequirements(rsp, flavors)

	required, err := request.GetRequiredResources(req)
	if err != nil {
		return errors.Wrapf(err, "cannot get required resources")
	}

	if !allFlavorsAvailable(required, flavors) {
		f.log.Info("Waiting for flavor EnvironmentConfigs")
		response.Normalf(rsp, "Waiting for %d flavor EnvironmentConfigs", len(flavors))
		return nil
	}

	flavorData := extractFlavorData(required, flavors, f.log)

	merged := MergeFlavors(flavorData)

	// Filter infrastructure fields from flavor data
	for k := range infrastructureFields {
		delete(merged, k)
	}

	actorSpec := extractActorInlineSpec(oxr)
	if actorSpec != nil {
		merged = DeepMerge(merged, actorSpec)
	}

	dxr, err := request.GetDesiredCompositeResource(req)
	if err != nil {
		return errors.Wrapf(err, "cannot get desired composite resource")
	}

	// Build complete spec from infrastructure fields + resolved flavors.
	// Only infrastructure fields are carried from observed spec to avoid
	// "sticky" flavor data: if a flavor is removed from spec.flavors,
	// its fields should not persist from the previous observed state.
	oxrSpec, _ := oxr.Resource.Object["spec"].(map[string]interface{})
	infraOnly := make(map[string]interface{})
	for k := range infrastructureFields {
		if v, ok := oxrSpec[k]; ok {
			infraOnly[k] = v
		}
	}
	completeSpec := DeepMerge(infraOnly, merged)

	dxr.Resource.Object["spec"] = completeSpec

	if err := response.SetDesiredCompositeResource(rsp, dxr); err != nil {
		return errors.Wrapf(err, "cannot set desired composite resource")
	}

	response.Normalf(rsp, "Applied %d flavors: %v", len(flavors), flavors)
	f.log.Info("Flavors applied", "count", len(flavors))

	return nil
}

// getFlavors reads spec.flavors from the observed composite resource.
func getFlavors(oxr *resource.Composite) []string {
	spec, ok := oxr.Resource.Object["spec"].(map[string]interface{})
	if !ok {
		return nil
	}

	flavorsRaw, ok := spec["flavors"]
	if !ok {
		return nil
	}

	flavorsSlice, ok := flavorsRaw.([]interface{})
	if !ok {
		return nil
	}

	flavors := make([]string, 0, len(flavorsSlice))
	for _, o := range flavorsSlice {
		if s, ok := o.(string); ok {
			flavors = append(flavors, s)
		}
	}

	return flavors
}

// flavorResourceKey returns the requirements map key for a given flavor name.
func flavorResourceKey(flavor string) string {
	return "flavor-" + flavor
}

// setRequirements populates resource requirements on the response so Crossplane
// fetches the EnvironmentConfig for each flavor by label.
func setRequirements(rsp *fnv1.RunFunctionResponse, flavors []string) {
	if rsp.Requirements == nil {
		rsp.Requirements = &fnv1.Requirements{}
	}
	if rsp.Requirements.Resources == nil {
		rsp.Requirements.Resources = make(map[string]*fnv1.ResourceSelector)
	}

	for _, flavor := range flavors {
		rsp.Requirements.Resources[flavorResourceKey(flavor)] = &fnv1.ResourceSelector{
			ApiVersion: EnvConfigAPIVersion,
			Kind:       EnvConfigKind,
			Match: &fnv1.ResourceSelector_MatchLabels{
				MatchLabels: &fnv1.MatchLabels{
					Labels: map[string]string{
						FlavorLabel: flavor,
					},
				},
			},
		}
	}
}

// allFlavorsAvailable returns true if every requested flavor has at least one
// matching EnvironmentConfig in the required resources.
func allFlavorsAvailable(required map[string][]resource.Required, flavors []string) bool {
	for _, flavor := range flavors {
		resources, ok := required[flavorResourceKey(flavor)]
		if !ok || len(resources) == 0 {
			return false
		}
	}

	return true
}

// extractFlavorData reads the data field from each flavor's EnvironmentConfig
// in spec.flavors order, returning a slice of partial AsyncActor specs.
func extractFlavorData(required map[string][]resource.Required, flavors []string, log logging.Logger) []map[string]interface{} {
	result := make([]map[string]interface{}, 0, len(flavors))

	for _, flavor := range flavors {
		resources := required[flavorResourceKey(flavor)]
		if len(resources) == 0 {
			continue
		}

		if len(resources) > 1 {
			log.Info("Multiple EnvironmentConfigs match flavor label, using first", "flavor", flavor, "count", len(resources))
		}

		envConfig := resources[0].Resource
		dataRaw, ok := envConfig.Object["data"]
		if !ok {
			log.Info("Flavor EnvironmentConfig has no data field, skipping", "flavor", flavor)
			continue
		}

		data, ok := dataRaw.(map[string]interface{})
		if !ok {
			log.Info("Flavor EnvironmentConfig data is not a map, skipping", "flavor", flavor)
			continue
		}

		result = append(result, data)
	}

	return result
}

// extractActorInlineSpec returns all flavor-mergeable fields from the XR spec.
// Infrastructure fields are excluded. These are applied as the final override
// so the actor's own configuration always wins over flavor values.
func extractActorInlineSpec(oxr *resource.Composite) map[string]interface{} {
	spec, ok := oxr.Resource.Object["spec"].(map[string]interface{})
	if !ok {
		return nil
	}

	result := make(map[string]interface{})
	for k, v := range spec {
		if !infrastructureFields[k] {
			result[k] = v
		}
	}

	if len(result) == 0 {
		return nil
	}

	return result
}
