---
title: "Sidecar: multi-frame streaming protocol (runtime <-> sidecar)"
status: rejected
priority: 1
tags:
  - type:feature
---

The original task 1fw7nd proposed a custom multi-frame protocol over the Unix socket:
{"type": "stream", "data": {"type": "text_delta", "delta": "..."}}
{"type": "stream", "data": {"type": "progress", "pct": 50}}
{"type": "result", "data": {"payload": {...}, "route": {...}}}

This was a proprietary framing format — the sidecar would read frames in a loop, distinguish stream vs result types, and forward
accordingly.

What replaced it: Instead of inventing a custom protocol, we used standard SSE (text/event-stream) — the same format the gateway
already uses for client streaming. The runtime emits event: downstream, event: upstream, event: done, and event: error as standard
SSE events. The sidecar detects SSE via Content-Type header and uses a standard SSE parser.

Why SSE won:
- No custom framing to maintain — SSE is a well-specified standard
- Content-Type detection makes backward compatibility trivial (JSON responses still work)
- The sidecar's parseSSEStream() is ~30 lines of standard SSE parsing vs a custom frame loop
- Event types (downstream/upstream) provide clear semantics without a type field convention




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


_Migrated from beads `asya-qrsp`_
