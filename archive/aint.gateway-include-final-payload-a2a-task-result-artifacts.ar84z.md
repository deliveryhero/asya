---
title: "Gateway: include final payload in A2A task result (artifacts)"
status: merged
priority: 1 # high
assignee: Artem Yushkovskiy
tags:
  - pr:392
---



## Problem

The sidecar sends the final output payload to the gateway via `POST /mesh/{id}/final`,
but the gateway only stores a generic "Task completed successfully" message. Neither A2A
`tasks/send` nor MCP Streamable HTTP `tools/call` return the actual result payload to
the client.

## Specification

### 1. Surface result as A2A artifact (done)

Per the A2A spec, task outputs are delivered as `Artifact` objects on the `Task`. Two paths:

- **`StoreAdapter.Get()`**: synthesize artifact from `envelope.Result` for `tasks/get` polling
- **`waitAndRelayEvents()`**: send `TaskArtifactUpdateEvent` before terminal `StatusUpdateEvent`
  for blocking `tasks/send` and MCP Streamable HTTP

Only for succeeded tasks. State-proxy artifacts take precedence. Empty-map guard for PG NULL default.

### 2. Unify mesh-to-API delivery via PG NOTIFY (this PR)

Currently three separate mechanisms deliver events from mesh gateway to API gateway:

| Event type | Primary path | Latency |
|------------|-------------|---------|
| FLY tokens | PG NOTIFY on `fly` channel | ~ms |
| Progress updates | PG tables + 500ms poll | 500ms |
| Final status + result | PG tables + 500ms poll | 500ms |

Target: **single PG NOTIFY channel** for all event types. DB poll becomes backup only.

#### Design

**Channel**: `task_events` (replaces `fly`)

**Payload format**: `task_id:type:json`
- `type` = `fly` | `progress` | `final`
- `json` = event payload (FLY body, progress update, or final status + result)

**Size handling**:
- If serialized notification <= 7900 bytes: send via `pg_notify`
- If > 7900 bytes: skip pg_notify, rely on DB poll (500ms fallback)
- FLY events that exceed limit: in-process `notifyListeners` only (existing behavior)

**Persistence rules** (unchanged):
- FLY: not persisted (ephemeral streaming tokens)
- Progress: persisted to `tasks` + `task_updates` tables
- Final: persisted to `tasks` + `task_updates` tables

**Listener changes**:
- `StartFLYListener` renamed to `StartEventListener`
- LISTEN on `task_events` channel instead of `fly`
- Parse `type` prefix, dispatch accordingly:
  - `fly`: create EnvelopeUpdate with PartialPayload (existing behavior)
  - `progress`: create EnvelopeUpdate with status/progress fields
  - `final`: create EnvelopeUpdate with status + Result

**Handler changes**:
- `HandleMeshFly`: send `task_id:fly:payload` on `task_events`
- `HandleMeshProgress`: after `store.UpdateProgress()`, send `task_id:progress:json` on `task_events`
- `HandleMeshFinal`: after `store.Update()`, send `task_id:final:json` on `task_events`

**waitAndRelayEvents changes**:
- Subscription channel now receives progress/final via PG NOTIFY (fast path)
- DB poll interval can be increased (e.g., 2s) since it's backup only
- Non-terminal progress updates from subscription: still dropped to prevent feedback loop
  (but terminal + FLY arrive faster now)

## Plan

1. Rename FLY channel to `task_events`, generalize notification format
2. Generalize `StartFLYListener` to `StartEventListener` with type dispatch
3. Add `pg_notify` calls in `HandleMeshProgress` and `HandleMeshFinal`
4. Increase DB poll interval from 500ms to 2s (backup only)
5. Update tests
