# Implementation Phases: Pause/Resume Actors

**Epic**: 1ixy
**RFC**: `rfc.md` (in this directory)

## Dependency Graph

```
Phase A (Gateway + Sidecar)                  Phase B (Crew Actors)
─────────────────────────────                ─────────────────────

[1kwi46]  [1kitzu]  [1kx4xg]
Types      Constants  Migration
  │           │         │
  ├───────────┼─────────┤
  │           │         │
  │      [1kftbu]       │
  │      Sidecar ───────┼──────────────────> [1kcw5i]
  │      pause hdr      │                    x-pause crew ──────┐
  │           │         │                    (+ debt/1k34nz)     │
  ├───────────┴─────────┤                                       │
  │                     │                                  [1kk0r7]
  │    [1kmp6r]         │                                  Helm chart
  │    Accept pause ────┤                                       │
  │      │              │                                       │
  │      ├──> [1knc3h]  │                    [1kr9uw]            │
  │      │    Ext pause │                    x-resume crew ─────┘
  │      │              │                    (dep: 1kjvyj)
  │      ├──> [1kjvyj]  │
  │      │    Resume ───┼──────────────────> (feeds x-resume)
  │      │              │
  │      └──> [1knfkr]  │
  │           Timer     │
  │           freeze    │
  │                     │
  ├──> [1k2yps]         │                    [1kpm6e]
  │    Cancel           │                    Integration tests
  │                     │                    (all Phase A + B)
  └──> [1ka9sc]         │
       List tasks ──────┘
```

---

## Phase A: Gateway State Machine + Sidecar

**PR scope**: Types, DB migration, sidecar pause header detection, gateway
pause/resume/cancel/list endpoints, and timeout freeze/thaw. No crew actors —
pause can be tested via mock progress reports.

**Why first**: Gateway is the external API surface. Crew actors (Phase B) need
the gateway to accept `paused` phase and the sidecar to forward `x-asya-pause`
headers before they can function end-to-end.

### A.1 — Foundation (no dependencies)

| Ref | Task | Component |
|-----|------|-----------|
| `1ixy/1kwi46` | Add `TaskStatusPaused`, `TaskStatusCanceled` to types; A2A state mapping (`paused` -> `input_required`, `canceled` -> `canceled`) | `src/asya-gateway/pkg/types/` |
| `1ixy/1kitzu` | Add `PhasePaused`, `PhaseCanceled` constants | `src/asya-sidecar/pkg/messages/message.go` |
| `1ixy/1kx4xg` | DB migration 008: `pause_metadata JSONB` column | `src/asya-gateway/migrations/` |

### A.2 — Sidecar + Gateway Core

| Ref | Task | Component |
|-----|------|-----------|
| `1ixy/1kftbu` | Sidecar: detect `x-asya-pause` header in runtime response, report `phase=paused` to gateway, ack message, skip routing | `src/asya-sidecar/internal/router/` |
| `1ixy/1kmp6r` | Gateway: accept `phase=paused` in progress handler, store pause metadata in JSONB, SSE notify with `input_required` | `src/asya-gateway/internal/` |

### A.3 — Gateway Endpoints

| Ref | Task | Component |
|-----|------|-----------|
| `1ixy/1knc3h` | `POST /a2a/tasks/{id}:pause` — external pause (no metadata) | `src/asya-gateway/internal/a2a/` |
| `1ixy/1kjvyj` | Resume via `message/send` with `task_id` — validate paused, create message to x-resume, re-queue | `src/asya-gateway/internal/a2a/` |
| `1ixy/1knfkr` | Freeze/thaw backstop timer — save `remaining_sec` on pause, restart on resume | `src/asya-gateway/internal/taskstore/` |
| `1ixy/1k2yps` | `POST /a2a/tasks/{id}:cancel` — cancel endpoint with terminal state validation | `src/asya-gateway/internal/a2a/` |
| `1ixy/1ka9sc` | `GET /a2a/tasks` — list endpoint with filtering (context_id, status, pagination) | `src/asya-gateway/internal/a2a/` |

**Merge criteria (Phase A)**:
- All existing gateway + sidecar unit tests pass
- New unit tests for each task
- Sidecar: `x-asya-pause` header detected, pause reported, message acked, no routing
- Gateway: paused phase accepted, metadata stored, SSE notification sent
- Gateway: cancel rejects terminal tasks, pause rejects non-active tasks
- Gateway: resume validates paused state, creates x-resume message, re-queues
- Gateway: timer freezes on pause, thaws on resume with correct remaining_sec
- Gateway: list endpoint filters by status, paginates correctly

---

## Phase B: Crew Actors + Integration

**PR scope**: x-pause and x-resume crew actor implementations, Helm chart
additions, and integration tests for the full pause/resume flow.

**Why second**: Depends on Phase A — sidecar must detect `x-asya-pause` header
and gateway must accept `paused` phase before crew actors can function.

**External dependency**: `debt/1k34nz` (migrate S3 persister to checkpointer
actor) must be merged before x-pause, since x-pause follows the checkpointer
pattern.

| Ref | Task | Component |
|-----|------|-----------|
| `1ixy/1kcw5i` | x-pause handler: verify x-resume in route, persist message to S3, set `x-asya-pause` header, return `None` | `src/asya-crew/` |
| `1ixy/1kr9uw` | x-resume handler: load persisted message, merge user input (configurable shallow/deep), restore route via VFS, stamp `deadline_at` | `src/asya-crew/` |
| `1ixy/1kk0r7` | Helm chart: add x-pause and x-resume actor definitions to asya-crew chart | `deploy/helm-charts/asya-crew/` |
| `1ixy/1kpm6e` | Integration test: full pause/resume flow, external pause, cancel, timeout freeze/thaw | `testing/integration/` |

**Merge criteria (Phase B)**:
- x-pause: persists full message, sets header, returns None
- x-pause: prepends x-resume to route if missing
- x-resume: loads message, merges input at correct payload_key paths
- x-resume: restores route via VFS, stamps new deadline_at
- Helm chart: x-pause + x-resume deploy alongside existing crew actors
- Integration: message pauses, client resumes with input, pipeline continues
- Integration: external pause works without metadata
- Integration: timeout correctly freezes and thaws across pause

---

## Parallelism

```
Time ──────────────────────────────────────────────>

Phase A  ████████████████████████████
Phase B                               ████████████████████
                                      (after Phase A + debt/1k34nz merge)
```

Phase A and Phase B are sequential — B depends on A. However, within Phase A,
tasks A.1 can all be done in parallel, then A.2 in parallel, then A.3 items
are mostly independent of each other (except their shared dependency on A.2).

## Risk Notes

- **External dependency**: `debt/1k34nz` (checkpointer migration) is afoot but
  not merged. Phase B x-pause depends on it. Phase A has no external deps.
- **Timeout interaction**: Freeze/thaw design (save `remaining_sec`, restart on
  resume) excludes human think-time from SLA budget. Different from Temporal
  (wall-clock continues) and from fresh restart (unbounded budget).
- **Backward compatibility**: Existing pipelines without x-pause see no change.
  New phase constants are additive. Gateway ignores unknown phases gracefully.
