---
title: Ephemeral FLY streaming via PG LISTEN/NOTIFY with A2A artifact chunking
status: merged
priority: 1 # high
assignee: Artem Yushkovskiy
tags:
  - pr:368
---


## Problem

In dual-gateway mode, FLY events (per-token LLM streaming) have two problems:

1. **FLY events write to PostgreSQL** (`task_updates.partial_payload` via `UpdateProgress()`) — violates "PG = metadata only" and will kill PG under LLM streaming load (30+ tokens/sec per task)
2. **500ms DB poll** in `waitAndRelayEvents` is the only cross-process detection — batches ~15 tokens per poll tick instead of individual token events

Current path (broken):
```
Sidecar → POST /mesh/{id}/fly → Mesh GW → INSERT into PG → API GW polls DB every 500ms → SSE client
```

Target path:
```
Sidecar → POST /mesh/{id}/fly → Mesh GW → pg_notify (no storage) → API GW → SSE client
```

## Constraints

- Mesh and API gateways are **separate deployments** (independent scaling)
- Both share **PostgreSQL only** — no Redis, NATS, or other new infra
- **Multi-replica** on both sides
- Sidecars remain dumb — POST to `/mesh/{id}/fly`, no sticky sessions, no direct pod addressing
- FLY events are **ephemeral** — must never be persisted to any storage
- Gateway does NOT access state proxy — state proxy is an actor-level sidecar only

## Key Architectural Decisions

### Why PG LISTEN/NOTIFY

Multi-replica requires a broadcast mechanism (FLY POST may hit mesh replica A, but SSE client is on API replica B). PG LISTEN/NOTIFY is:
- Pure in-memory pub/sub — no WAL, no disk, no table writes
- Built into pgx/v5 (already used) — no new dependencies
- Broadcasts to all listeners automatically — handles multi-replica without sticky routing
- Fire-and-forget — if no listener is connected, notifications are silently dropped (perfect for ephemeral)

Limitations: 8KB payload limit (fine for LLM tokens at ~50-200 bytes), notifications lost during PG reconnect (acceptable for ephemeral data).

### Three-Layer Streaming Model

```
FLY Layer (ephemeral, in-memory)              ← per-token streaming, 30+ events/sec
  PG LISTEN/NOTIFY broadcast, zero storage       Uses: pg_notify + notifyListeners

Protocol Layer (A2A / MCP)                    ← task lifecycle, ~5 events/task
  A2A: TaskStatusUpdateEvent (from /progress, /final)
  A2A: TaskArtifactUpdateEvent{Append} (from FLY, in-memory only)
  MCP: Streamable HTTP response

Artifact Layer (durable, S3/object store)     ← final results, on completion
  Written by actors via state-proxy sidecar
  Gateway never accesses state proxy directly
```

### A2A Streaming Semantics

A2A's `TaskArtifactUpdateEvent` with `Append: true` / `LastChunk: true` IS the protocol's intended mechanism for LLM text chunking (equivalent to ADK's `partial: true`). Each chunk is a `TextPart` appended to a named artifact.

However, a2a-go's `Manager.Process()` calls `Save()` on every event, which writes to PG. To use artifact chunking without PG writes, `StoreAdapter.Save()` must return early for append events (accumulate in-memory only).

FLY events and A2A artifact chunks serve different audiences:
- **FLY SSE** — raw ephemeral stream for Asya-native clients (protocol-agnostic)
- **A2A artifact chunking** — protocol-compliant streaming for standard A2A clients

## Implementation

### 1. Make FLY ephemeral in HandleMeshFly

**File**: `src/asya-gateway/internal/mcp/handlers.go` — `HandleMeshFly` (~line 657)

Current: creates `EnvelopeUpdate` with `PartialPayload` and calls `h.taskStore.UpdateProgress(update)` which INSERTs into `task_updates`.

Change:
- Remove `UpdateProgress()` call entirely
- Call `pg_notify('fly', 'task_id:payload_json')` via a pool connection
- Call `notifyListeners()` for in-process subscribers (testing/single-gateway mode)
- Return HTTP 200

```go
// Broadcast via PG NOTIFY for cross-process delivery (dual-gateway mode)
_, err := h.pool.Exec(ctx, "SELECT pg_notify('fly', $1)", taskID+":"+string(body))

// Also notify in-process subscribers (testing/single-gateway mode)
h.taskStore.NotifyFLY(taskID, body)
```

### 2. Add PG LISTEN goroutine to API gateway

**File**: new file `src/asya-gateway/internal/envelopestore/pg_listener.go` (or in `pg_store.go`)

A dedicated `*pgx.Conn` (NOT from pool — pool connections lose LISTEN state when returned) runs a LISTEN loop:

```go
func (s *PgStore) StartFLYListener(ctx context.Context, connString string) {
    for {
        conn, err := pgx.Connect(ctx, connString)
        // on error: log, backoff, retry
        conn.Exec(ctx, "LISTEN fly")
        for {
            notification, err := conn.WaitForNotification(ctx)
            // on error: break to reconnect
            taskID, payload := parseFLYNotification(notification.Payload)
            s.notifyFLY(taskID, payload) // dispatch to in-process Subscribe() channels
        }
    }
}
```

The `notifyFLY` method creates an `EnvelopeUpdate` with `PartialPayload` and dispatches via the existing `notifyListeners()` mechanism. Replicas without a subscriber for that task_id do an O(1) map lookup and discard.

Start this goroutine on API gateway boot (mode=api or mode=testing). Not needed for mode=mesh.

### 3. Add FLY SSE endpoint on API gateway

**File**: `src/asya-gateway/cmd/gateway/main.go` — `registerAPIRoutes`

Register a streaming endpoint on the API gateway (e.g., `/stream/{id}` or reuse `/mesh/{id}/stream` pattern on the API side).

- Protocol-agnostic: any client can subscribe with just the task ID
- Reuses the existing `Subscribe()` → `sseWriter.writeEvent()` pattern from `HandleMeshStream`
- This is the fast path for Asya-native clients (custom UIs, chatbots)

### 4. Relay FLY as A2A artifact chunks in waitAndRelayEvents

**File**: `src/asya-gateway/internal/a2a/blocking.go` — `waitAndRelayEvents` (~line 82)

Current: only relays terminal `TaskStatusUpdateEvent`, drops all non-terminal updates (line 95).

Change: when subscription channel delivers a FLY event (has `PartialPayload`), convert to `TaskArtifactUpdateEvent{Append: true}` and write to `eq`:

```go
case update, ok := <-ch:
    if !ok {
        return nil
    }
    if update.PartialPayload != nil {
        artifactEvent := convertFLYToArtifactUpdate(reqCtx, update)
        if err := eq.Write(ctx, artifactEvent); err != nil {
            slog.Warn("Failed to relay FLY as artifact", "task_id", taskID, "error", err)
        }
        continue
    }
    if terminalOrInterrupted(update.Status) {
        return writeTerminalEvent(ctx, reqCtx, eq, update.Status)
    }
    // Non-terminal status updates still dropped (feedback loop prevention)
```

The `convertFLYToArtifactUpdate` function:
- Uses a deterministic artifact ID per task (e.g., `"fly-stream"`)
- First chunk: `Append: false` (creates artifact)
- Subsequent chunks: `Append: true`
- Track first-vs-subsequent via a local boolean in the `for` loop

### 5. Skip PG writes for artifact appends in StoreAdapter.Save()

**File**: `src/asya-gateway/internal/a2a/store_adapter.go` — `Save()` (~line 34)

Current: every event triggers `a.internal.Update(update)` → PG write.

Change: return early for artifact append events:

```go
func (a *StoreAdapter) Save(ctx context.Context, task *a2alib.Task, event a2alib.Event, prev a2alib.TaskVersion) (a2alib.TaskVersion, error) {
    // Streaming artifact chunks are ephemeral — accumulate in-memory only, no PG write.
    // Manager.lastSaved still accumulates parts via updateArtifact().
    // Final artifact delivery is handled by actors via state proxy, not by the gateway.
    if _, ok := event.(*a2alib.TaskArtifactUpdateEvent); ok {
        return prev, nil
    }
    // ... existing Save logic for status changes
}
```

This breaks the feedback loop: `eq.Write()` → a2a-go SSE → `Manager.Process()` → `updateArtifact()` → `saveTask()` → `Save()` → **returns early** → no `internal.Update()` → no `notifyListeners()` cascade → no PG write.

### 6. Stop writing FLY to task_updates table

The `partial_payload` column in `task_updates` stays (existing rows, used by `GetUpdates` for progress replay) but FLY events no longer populate it. The `HandleMeshFly` change in step 1 handles this — no separate migration needed.

In testing/single-gateway mode: `notifyListeners()` (in-process) handles FLY directly. No PG NOTIFY needed, no DB write.

## Data Flow

```
                        DUAL-GATEWAY MODE

Sidecar ──POST /mesh/{id}/fly──→ Mesh Gateway
                                      |
                                      |── pg_notify('fly', 'task_id:payload')  [no storage]
                                      +── notifyListeners()                    [testing mode]
                                      |
                                      | PG LISTEN/NOTIFY (in-memory broadcast)
                                      v
                                 API Gateway (LISTEN goroutine receives notification)
                                      |
                         +------------+------------+
                         |            |            |
                    FLY SSE      A2A SSE       (discard if
                    endpoint    event queue     no subscriber)
                         |            |
                    Raw FLY      TaskArtifact
                    payload      UpdateEvent
                         |       {Append: true}
                         v            v
                    Asya-native   Standard A2A
                    clients       clients
```

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| PG NOTIFY 8KB payload limit | Low | LLM tokens are ~50-200 bytes. Truncate/skip rare large events |
| Lost notifications during PG reconnect | Low | Acceptable — FLY is ephemeral. Brief gap in tokens during PG failover |
| Fan-out to all API replicas | Low | O(1) map lookup to filter. Optimize with per-task channels later if needed |
| Pod crash loses in-memory artifact state | Low | Final artifacts delivered by actors via state proxy. Gateway never persists artifacts |
| Save() feedback loop | None | Artifact append Save() returns early — no PG write, no notifyListeners cascade |
| Extra PG connection per API replica | Low | 1 dedicated LISTEN conn per replica — negligible vs pool size |

## What Changes vs What Doesn't

**Changes:**
- `HandleMeshFly` — remove `UpdateProgress()`, add `pg_notify()`
- `PgStore` — add PG LISTEN goroutine + FLY dispatch to subscribers
- `waitAndRelayEvents` — relay FLY events as `TaskArtifactUpdateEvent{Append}` via `eq.Write()`
- `StoreAdapter.Save()` — skip PG write for `TaskArtifactUpdateEvent`
- API gateway routes — add FLY SSE endpoint

**No changes:**
- Sidecar — still POSTs to `/mesh/{id}/fly`
- `/mesh/{id}/progress` — still writes status metadata to PG
- `/mesh/{id}/final` — still writes terminal status to PG
- State proxy — actor-level sidecar, gateway does not access it
- `task_updates` schema — column stays, just no longer populated by FLY

## Key Source Files

- `src/asya-gateway/internal/mcp/handlers.go` — HandleMeshFly (line ~657), HandleMeshStream (line ~246)
- `src/asya-gateway/internal/a2a/blocking.go` — waitAndRelayEvents (line ~42)
- `src/asya-gateway/internal/a2a/store_adapter.go` — Save() (line ~34)
- `src/asya-gateway/internal/a2a/fly.go` — DetectFLYEventType
- `src/asya-gateway/internal/envelopestore/pg_store.go` — Subscribe/notifyListeners (line ~634)
- `src/asya-gateway/cmd/gateway/main.go` — route registration (line ~281)
