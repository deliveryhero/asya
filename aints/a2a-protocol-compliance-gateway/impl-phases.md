# Implementation Phases: A2A Protocol Compliance (Epic 1c0d)

**Source of truth**: `rfc-a2a-native.md` (supersedes all previous design)
**Library**: `a2a-go` v0.3.7 (stable)

```
  T1 (DB migration)  ──────> T3 (tool registry) ──┐
                                                  ├──> T6 (executor) ──> T7 (wire handler) ──> T8 (FLY rename)
  T2 (a2a-go import) ──┬──> T4 (translator) ──────┘
                       └──> T5 (store adapter) ───┘
```

## Previous Work (Superseded)

Phases 1 and 1.5 (PRs #202, #208) implemented hand-rolled A2A types and endpoints.
The new RFC replaces this with `a2a-go` library integration. All previous slopped
tasks have been moved to `.closed/`.

## Prerequisites (All Complete)

| Epic | Status | What it delivered |
|------|--------|-------------------|
| 1mx1 (envelope rename) | Done | `/tasks/` -> `/mesh/` routes (except `/partial` -> `/fly`) |
| 1ixy (pause/resume) | Done | x-pause, x-resume actors, sidecar integration |
| 1dmf (state proxy) | Done | xattr API (`user.asya.url`, `user.asya.presigned_url`) |

## Phase 1: Core A2A with a2a-go (MVP)

Delivers: a2a-go integration, tools registry, Agent Card, SendMessage,
SendStreamingMessage, GetTask, SubscribeToTask, A2A-native FLY streaming.

**Status**: Not started

| # | Ref | Task | Deps |
|---|-----|------|------|
| 1 | `1c0d/1qtbxr` | DB migration: tools table + new status values | None |
| 2 | `1c0d/1qcmsr` | Import a2a-go v0.3.7 + state mapping | None |
| 3 | `1c0d/1qn6p7` | Tool registry + /mesh/expose API | T1 |
| 4 | `1c0d/1qzr7p` | Message-to-envelope translator | T2 |
| 5 | `1c0d/1qv3q2` | A2AStoreAdapter wrapping PgStore | T2 |
| 6 | `1c0d/1qx70r` | AsyaExecutor + skill resolution | T3, T4, T5 |
| 7 | `1c0d/1qdvt8` | Wire a2a-go handler + Agent Card + endpoint layout | T3, T6 |
| 8 | `1c0d/1q8x33` | Rename /partial → /fly + A2A-native FLY format | T7 |

## Phase 2: Production Readiness

| # | Task | Description |
|---|------|-------------|
| 9 | ListTasks with cursor pagination | Internal TaskStore.List(), context_id/status filtering |
| 10 | CancelTask + sidecar 410 Gone (1c0d/1qtug1) | Cancel endpoint, sidecar handles 410 on progress |
| 11 | Blocking mode | `configuration.blocking: true`, hold connection until terminal |
| 12 | API Key authentication | `ASYA_A2A_API_KEY` middleware on `{base}/a2a/*` |
| 13 | Runtime FLY helpers | `fly_text()`, `fly_status()` in `asya_runtime.py` |

## Phase 3: Advanced Features

| # | Task | Description |
|---|------|-------------|
| 14 | Bearer/JWT authentication | `ASYA_A2A_JWT_*` env vars, JWKS validation |
| 15 | Extended Agent Card | `GetExtendedAgentCard` with auth-gated details |
| 16 | GetTask history/artifacts from S3 | Fetch `payload.a2a.task.history` from S3 for paused/completed |

## Phase 4: Extended Protocol

| # | Task | Description |
|---|------|-------------|
| 17 | Push notification CRUD | 4 methods + webhook delivery + DB table |
| 18 | gRPC transport | `a2agrpc.NewHandler()` from a2a-go |
