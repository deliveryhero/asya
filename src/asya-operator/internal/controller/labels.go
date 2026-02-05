package controller

import (
	"fmt"
	"strings"

	asyav1alpha1 "github.com/asya/operator/api/v1alpha1"
)

var reservedLabelPrefixes = []string{
	"app.kubernetes.io/",
	"asya.sh/",
	"keda.sh/",
	"kubernetes.io/",
}

// propagateLabels merges user labels from AsyncActor CR with operator-managed labels.
// Operator-managed labels take precedence over user labels for reserved prefixes.
// Returns the merged label map.
func propagateLabels(asya *asyav1alpha1.AsyncActor, operatorLabels map[string]string) map[string]string {
	merged := make(map[string]string)

	// Start with user labels from AsyncActor CR
	for k, v := range asya.Labels {
		merged[k] = v
	}

	// Operator labels override user labels for reserved prefixes
	for k, v := range operatorLabels {
		merged[k] = v
	}

	return merged
}

// validateUserLabels checks if user labels use reserved prefixes
// Returns error if any user label uses a reserved prefix
// Exceptions:
// - app.kubernetes.io/managed-by (automatically added by Helm)
// - asya.sh/actor (user-controlled actor identity)
// - asya.sh/flow (user-controlled flow grouping)
func validateUserLabels(labels map[string]string) error {
	for key := range labels {
		// Allow specific exceptions
		if key == "app.kubernetes.io/managed-by" ||
			key == "asya.sh/actor" ||
			key == "asya.sh/flow" {
			continue
		}

		for _, prefix := range reservedLabelPrefixes {
			if strings.HasPrefix(key, prefix) {
				return fmt.Errorf("label key %q uses reserved prefix %q - reserved prefixes are: %v (exceptions: asya.sh/actor, asya.sh/flow)",
					key, prefix, reservedLabelPrefixes)
			}
		}
	}
	return nil
}

// ensureActorLabels ensures required asya.sh/* labels are set on the AsyncActor resource.
// Returns true if labels were modified and need to be persisted.
func ensureActorLabels(asya *asyav1alpha1.AsyncActor) bool {
	if asya.Labels == nil {
		asya.Labels = make(map[string]string)
	}

	modified := false
	actorName := asya.GetActorName()

	// Ensure asya.sh/actor label is set
	if asya.Labels["asya.sh/actor"] != actorName {
		asya.Labels["asya.sh/actor"] = actorName
		modified = true
	}

	return modified
}
