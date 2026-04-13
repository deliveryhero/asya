---
title: "ADR: Rejected — Single-Key with CAS Counter"
status: rejected
superseded_by: "rfc.md (actualized: split-key pattern, zero contention)"
date: 2025-02-23
---

# ADR: Single-Key with CAS Counter

## Status

**Rejected** in favor of the split-key pattern. Preserved for historical
context and as rationale for why CAS-based fan-in needs careful design.

## Context

An intermediate design was explored during the actualization of the fan-in
RFC. Instead of RocksDB, the aggregator would use an external KV store
(Redis or S3) via state proxy sidecar, storing all aggregation state in a
single key per origin_id.

## The Proposed Approach

Store all slices and metadata in one KV entry:

```python
# Single key: /state/fanin/{origin_id}
state = {
    "slice_count": 6,
    "aggregation_key": "/results",
    "results": [parent_payload, "result-1", null, null, null, null],
    "received_count": 2,
    "message": { "id": "...", "route": {...}, "headers": {...} }
}
```

Each slice arrival:
1. Read the full state (connector stores revision/ETag)
2. Add slice to `results[idx]`, increment `received_count`
3. Write the full state (connector uses stored revision for conditional write)

CAS ensures that concurrent writes don't overwrite each other.

## Why Rejected

### 1. CAS Layer 1 retry is broken for multi-writer fan-in

The state proxy connector's internal CAS retry (Layer 1) re-reads the latest
revision and re-attempts the write **with the same data** the handler produced.
This is designed for single-writer scenarios where a transient conflict is
resolved by retrying with the current revision.

For fan-in, this is wrong:

```
Pod A reads state (rev R1), adds slice 3 -> produces state_A
Pod B reads state (rev R1), adds slice 5 -> produces state_B
Pod A writes state_A with R1 -> succeeds (now rev R2, has slice 3)
Pod B writes state_B with R1 -> CAS fail
  Layer 1 retry: re-reads (gets rev R2, which has slice 3)
  Re-writes state_B with R2 -> succeeds BUT OVERWRITES slice 3!
```

The connector re-reads to get the new revision but writes the handler's
stale data. Slice 3 is lost.

### 2. Workaround: CAS_MAX_RETRIES=0 forces Layer 2

Setting `CAS_MAX_RETRIES=0` skips Layer 1 entirely. Every CAS conflict
causes the message to be nacked and re-queued (Layer 2). The handler
re-runs fresh, reads the latest state, and adds its slice.

This works correctly but has performance implications:
- Each Layer 2 retry adds ~100-500ms (queue round-trip)
- For N concurrent slices, worst case is O(N^2) retries
- In practice, sub-agents take varying amounts of time, so concurrent
  arrivals are rare

### 3. Full payload in single KV entry

Storing all N sub-agent results in one key means the KV entry grows with N.
For 10 sub-agents each returning 100KB, the entry is ~1MB. This is:
- Fine for Redis (memory-based, handles large values)
- Fine for S3 (handles up to 5GB per object)
- Wasteful: every slice arrival reads and writes the entire aggregated state

### 4. Split-key eliminates all these problems

The split-key pattern writes each slice to its own key:
- Zero contention (no CAS needed)
- No full-state read/write on each arrival
- No Layer 1/Layer 2 retry concerns
- Arbitrary payload sizes per slice

## When This Approach Might Be Valid

Single-key CAS works well when:
- Fan-in count is small (2-3 slices)
- Payloads are tiny (counters, flags)
- Low concurrency (slices arrive seconds apart)

For these cases, a future `fanin-redis-cas` flavor could use this pattern
with `CAS_MAX_RETRIES=0` and Layer 2 retries. The handler would be simpler
(one key instead of listing files) at the cost of occasional retries.

## References

- Semi-Stateful Actors RFC (epic 1dmf) -- Two-Layer Retry Strategy, ADR-13
  (CAS hidden inside read/write interface)
