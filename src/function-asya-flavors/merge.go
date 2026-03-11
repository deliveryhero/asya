package main

import "fmt"

// MergeFlavors merges flavor data sequentially with type-aware semantics
// derived from Go runtime types (no field-specific categories):
//   - []interface{} (lists): concatenated across all flavors
//   - map[string]interface{} (maps/structs): keys merged; same key in two flavors is a conflict error
//   - all other types (scalars): only one flavor may define the field; conflict returns error
func MergeFlavors(flavorData []map[string]interface{}, flavorNames []string) (map[string]interface{}, error) {
	merged := make(map[string]interface{})
	seen := make(map[string]string) // field -> flavor name that first defined it

	for i, data := range flavorData {
		name := flavorNames[i]
		for k, v := range data {
			existing, exists := merged[k]

			if !exists {
				merged[k] = v
				seen[k] = name
				continue
			}

			switch ev := existing.(type) {
			case []interface{}:
				if sv, ok := v.([]interface{}); ok {
					merged[k] = append(ev, sv...)
				}

			case map[string]interface{}:
				if sv, ok := v.(map[string]interface{}); ok {
					for mk, mv := range sv {
						if _, dup := ev[mk]; dup {
							return nil, fmt.Errorf("flavors %q and %q conflict on %s.%s", seen[k], name, k, mk)
						}
						ev[mk] = mv
					}
				}

			default:
				return nil, fmt.Errorf("flavors %q and %q both set %q", seen[k], name, k)
			}
		}
	}

	return merged, nil
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
