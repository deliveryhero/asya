---
title: "Implement RFC flavor overlap rules: type-aware merge with conflict detection"
status: merged
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - pr:306
dependencies:
  - lfcf6
---


## Summary

Phase 2 [lfcf] shipped with the old DeepMerge last-wins flavor merge instead of the type-aware overlap rules specified in the RFC (`.aint/aints/xrd-v2/rfc.md`, section 'Flavor overlap rules').

## What the RFC specifies

| Field type | Overlap behavior | Fields |
|---|---|---|
| **Lists** | Append across flavors | `stateProxy`, `tolerations`, `secretRefs`, `volumes`, `volumeMounts` |
| **Maps** | Merge keys (conflict on same key = error) | `nodeSelector` |
| **Scalars/structs** | Error (flavors must not overlap) | `scaling`, `resources`, `replicas`, `sidecar` |

Actor inline spec always wins silently (no error on actor-vs-flavor overlap).

## What the code currently does

`src/function-asya-flavors/merge.go`: `DeepMerge` + `MergeFlavors` use last-wins:
- Lists: merge-by-name if name-keyed, otherwise replace (last flavor wins)
- Maps: deep merge recursively (no conflict detection)
- Scalars: replace (last flavor wins, no error)

`src/function-asya-flavors/fn.go`: uses `infrastructureFields` blacklist instead of `workloadFields` whitelist.

## Changes needed

### `src/function-asya-flavors/fn.go`

1. Replace `infrastructureFields` blacklist (line 27) with `workloadFields` whitelist:
```go
var workloadFields = map[string]bool{
    "scaling":    true,
    "workload":   true,
    "resiliency": true,
    "sidecar":    true,
    "stateProxy": true,
    "secretRefs": true,
}
```

2. Update `extractActorInlineSpec` (line 240): include field if `workloadFields[k]` (whitelist), not `\!infrastructureFields[k]` (blacklist)

3. Update `infraOnly` loop (line 114): copy field if NOT in workloadFields

4. Update filter after merge (line 94): delete if NOT in workloadFields

### `src/function-asya-flavors/merge.go`

Replace `MergeFlavors` with type-aware merge (~30 LOC):

```go
func MergeFlavors(flavorData []map[string]interface{}, flavorNames []string) (map[string]interface{}, error) {
    merged := map[string]interface{}{}
    seen := map[string]string{} // field -> flavor name
    for i, data := range flavorData {
        name := flavorNames[i]
        for k, v := range data {
            if existing, ok := merged[k]; ok {
                switch ev := existing.(type) {
                case []interface{}:
                    merged[k] = append(ev, v.([]interface{})...)
                case map[string]interface{}:
                    for mk, mv := range v.(map[string]interface{}) {
                        if _, dup := ev[mk]; dup {
                            return nil, fmt.Errorf("flavors %q and %q conflict on %s.%s", seen[k], name, k, mk)
                        }
                        ev[mk] = mv
                    }
                default:
                    return nil, fmt.Errorf("flavors %q and %q both set %q", seen[k], name, k)
                }
            } else {
                merged[k] = v
                seen[k] = name
            }
        }
    }
    return merged, nil
}
```

Keep `DeepMerge` for actor-spec-over-flavor merge (actor always wins, no error).

### `src/function-asya-flavors/fn.go` caller update

Update the call site (line 91) to pass flavor names and handle the error:
```go
merged, err := MergeFlavors(flavorData, flavors)
if err \!= nil {
    return errors.Wrapf(err, "flavor merge conflict")
}
```

### `src/function-asya-flavors/fn_test.go` + `merge_test.go`

Add test cases:
- Two flavors both set `scaling` (scalar) -> error with flavor names
- Two flavors both add `stateProxy` entries (list) -> appended
- Two flavors both add different `nodeSelector` keys (map) -> merged
- Two flavors set same `nodeSelector` key (map conflict) -> error
- Actor overrides flavor `scaling` -> no error, actor wins
- Single flavor -> no conflict possible

### Documentation

Update/create `docs/internal/xrd-flavors.md` (tech spec), `docs/tutorials/actor-flavors.md` (user guide), `src/function-asya-flavors/README.md`.
Explain this new merge behavior in details.

## Test strategy

- `make lint`, `make -C src/function-asya-flavors test-unit` must pass
- then create PR - we'll test the rest there
- add some tests on `fn.go` (unit, component, E2E) specifically fixating this merge behavior.
- existing E2E tests unchanged (existing flavors are non-overlapping, so the new validation won't trigger)
