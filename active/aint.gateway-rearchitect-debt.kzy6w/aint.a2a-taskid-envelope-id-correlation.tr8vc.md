---
title: "debt: A2A task id decoupled from mesh envelope id breaks --show-traces, tasks/get, client polling"
status: open
priority: 2
tags: [gateway-rearchitect, debt, a2a, tracing, observability]
---

## Problem

The A2A adapter mints (or receives from the a2a-srv framework) its own **A2A task id**
and creates a **separate** mesh envelope with a server-generated **envelope id**. The two
ids differ, and nothing reconciles them durably. Every consumer that holds the A2A task id
and then tries to look up trace/state/data by it fails.

Concrete evidence (live, 2026-06-11, pubsub-gcs + pvc-kv demo cluster):
- `asya k send text-improver … --a2a` returned A2A task id `019eb6cb-4b16-75bf-…`
- the mesh envelope/actor-span id was `3cc756af-…` (seen in actor logs + Tempo)
- `GET /api/v1/mesh/3cc756af-…` → 200 `succeeded`; `GET /api/v1/mesh/019eb6cb-…` → 404
- Tempo had the spans, tagged `asya.envelope_id=3cc756af-…`
- `asya k send … --show-traces` queries `{span.asya.envelope_id="019eb6cb-…"}` → **No traces found**
- After a gateway pod restart, `tasks/get 019eb6cb-…` → `task not found` (the in-memory map is gone)

## Root cause (code trace)

1. **A2A adapter** `src/asya-gateway/internal/a2aadapter/executor.go`:
   - `taskID := reqCtx.TaskID` (line ~49) — A2A task id, set by the a2a-srv framework before Execute.
   - `createResp, _ := e.meshClient.Create(ctx, agent.Actor, …)` (line ~82) — mesh-api mints
     `createResp.ID` (the envelope id); these are different values.
   - Headers include `"x-asya-a2a-task-id": string(taskID)` (line ~85) — the A2A task id *is*
     propagated into the envelope, but only as a header.
   - `e.store.RegisterTask(taskID, createResp.ID)` (line ~97) — registers the mapping.
2. **The mapping is in-memory only**: `src/asya-gateway/internal/a2aadapter/store.go:33`
   `s.taskToMsg[a2aTaskID] = meshMsgID` (guarded by a mutex, no persistence). Lost on restart →
   `tasks/get` 404s after restart (matches the pvc-kv state-persistence observation).
3. **Spans are tagged with the envelope id, not the task id**:
   `src/asya-sidecar/internal/router/router.go:92` → `attribute.String("asya.envelope_id", msg.ID)`.
   The `x-asya-a2a-task-id` header is available on the envelope but is **not** emitted as a span attr.
4. **CLI searches by the A2A task id as if it were the envelope id**:
   `src/asya-lab/asya_lab/k_cli.py:1206-1277` (`_show_trace`) builds
   `{span.asya.envelope_id="<task_id>"}` where `<task_id>` is the value returned by `message/send`
   (the A2A task id). No span carries that value → never matches.
5. `meshclient.CreateRequest` (`src/asya-gateway/internal/meshclient/client.go:17`) has only
   `Payload/Headers/Timeout` — **no id field** — so the adapter cannot today ask mesh-api to use the
   A2A task id as the envelope id.

## Impact

- `asya k send --show-traces` never finds traces (demo-visible; README advertises this).
- A2A `tasks/get` / `tasks/resubscribe` / push notifications fail to resolve after a gateway
  restart (in-memory map), and any external A2A client that polls by the returned task id can't
  correlate it to mesh state or Tempo traces.
- Affects all transports/backends; independent of pg-kv vs pvc-kv.

## Fix

**Option A (recommended): one id end-to-end — A2A task id == mesh envelope id.**
Add an optional `Id` field to `meshclient.CreateRequest` and the mesh-api `POST /api/v1/mesh/`
handler so a caller may supply the envelope id; the a2a adapter passes `taskID` as the envelope id.
Then task id == envelope id == `asya.envelope_id` span attr → `--show-traces` works, `tasks/get`
needs no map (look up by id directly via mesh-api), push/poll all correlate. Drop the in-memory
`RegisterTask`/`taskToMsg`. This mirrors how the pre-split gateway behaved (the old README
`--show-traces` searched by task id and found the spans). Verify the a2a-srv framework accepts an
externally-determined task id (it exposes `reqCtx.TaskID`; confirm it can be set/echoed).

**Option B (smaller, tracing-only): stamp the A2A task id onto spans.**
Emit `asya.a2a_task_id` from the `x-asya-a2a-task-id` header in the sidecar
(`router.go` alongside `asya.envelope_id`) and in the runtime, and have `_show_trace` query
`{span.asya.a2a_task_id="<task_id>"}`. Fixes traces only; does **not** fix `tasks/get` after restart.

**Option C (orthogonal, for tasks/get durability): persist the task→envelope map.**
If Option A is not taken, persist `RegisterTask` in the state proxy (pg-kv/pvc-kv) so `tasks/get`
survives restarts. Still leaves `--show-traces` broken unless combined with B.

Prefer **A**; it subsumes B and C.

## Verification

- `asya k send <flow> --show-traces` renders the ASCII span table (traces found by the returned id).
- `tasks/get <task-id>` resolves after `kubectl delete pod` of the gateway (pvc-kv backend).
- `GET /api/v1/mesh/<returned-task-id>` returns the task (id unified).
- e2e: extend a tracing test to assert a span exists with the returned A2A task id.
