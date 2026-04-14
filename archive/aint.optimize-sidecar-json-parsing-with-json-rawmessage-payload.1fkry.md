---
title: Optimize sidecar JSON parsing with json.RawMessage for payload
status: merged
priority: 3
---

Use json.RawMessage for payload field in Go sidecar to avoid deserializing payload into Go objects. Sidecar only needs id, route, headers - payload can stay as raw bytes and be forwarded directly to runtime.

**Benefits:**
- ~45% reduction in total parsing overhead
- Zero protocol changes required
- Zero risk - fully backward compatible

**Implementation:**
1. Change Envelope.Payload from `any` to `json.RawMessage` in pkg/envelopes/envelope.go
2. Update router.go to pass payload bytes directly to runtime
3. Runtime parsing unchanged (still receives JSON)

**Context:** This is a low-risk incremental optimization before implementing full binary protocol (asya-6j2).


## Notes

## Implementation Status

The json.RawMessage optimization was already in place:
- `Envelope.Payload` uses `json.RawMessage` (pkg/envelopes/envelope.go:30)
- `RuntimeResponse.Payload` uses `json.RawMessage` (internal/runtime/client.go:24)

## Changes Made

Added regression tests to ensure the optimization remains in place:
- `TestEnvelope_RawMessagePreservesPayloadBytes`: Verifies payload stays as raw bytes
- `TestEnvelope_RawMessageForwardsUnchanged`: Verifies payload can be extracted and forwarded

## Branch

`feature/asya-866-rawmessage` - commit ff60bb0


**Close reason**: Already implemented. Added regression tests to verify json.RawMessage optimization remains in place.


_Migrated from beads `asya-866`_
