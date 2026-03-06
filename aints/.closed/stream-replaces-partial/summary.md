---
title: "Rename 'partial' to 'stream' across wire protocol, gateway, and sidecar"
priority: 2 # medium
tags:
  - type:breaking-change
  - component:gateway
  - component:sidecar
  - component:runtime
---


## Context

Epic 1ia4 (streaming-protocol) established the streaming architecture: upstream
events flow transport-level from sidecar to gateway, bypassing message queues.
That epic used the term "partial" throughout — `ForwardPartial()`, `POST
/tasks/{id}/partial`, `event: partial`, `PartialPayload`.

The ABI protocol (epic 1l01) introduces the `FLY` verb for upstream streaming
events, replacing the `partial: True` dict key convention. On the handler side,
this is covered by 1l01.

This epic covers the **downstream propagation** of that change: the runtime SSE
protocol, sidecar forwarding, gateway endpoints, database schema, and client-facing
SSE event types.

The word "partial" is misleading — these are **streaming events** (LLM tokens,
progress updates), not incomplete/partial data. The 1ia4 RFC has been updated
to use the new terminology (with legacy notes for current code).

## Scope

### Runtime (Python)

- Remove `partial: True` detection logic from `_emit_sse_event()`
- FLY tuples are emitted as `event: upstream` (SSE to sidecar) — unchanged wire format
- Remove partial key stripping (FLY payload is forwarded as-is)
- Batch mode: skip FLY instructions entirely (they're meaningless without SSE)

### Sidecar (Go)

- Rename `ForwardPartial()` → `ForwardStream()`
- Update endpoint: `POST /tasks/{id}/partial` → `POST /tasks/{id}/stream`
- Update comments and logs referencing "partial"

### Gateway (Go)

- Rename endpoint: `/tasks/{id}/partial` → `/tasks/{id}/stream`
- Rename handler: `HandleTaskPartial()` → `HandleTaskStream()` (or distinguish
  from existing `HandleTaskStream` which is SSE streaming)
- Rename type field: `PartialPayload` → `StreamPayload`
- Rename SSE event type: `event: partial` → `event: stream`
- DB migration: rename column `partial_payload` → `stream_payload`

### Tests

- Update all test assertions using "partial" event type
- Update mock data with "partial" keys
- Update `stream_task_events()` helper to collect "stream" events

## Wire Protocol Change

```
Before:
  Handler: yield {"partial": True, "token": "hello"}
  Runtime→Sidecar SSE: event: upstream
  Sidecar→Gateway HTTP: POST /tasks/{id}/partial
  Gateway→Client SSE: event: partial

After:
  Handler: yield "FLY", {"token": "hello"}
  Runtime→Sidecar SSE: event: upstream  (unchanged)
  Sidecar→Gateway HTTP: POST /tasks/{id}/stream
  Gateway→Client SSE: event: stream
```
