---
title: Runtime SSE streaming for generator handlers
priority: 2 # medium
type: task
dependencies:
  - 1fbe/1iof6x
  - 1ia4/1f2wwf
---

Add SSE (`text/event-stream`) response mode for generator and async-generator handlers in the HTTP-over-Unix-socket runtime server.

## Scope

- Runtime auto-detects handler type (return vs generator vs async generator) and selects response format
- JSON response for return-based handlers (from 1fbe)
- SSE (`text/event-stream`) for generator handlers
- Event types:
  - `downstream`: yielded output frame (routed to next actor queue by sidecar)
  - `upstream`: partial/token frame (forwarded to gateway by sidecar)
  - `done`: generator exhausted (sidecar closes connection)
  - `error`: handler exception mid-stream (sidecar routes to x-sump)
- Generator yield semantics: each `yield` produces a `downstream` event by default
- Upstream marking: handler yields with a marker to indicate upstream events (TBD: convention for marking)
- End of iteration -> `done` event
- Exception during iteration -> `error` event

## Dependencies

- 1fbe/1iof6x (runtime HTTP server — vibed)
- 1ia4/1f2wwf (async generator detection)

## Key Files

- `src/asya-runtime/asya_runtime.py`

## References

- RFC: 1ia4/rfc.md
- Epic: 1fbe.redesign-protocol-sidecar-runtime (epic.md contains full SSE protocol spec)

Unit tests required.
