package webhook

import (
	"encoding/json"
	"fmt"

	jsonpatch "github.com/evanphx/json-patch/v5"
)

// createJSONPatch creates a JSON patch from the original and mutated JSON
func createJSONPatch(original, mutated []byte) ([]byte, error) {
	patch, err := jsonpatch.CreateMergePatch(original, mutated)
	if err != nil {
		return nil, fmt.Errorf("failed to create merge patch: %w", err)
	}

	// Convert merge patch to JSON Patch format
	// The Kubernetes admission controller expects RFC 6902 JSON Patch
	return convertMergePatchToJSONPatch(original, patch)
}

// convertMergePatchToJSONPatch converts a merge patch to a JSON Patch (RFC 6902)
func convertMergePatchToJSONPatch(original, mergePatch []byte) ([]byte, error) {
	// Apply the merge patch to get the final result
	result, err := jsonpatch.MergePatch(original, mergePatch)
	if err != nil {
		return nil, fmt.Errorf("failed to apply merge patch: %w", err)
	}

	// Create a JSON Patch by comparing original and result
	var origMap, resultMap map[string]interface{}
	if err := json.Unmarshal(original, &origMap); err != nil {
		return nil, fmt.Errorf("failed to unmarshal original: %w", err)
	}
	if err := json.Unmarshal(result, &resultMap); err != nil {
		return nil, fmt.Errorf("failed to unmarshal result: %w", err)
	}

	// Build JSON Patch operations
	var ops []map[string]interface{}
	buildPatchOps("", origMap, resultMap, &ops)

	return json.Marshal(ops)
}

// buildPatchOps recursively builds JSON Patch operations
func buildPatchOps(path string, original, mutated map[string]interface{}, ops *[]map[string]interface{}) {
	// Check for added or changed keys
	for key, newValue := range mutated {
		keyPath := path + "/" + escapeJSONPointer(key)

		origValue, exists := original[key]
		if !exists {
			// Key was added
			*ops = append(*ops, map[string]interface{}{
				"op":    "add",
				"path":  keyPath,
				"value": newValue,
			})
			continue
		}

		// Key exists in both, check if changed
		origMap, origIsMap := origValue.(map[string]interface{})
		newMap, newIsMap := newValue.(map[string]interface{})

		if origIsMap && newIsMap {
			// Recurse into nested maps
			buildPatchOps(keyPath, origMap, newMap, ops)
		} else if !jsonEqual(origValue, newValue) {
			// Value changed
			*ops = append(*ops, map[string]interface{}{
				"op":    "replace",
				"path":  keyPath,
				"value": newValue,
			})
		}
	}

	// Check for removed keys
	for key := range original {
		if _, exists := mutated[key]; !exists {
			keyPath := path + "/" + escapeJSONPointer(key)
			*ops = append(*ops, map[string]interface{}{
				"op":   "remove",
				"path": keyPath,
			})
		}
	}
}

// escapeJSONPointer escapes special characters in JSON Pointer (RFC 6901)
func escapeJSONPointer(s string) string {
	// Replace ~ with ~0 first, then / with ~1
	result := ""
	for _, c := range s {
		switch c {
		case '~':
			result += "~0"
		case '/':
			result += "~1"
		default:
			result += string(c)
		}
	}
	return result
}

// jsonEqual checks if two JSON values are equal
func jsonEqual(a, b interface{}) bool {
	aBytes, _ := json.Marshal(a)
	bBytes, _ := json.Marshal(b)
	return string(aBytes) == string(bBytes)
}
