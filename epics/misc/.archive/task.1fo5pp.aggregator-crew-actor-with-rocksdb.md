---
title: Aggregator crew actor with RocksDB
status: wont_do
reason: virtual actors
priority: 2 # medium
type: task
tags:
  - type:feature
---




## Summary

Implement the aggregator crew actor in `src/asya-crew/asya_crew/aggregator.py`. The aggregator collects N+1 fan-in messages (1 parent payload + N sub-agent slices), detects completeness, and emits a merged envelope.

## Design

- Runs in envelope mode
- Uses embedded RocksDB (via `plyvel` Python bindings) for durable state
- State keyed by `origin_id` from `x-asya-fan-in` header
- Stores payloads in a `results` array indexed by `slice_index`
- When `received_count == slice_count`: emit merged envelope, delete state
- When incomplete: return `None` (sidecar routes to x-sink, which suppresses gateway reporting via `x-asya-fan-in` header)

## State Schema

```json
{
  "slice_count": 6,
  "aggregation_key": "/results",
  "results": [parent_payload, slice_1, null, null, null, null],
  "received_count": 2,
  "message": {
    "id": "origin-id",
    "route": {"actors": [...], "current": N},
    "headers": {"non-transient-headers": "..."}
  }
}
```

## Changes

### `src/asya-crew/asya_crew/aggregator.py` (NEW)
- `aggregator(envelope)` handler function
- RocksDB initialization via `ASYA_FANIN_DB_PATH` env var
- `_TRANSIENT_HEADERS` set: strip fan-in/route-override headers from merged envelope
- JSON Pointer-based result placement via `jsonpointer` library
- Completeness detection: `received_count == slice_count`

### `src/asya-crew/pyproject.toml`
- Add dependencies: `plyvel`, `jsonpointer`, `xxhash`

### Tests (unit)
- Single message completes fan-in (slice_count=1)
- Multiple messages arrive in order → emit on last
- Multiple messages arrive out of order → emit on last
- Index 0 arrives last → still emits correctly
- Duplicate slice_index is overwritten (idempotent)
- After emission, state is deleted from RocksDB
- Transient headers stripped from merged envelope
- `aggregation_key` JSON Pointer correctly places results

## Dependencies
- DEPENDS ON: asya-0bvg (sink non-reporting for partial messages)

## References
- RFC: docs/rfc/fan-in/rfc-fan-in.md (Aggregator Actor Design)
- ADR-1: Embedded RocksDB per Replica


---
_Migrated from beads `asya-fi6u`_
