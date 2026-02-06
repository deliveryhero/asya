package webhook

import (
	"encoding/json"
	"fmt"

	"github.com/mattbaird/jsonpatch"
)

// createJSONPatch creates an RFC 6902 JSON Patch from the original and mutated JSON documents.
func createJSONPatch(original, mutated []byte) ([]byte, error) {
	ops, err := jsonpatch.CreatePatch(original, mutated)
	if err != nil {
		return nil, fmt.Errorf("failed to create JSON patch: %w", err)
	}
	return json.Marshal(ops)
}
