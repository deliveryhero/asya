package main

import "fmt"

// appendListFields are spec fields whose values (lists) are concatenated across flavors.
var appendListFields = map[string]bool{
	"tolerations": true,
	"stateProxy":  true,
	"secretRefs":  true,
	"volumes":     true,
}

// mapMergeFields are spec fields whose values (maps) have keys merged; same key in
// two flavors is a conflict error.
var mapMergeFields = map[string]bool{
	"nodeSelector": true,
}

// conflictOnlyFields are fields where only one flavor may provide a value; if two
// flavors both define the field, MergeFlavors returns an error.
var conflictOnlyFields = map[string]bool{
	"scaling":   true,
	"resources": true,
}

// MergeFlavors merges flavor data sequentially with type-aware semantics:
//   - appendListFields: concatenated across all flavors
//   - mapMergeFields: keys merged; conflict returns error
//   - conflictOnlyFields: only one flavor may define the field; conflict returns error
//   - all other fields: last flavor wins
func MergeFlavors(flavorData []map[string]interface{}) (map[string]interface{}, error) {
	result := make(map[string]interface{})

	for _, flavor := range flavorData {
		for k, v := range flavor {
			existing, exists := result[k]

			switch {
			case appendListFields[k]:
				result[k] = appendList(existing, v)

			case mapMergeFields[k]:
				merged, err := mergeMaps(k, existing, v)
				if err != nil {
					return nil, err
				}
				result[k] = merged

			case conflictOnlyFields[k] && exists:
				return nil, fmt.Errorf("field %q defined in multiple flavors; only one flavor may set it", k)

			default:
				result[k] = v
			}
		}
	}

	return result, nil
}

// ApplyActorInline applies the actor's own spec on top of the merged flavor result.
// The actor always wins: its fields replace flavor values without merging.
func ApplyActorInline(base, actor map[string]interface{}) map[string]interface{} {
	result := make(map[string]interface{}, len(base)+len(actor))
	for k, v := range base {
		result[k] = v
	}
	for k, v := range actor {
		result[k] = v
	}
	return result
}

// appendList appends src list items to existing list. Both must be []interface{};
// if existing is nil it is treated as empty.
func appendList(existing, src interface{}) []interface{} {
	var result []interface{}
	if existing != nil {
		if ex, ok := existing.([]interface{}); ok {
			result = append(result, ex...)
		}
	}
	if s, ok := src.([]interface{}); ok {
		result = append(result, s...)
	}
	return result
}

// mergeMaps merges src map into existing map. Returns error if the same key appears
// in both, as this is a conflict for nodeSelector-type fields.
func mergeMaps(field string, existing, src interface{}) (map[string]interface{}, error) {
	result := make(map[string]interface{})
	if existing != nil {
		if ex, ok := existing.(map[string]interface{}); ok {
			for k, v := range ex {
				result[k] = v
			}
		}
	}
	if s, ok := src.(map[string]interface{}); ok {
		for k, v := range s {
			if _, conflict := result[k]; conflict {
				return nil, fmt.Errorf("field %q: key %q defined in multiple flavors", field, k)
			}
			result[k] = v
		}
	}
	return result, nil
}
