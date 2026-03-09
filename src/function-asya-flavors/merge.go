package main

// DeepMerge merges patch into base. Dicts merge recursively, arrays replace,
// except arrays of objects with a "name" key which merge by name.
func DeepMerge(base, patch map[string]interface{}) map[string]interface{} {
	result := make(map[string]interface{})
	for k, v := range base {
		result[k] = v
	}

	for k, pv := range patch {
		bv, exists := result[k]
		if !exists {
			result[k] = pv
			continue
		}

		// Both are maps: recurse
		bm, bOk := bv.(map[string]interface{})
		pm, pOk := pv.(map[string]interface{})
		if bOk && pOk {
			result[k] = DeepMerge(bm, pm)
			continue
		}

		// Both are arrays: check if name-keyed (merge by name) or replace
		ba, bOk := bv.([]interface{})
		pa, pOk := pv.([]interface{})
		if bOk && pOk && isNameKeyedArray(ba) && isNameKeyedArray(pa) {
			result[k] = mergeByName(ba, pa)
			continue
		}

		// Default: replace
		result[k] = pv
	}

	return result
}

// isNameKeyedArray returns true if all items are maps with a "name" string key.
// Empty arrays return false (treated as replace).
func isNameKeyedArray(arr []interface{}) bool {
	if len(arr) == 0 {
		return false
	}

	for _, item := range arr {
		m, ok := item.(map[string]interface{})
		if !ok {
			return false
		}

		name, ok := m["name"]
		if !ok {
			return false
		}

		if _, ok := name.(string); !ok {
			return false
		}
	}

	return true
}

// mergeByName merges two arrays of name-keyed objects. Same name = deep merge
// (preserves fields from base not present in patch). Different names accumulate.
// Order: base items first, then new patch items.
func mergeByName(base, patch []interface{}) []interface{} {
	patchMap := make(map[string]interface{})
	var patchOrder []string

	for _, item := range patch {
		m := item.(map[string]interface{})
		name := m["name"].(string)
		patchMap[name] = item
		patchOrder = append(patchOrder, name)
	}

	seen := make(map[string]bool)
	var result []interface{}

	// Base items first, with deep-merged overrides from patch
	for _, item := range base {
		m := item.(map[string]interface{})
		name := m["name"].(string)
		seen[name] = true

		if override, ok := patchMap[name]; ok {
			result = append(result, DeepMerge(m, override.(map[string]interface{})))
		} else {
			result = append(result, item)
		}
	}

	// New items from patch (not in base), deduplicated
	for _, name := range patchOrder {
		if !seen[name] {
			seen[name] = true
			result = append(result, patchMap[name])
		}
	}

	return result
}

// MergeFlavors merges flavor data sequentially. Later flavors override earlier ones.
func MergeFlavors(flavorData []map[string]interface{}) map[string]interface{} {
	if len(flavorData) == 0 {
		return map[string]interface{}{}
	}

	base := map[string]interface{}{}
	for _, data := range flavorData {
		base = DeepMerge(base, data)
	}

	return base
}
