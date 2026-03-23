---
title: FLY events use 500ms DB poll between mesh and api gateways — route directly to SSE clients
priority: 1 # high
---

In dual-gateway mode (api + mesh), FLY events from actors go: sidecar -> mesh gateway -> PostgreSQL (UpdateProgress) -> api gateway polls DB every 500ms -> SSE client. This adds up to 500ms latency per FLY event, making per-token LLM streaming choppy. FLY events are ephemeral by design (not persisted). They should be relayed directly to SSE clients without touching PostgreSQL. Options: Redis pub/sub, NATS, or shared in-memory channel.



The gateway mesh does NOT send SSE to the gateway API. They share PostgreSQL.

Here's the actual architecture:

Client ──SSE──→ Gateway API (blocks in waitAndRelayEvents)
                    │
                    ├─ DB poll every 500ms (cross-process detection)
                    └─ In-process subscription channel (same-pod only)

Sidecar ──POST /mesh/{id}/fly──→ Gateway Mesh
                                    │
                                    └─ Writes to PostgreSQL (envelope_updates table)

For FLY events specifically:
1. Sidecar POSTs FLY payload → gateway mesh → UpdateProgress() writes to PostgreSQL
2. Gateway API polls DB every 500ms → detects the update → relays to SSE client

For terminal status (succeeded/failed):
1. x-sink sidecar POSTs final status → gateway mesh → writes succeeded to PostgreSQL
2. Gateway API detects via DB poll (500ms) → writes TaskStatusUpdateEvent → SSE stream ends

Latency:
- FLY event latency = 500ms worst case (DB poll interval) + DB write time
- This means per-token LLM streaming at ~30 tokens/sec would actually be batched — you'd get ~15 tokens every 500ms poll tick, not
individual token events
- For the "fast path" (in-process subscription channel), latency is near-zero, but only works when api + mesh run in the same pod
(single-gateway mode)

Implication for token streaming: The 500ms DB poll is fine for progress updates but adds noticeable latency for real-time token
streaming. To make per-token streaming smooth, the dual-gateway setup would need either:
- A shared pub/sub channel (Redis, NATS) between mesh and api pods
- Or running in single-gateway mode (both api+mesh in one pod)


---

 Design Summary: Ephemeral FLY Streaming with A2A Artifact Chunking

  Problem Statement

  In dual-gateway mode, FLY events (per-token LLM streaming) follow a path with ~500ms latency:

  Sidecar → POST /mesh/{id}/fly → Mesh GW → INSERT into PG → API GW polls DB every 500ms → SSE client

  Two problems:
  1. FLY events are written to PostgreSQL (task_updates.partial_payload) — violates "PG = metadata only" and will kill PG under LLM
  streaming load
  2. 500ms DB poll is the only cross-process detection mechanism — makes token streaming choppy

  Architecture Constraints

  - Mesh and API gateways are separate deployments (independent scaling, security boundary)
  - Both share PostgreSQL only — no Redis, NATS, or other infra
  - Multi-replica on both sides
  - Sidecars remain dumb — POST to /mesh/{id}/fly, no sticky sessions
  - FLY events are ephemeral by design — must never be persisted

  Three-Layer Streaming Model

  ┌─────────────────────────────────────────────────────┐
  │  FLY Layer (ephemeral, in-memory)                   │  ← per-token streaming
  │  PG LISTEN/NOTIFY broadcast, zero storage            │     30+ events/sec
  ├─────────────────────────────────────────────────────┤
  │  Protocol Layer (A2A / MCP)                         │  ← task lifecycle
  │  TaskStatusUpdateEvent via sidecar /progress+/final  │     ~5 events/task
  │  TaskArtifactUpdateEvent from FLY (in-memory only)   │     PG metadata only
  ├─────────────────────────────────────────────────────┤
  │  State Proxy Layer (durable, S3/object store)        │  ← payload & artifacts
  │  Written by actors via state-proxy sidecar           │     on completion
  │  Read by gateway on tasks/get                        │
  └─────────────────────────────────────────────────────┘

  Protocol Streaming Semantics

  ┌──────────┬─────────────────────┬──────────────────────────────────────────────────┬─────────────┬──────────────────────────────┐
  │ Protocol │    What streams     │                       How                        │  Frequency  │          Durability          │
  ├──────────┼─────────────────────┼──────────────────────────────────────────────────┼─────────────┼──────────────────────────────┤
  │ A2A      │ Task lifecycle +    │ TaskStatusUpdateEvent +                          │ Low-medium  │ Status → PG; artifact chunks │
  │          │ artifact chunks     │ TaskArtifactUpdateEvent{Append: true, LastChunk} │             │  → in-memory only            │
  ├──────────┼─────────────────────┼──────────────────────────────────────────────────┼─────────────┼──────────────────────────────┤
  │ MCP      │ Tool results        │ MCP Streamable HTTP response                     │ Low         │ Response-scoped              │
  ├──────────┼─────────────────────┼──────────────────────────────────────────────────┼─────────────┼──────────────────────────────┤
  │ FLY      │ Raw ephemeral       │ Separate SSE endpoint on API gateway             │ High        │ None                         │
  │          │ events (LLM tokens) │                                                  │ (30+/sec)   │                              │
  └──────────┴─────────────────────┴──────────────────────────────────────────────────┴─────────────┴──────────────────────────────┘

  A2A's TaskArtifactUpdateEvent with Append/LastChunk IS the protocol's intended mechanism for LLM text chunking — equivalent to ADK's
  partial: true.

  Design: Component Changes

  1. Mesh Gateway — Make FLY Ephemeral + PG NOTIFY

  File: handlers.go — HandleMeshFly

  Current: calls UpdateProgress() → INSERTs into task_updates table
  Change: remove DB write, call pg_notify('fly', 'task_id:payload_json') instead

  Sidecar → POST /mesh/{id}/fly → HandleMeshFly
      → pg_notify('fly', 'task_id:json_payload')   // broadcast, no storage
      → notifyListeners()                            // in-process (for testing mode)
      → HTTP 200

  No INSERT, no UPDATE, no task_updates row. PG NOTIFY is pure in-memory pub/sub — no WAL, no disk.

  2. API Gateway — PG LISTEN Goroutine

  New: dedicated LISTEN fly goroutine on a held *pgx.Conn (not from pool)

  // Lifecycle: starts on gateway boot, reconnects on failure
  for {
      conn := pgx.Connect(ctx, connString)
      conn.Exec(ctx, "LISTEN fly")
      for {
          notification := conn.WaitForNotification(ctx)
          taskID, payload := parseNotification(notification.Payload)
          store.dispatchFLY(taskID, payload)  // → notifyListeners for that task
      }
      // on error: reconnect loop with backoff
  }

  When a notification arrives, dispatch to in-process Subscribe() channels. Replicas that don't have a subscriber for that task_id do an
   O(1) map lookup and discard.

  3. API Gateway — FLY SSE Endpoint

  New endpoint: register a FLY SSE stream on the API gateway (e.g., reuse /mesh/{id}/stream pattern but on the API side, or a new path
  like /stream/{id})

  - Protocol-agnostic: any client (A2A, MCP, custom UI) can subscribe with just the task ID
  - Uses the existing Subscribe() → sseWriter.writeEvent() pattern from HandleMeshStream
  - This is the fast path for Asya-native clients

  4. A2A Path — Artifact Chunking via Event Queue

  File: blocking.go — waitAndRelayEvents

  Current: only relays terminal TaskStatusUpdateEvent, drops all non-terminal updates
  Change: also relay FLY events as TaskArtifactUpdateEvent{Append: true} to eq.Write()

  When the PG NOTIFY listener dispatches a FLY event to the subscription channel:

  case update := <-ch:
      if update.PartialPayload != nil {
          // Convert FLY to A2A artifact chunk
          artifactEvent := convertFLYToArtifactUpdate(reqCtx, update)
          eq.Write(ctx, artifactEvent)  // → a2a-go sends SSE to client
          continue
      }
      if terminalOrInterrupted(update.Status) {
          return writeTerminalEvent(...)
      }
      // Non-terminal status updates still dropped (feedback loop prevention)

  The FLY → TaskArtifactUpdateEvent conversion:
  - First FLY: {Append: false, Artifact: {ID: deterministic, Parts: [TextPart(payload)]}}
  - Subsequent: {Append: true, Artifact: {ID: same, Parts: [TextPart(payload)]}}
  - On task completion: {Append: true, LastChunk: true, ...} (or just the terminal status event)

  5. StoreAdapter — Skip PG Writes for Artifact Appends~~ (unchanged logic, corrected context)

  Save() returns early for artifact append events. No state proxy involvement. The in-memory accumulated artifact in Manager.lastSaved
  serves only the active SSE stream — it's not persisted anywhere by the gateway. When the task completes, the final result delivery is
  handled by whatever mechanism already exists (envelope payload in PG, actor-provided URLs, etc.) — that's outside this aint's scope.


   The gateway does NOT access the state proxy directly. The state proxy is an actor-level sidecar. Actors read/write /state/... paths,
  and actors can return URLs to stored data. The gateway never reads from the state proxy storage backend.

  (I was confused by the existing stateproxy.Reader in store_adapter.go:21 — but if that's not the intended architecture, it's a
  separate concern.)

  This correction actually simplifies our design for this aint. The artifact delivery question ("how does tasks/get return final
  results?") is entirely separate from the FLY streaming problem. For this aint, we only care about:

  1. FLY events become ephemeral — remove PG INSERT, use PG NOTIFY
  2. FLY SSE endpoint on API gateway — for Asya-native clients
  3. A2A artifact chunking — convert FLY to TaskArtifactUpdateEvent{Append} in waitAndRelayEvents
  4. Save() skips PG for artifact appends — returns early, in-memory only

  None of these touch the state proxy. The final artifact delivery mechanism (how tasks/get returns results) is orthogonal and can stay
  as-is or be addressed in a separate aint.



  6. Remove FLY from task_updates Table

  FLY events no longer write to task_updates.partial_payload. The column stays (for GetUpdates replay of progress events) but FLY events
   never populate it.

  In testing/single-gateway mode: notifyListeners() (in-process) handles FLY directly — no PG NOTIFY needed, no DB write.

  Data Flow Diagram

                           DUAL-GATEWAY MODE

  Sidecar ──POST /mesh/{id}/fly──→ Mesh Gateway
                                        │
                                        ├─ pg_notify('fly', 'task_id:payload')
                                        └─ notifyListeners() [in-process, testing mode only]

                                        │ PG LISTEN/NOTIFY (in-memory, no storage)
                                        ▼
                                   API Gateway
                                        │
                           ┌────────────┼────────────┐
                           │            │            │
                      FLY SSE      A2A SSE       (discard if
                      endpoint    event queue     no subscriber)
                           │            │
                      Raw FLY      TaskArtifact
                      payload      UpdateEvent
                           │       {Append: true}
                           │            │
                           ▼            ▼
                      Asya-native   Standard A2A
                      clients       clients

  Risk Mitigations

  ┌──────────────────────────────────────────┬───────────────────────────────────────────────────────────────────────────────────┐
  │                   Risk                   │                                    Mitigation                                     │
  ├──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
  │ PG NOTIFY 8KB limit                      │ LLM tokens are tiny (~50-200 bytes). For rare large FLY events: truncate or skip  │
  ├──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
  │ Lost notifications during PG reconnect   │ Acceptable — FLY is ephemeral. Client sees brief gap in tokens                    │
  ├──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
  │ Fan-out to all API replicas              │ O(1) map lookup to filter. Optimize with channeled notifications later if needed  │
  ├──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
  │ Pod crash loses in-memory artifact state │ Final artifact lives in state proxy. tasks/get always works                       │
  ├──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
  │ Save() feedback loop                     │ Artifact append → Save() returns early → no PG write → no notifyListeners cascade │
  └──────────────────────────────────────────┴───────────────────────────────────────────────────────────────────────────────────┘

  What Changes, What Doesn't

  ┌─────────────────────┬────────────────────────────────────────────────────────────────────┐
  │      Component      │                               Change                               │
  ├─────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ HandleMeshFly       │ Remove UpdateProgress() INSERT, add pg_notify()                    │
  ├─────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ PgStore             │ Add PG LISTEN goroutine + dispatch to subscribers                  │
  ├─────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ waitAndRelayEvents  │ Relay FLY events as TaskArtifactUpdateEvent{Append} via eq.Write() │
  ├─────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ StoreAdapter.Save() │ Skip PG write for artifact append events                           │
  ├─────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ API gateway routes  │ Add FLY SSE endpoint (protocol-agnostic)                           │
  ├─────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ Sidecar             │ No changes — still POSTs to /mesh/{id}/fly                         │
  ├─────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ State proxy         │ No changes — still handles final artifact persistence              │
  ├─────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ /mesh/{id}/progress │ No changes — still writes status metadata to PG                    │
  ├─────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ /mesh/{id}/final    │ No changes — still writes terminal status to PG                    │
  └─────────────────────┴────────────────────────────────────────────────────────────────────┘
