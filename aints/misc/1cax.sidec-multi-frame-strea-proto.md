---
title: "Sidecar: multi-frame streaming protocol (runtime <-> sidecar)"
status: open
priority: 1 # high
type: task
tags:
  - type:feature
---


Extend the sidecar's Unix socket protocol to support multiple response frames from the runtime per handler invocation.

## Changes

### src/asya-sidecar/ (Go)
- Current: readFrame(conn) returns one JSON frame, route to next queue
- New: read frames in a loop until receiving a 'result' frame
- For 'stream' frames: forward to gateway via HTTP (see separate bead)
- For 'result' frame: normal envelope routing to next actor queue

### Protocol
Current (single frame):
  Runtime -> Sidecar: {"payload": {...}, "route": {...}}

New (multi frame):
  Runtime -> Sidecar: {"type": "stream", "data": {"type": "text_delta", "delta": "..."}}
  Runtime -> Sidecar: {"type": "stream", "data": {"type": "progress", "pct": 50}}
  Runtime -> Sidecar: {"type": "result", "data": {"payload": {...}, "route": {...}}}

### Backward Compatibility
- If the frame has no "type" field, treat it as a legacy single-frame result (current behavior)
- This ensures existing sync handlers continue working without changes

## Note on json.RawMessage
The sidecar currently uses json.RawMessage to avoid double JSON parsing. The multi-frame protocol must preserve this optimization -- streaming frames are forwarded as-is to the gateway without parsing the data field.

## Test Plan
- Unit test: single frame (backward compat)
- Unit test: multiple streaming frames + result frame
- Unit test: malformed frame handling
- Integration test: runtime sends streaming frames, sidecar forwards correctly

## References
- RFC: docs/rfc/agentic-compiler/agentic-compiler-rfc.md Section 11.1


---
_Migrated from beads `asya-qrsp`_
