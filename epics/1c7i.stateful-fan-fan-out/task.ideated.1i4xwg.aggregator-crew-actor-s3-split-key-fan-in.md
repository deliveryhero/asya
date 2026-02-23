---
title: "Aggregator crew actor: S3 split-key fan-in handler"
priority: 2 # medium
type: task
---

## Summary

Implement the v0 aggregator crew actor using the S3 split-key pattern via state proxy sidecar. The aggregator collects N+1 fan-in messages (1 parent payload + N sub-agent slices), detects completeness via directory listing, emits exactly-once via atomic create sentinel, and produces a merged envelope for pipeline continuation.

Runs as an envelope-mode handler in `asya-crew`. State lives in S3 via the state proxy sidecar (epic 1dmf) -- no PVCs, no StatefulSets, no shard affinity.

## Storage Layout

```
/state/fanin/{origin_id}/
+-- message.json        <-- continuation metadata (route, headers, id)
+-- slice-0.json        <-- parent payload (index 0)
+-- slice-1.json        <-- sub-agent result 1
+-- slice-N.json        <-- sub-agent result N
+-- complete            <-- emission lock (atomic create-if-not-exists)
```

## Handler Logic

1. Write slice payload to `slice-{idx}.json` (idempotent via exists check)
2. Index 0 only: save continuation metadata to `message.json` (route, non-transient headers, origin_id)
3. Check completeness via `os.listdir()` -- count slice files
4. If incomplete: return `None` (sidecar routes to x-sink, reporting suppressed)
5. If complete: atomic `open(path, "xb")` on `complete` sentinel -- exactly-once emission
6. Read all slices, merge using `jsonpointer.set_pointer()` at `aggregation_key`
7. Cleanup: delete all files in the directory
8. Return merged envelope

## Transient Headers (stripped from merged envelope)

`x-asya-fan-in`, `x-asya-route-override`, `x-asya-route-resolved`, `x-asya-parent-id`

## Changes

### `src/asya-crew/asya_crew/fanin/__init__.py` (NEW)
### `src/asya-crew/asya_crew/fanin/s3_split_key.py` (NEW)
- `aggregator(envelope: dict) -> dict | None` handler function
- `_TRANSIENT_HEADERS` set for header stripping
- JSON Pointer-based result placement via `jsonpointer` library

### `src/asya-crew/pyproject.toml`
- Add dependency: `jsonpointer`

### Tests (unit)
- Single message completes fan-in (slice_count=1 + parent = 2 total)
- Multiple messages arrive in order -> emit on last
- Multiple messages arrive out of order -> emit on last
- Index 0 arrives last -> still emits correctly
- Duplicate slice_index is ignored (idempotent via exists check)
- After emission, state directory is cleaned up
- Transient headers stripped from merged envelope
- `aggregation_key` JSON Pointer correctly places results in parent payload
- Concurrent completion detection: only one pod emits (FileExistsError on sentinel)
- `origin_id` restored as merged envelope `id`

## Dependencies
- DEPENDS ON: Runtime exclusive create mode (open path "x") for exactly-once sentinel
- DEPENDS ON: State proxy sidecar (epic 1dmf) for S3 filesystem access

## References
- RFC: `.aint/epics/1c7i.stateful-fan-fan-out/rfc.md` (Aggregator Actor Design, ADR-1, ADR-4)
