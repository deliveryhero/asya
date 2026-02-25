---
title: "Sidecar: forward upstream events to gateway"
priority: 2 # medium
type: task
tags:
  - type:feature
  - pr:205
dependencies:
  - 1ia4/1in0hv
---


Forward upstream (partial) SSE events from runtime to the gateway via HTTP for real-time client delivery (LLM token streaming, progress indicators).

## Design

Upstream events are **transport-level, not payload-level**. They bypass message queues entirely and go directly from sidecar to gateway. See `1ia4/rfc.md` for rationale.

## Changes

### src/asya-sidecar/ (Go)

When parsing SSE responses from runtime (after 1fbe HTTP migration):
- `event: downstream` -> route to next actor queue (existing behavior)
- `event: upstream` -> HTTP POST to gateway (this task)
- `event: done` -> close connection (existing behavior)
- `event: error` -> route to x-sump (existing behavior)

**Upstream forwarding**:
- Endpoint: `POST /tasks/{task_id}/stream`
- Reuse `progress.Reporter` HTTP client and retry logic
- Fire-and-forget (log errors, don't block processing)
- Include task_id from the original message for SSE correlation

### src/asya-gateway/ (Go)

- New endpoint: `POST /tasks/{task_id}/stream`
- Accept upstream events from sidecars
- Store in task event history (for late-joining SSE clients)
- Forward to connected SSE clients watching this task_id
- Send `event: stream` SSE event to clients

## Error Handling

- If gateway is unreachable: drop the event, log warning
- If handler errors mid-stream after some upstream events:
  - Already-sent upstream events are NOT recalled
  - Error is reported via normal x-sump path
  - Gateway sends `event: error` to SSE clients

## Test Plan
- Unit test: sidecar forwards upstream event to gateway endpoint
- Unit test: sidecar handles gateway unavailability gracefully
- Integration test: SSE client receives upstream events in real-time
- Integration test: error mid-stream after upstream events

## References
- RFC: 1ia4/rfc.md
- Progress reporter pattern: src/asya-sidecar/internal/progress/reporter.go
