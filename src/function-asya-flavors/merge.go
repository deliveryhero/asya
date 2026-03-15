package main

import "fmt"

// MergeFlavors merges flavor data sequentially with type-aware semantics
// derived from Go runtime types (no field-specific categories):
//   - []interface{} (lists): concatenated across all flavors
//   - map[string]interface{} (maps/structs): keys merged recursively;
//     same leaf key in two flavors is a conflict error
//   - all other types (scalars): only one flavor may define the field;
//     conflict returns error
//
// Type mismatches (e.g., one flavor defines a field as a list, another as a
// scalar) are treated as errors.
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

			result, err := mergeOverlap(seen[k], name, k, existing, v)
			if err != nil {
				return nil, err
			}
			merged[k] = result
		}
	}

	return merged, nil
}

// mergeOverlap recursively merges two overlapping values at the given path.
// Lists are appended, maps are recursively key-merged, and scalars conflict.
func mergeOverlap(firstFlavor, secondFlavor, path string, a, b interface{}) (interface{}, error) {
	switch av := a.(type) {
	case []interface{}:
		bv, ok := b.([]interface{})
		if !ok {
			return nil, fmt.Errorf("flavors %q and %q have conflicting types for key %q: existing is a list, new is %T", firstFlavor, secondFlavor, path, b)
		}
		return append(av, bv...), nil

	case map[string]interface{}:
		bv, ok := b.(map[string]interface{})
		if !ok {
			return nil, fmt.Errorf("flavors %q and %q have conflicting types for key %q: existing is a map, new is %T", firstFlavor, secondFlavor, path, b)
		}
		for mk, mv := range bv {
			if existing, dup := av[mk]; dup {
				merged, err := mergeOverlap(firstFlavor, secondFlavor, path+"."+mk, existing, mv)
				if err != nil {
					return nil, err
				}
				av[mk] = merged
			} else {
				av[mk] = mv
			}
		}
		return av, nil

	default:
		return nil, fmt.Errorf("flavors %q and %q conflict on %s", firstFlavor, secondFlavor, path)
	}
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
