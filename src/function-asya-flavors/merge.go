package main

import (
	"encoding/json"

	"github.com/crossplane/function-sdk-go/errors"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/util/strategicpatch"
)

// ActorSpecSchema provides strategic merge patch metadata for the AsyncActor spec.
// The corev1.PodSpec embedded in TemplateSchema carries Kubernetes struct tags that
// enable correct list merge semantics:
//   - containers merge by "name"
//   - env vars merge by "name"
//   - tolerations merge by "key"
//   - volumes merge by "name"
//   - volumeMounts merge by "mountPath"
//   - initContainers merge by "name"
//
// Top-level scalar fields (scaling, workload.kind, etc.) use standard deep merge.
type ActorSpecSchema struct {
	Scaling  *ScalingSchema  `json:"scaling,omitempty"`
	Workload *WorkloadSchema `json:"workload,omitempty"`
}

// ScalingSchema mirrors the scaling portion of the AsyncActor spec.
// All fields are scalars, so standard deep merge applies (later values override).
type ScalingSchema struct {
	Enabled         *bool `json:"enabled,omitempty"`
	MinReplicas     *int  `json:"minReplicas,omitempty"`
	MaxReplicas     *int  `json:"maxReplicas,omitempty"`
	PollingInterval *int  `json:"pollingInterval,omitempty"`
	CooldownPeriod  *int  `json:"cooldownPeriod,omitempty"`
	QueueLength     *int  `json:"queueLength,omitempty"`
}

// WorkloadSchema mirrors the workload portion of the AsyncActor spec.
type WorkloadSchema struct {
	Kind     string          `json:"kind,omitempty"`
	Replicas *int            `json:"replicas,omitempty"`
	Template *TemplateSchema `json:"template,omitempty"`
}

// TemplateSchema embeds corev1.PodSpec to inherit Kubernetes strategic merge
// patch annotations for correct list merge behavior.
type TemplateSchema struct {
	Spec corev1.PodSpec `json:"spec,omitempty"`
}

// MergeFlavors applies strategic merge patches sequentially for each flavor's data.
// Flavors are merged left-to-right: later flavors override earlier ones.
func MergeFlavors(flavorData []map[string]interface{}) (map[string]interface{}, error) {
	if len(flavorData) == 0 {
		return map[string]interface{}{}, nil
	}

	base := map[string]interface{}{}
	for i, data := range flavorData {
		var err error
		base, err = ApplyStrategicMerge(base, data)
		if err != nil {
			return nil, errors.Wrapf(err, "cannot apply flavor at index %d", i)
		}
	}

	return base, nil
}

// ApplyStrategicMerge applies a strategic merge patch to the base map using
// ActorSpecSchema for merge strategy metadata.
func ApplyStrategicMerge(base, patch map[string]interface{}) (map[string]interface{}, error) {
	baseJSON, err := json.Marshal(base)
	if err != nil {
		return nil, errors.Wrap(err, "cannot marshal base")
	}

	patchJSON, err := json.Marshal(patch)
	if err != nil {
		return nil, errors.Wrap(err, "cannot marshal patch")
	}

	mergedJSON, err := strategicpatch.StrategicMergePatch(baseJSON, patchJSON, &ActorSpecSchema{})
	if err != nil {
		return nil, errors.Wrap(err, "cannot apply strategic merge patch")
	}

	var result map[string]interface{}
	if err := json.Unmarshal(mergedJSON, &result); err != nil {
		return nil, errors.Wrap(err, "cannot unmarshal merged result")
	}

	return result, nil
}
