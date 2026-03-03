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

| # | Task | Description | Deps |
|---|------|-------------|------|
| 1 | DB migration: tools table | Create `tools` table (Section 13.4), add new status values | None |
| 2 | Import a2a-go + state mapping | `go get a2a-go@v0.3.7`, state translation functions | None |
| 3 | Tool registry + /mesh/expose API | `internal/toolstore/`, POST/GET handlers, remove YAML config | T1 |
| 4 | Message-to-envelope translator | `internal/a2a/translator.go`, payload construction rules (Section 5.2) | T2 |
| 5 | A2AStoreAdapter | Wrap PgStore for `a2asrv.TaskStore` interface | T2 |
| 6 | AsyaExecutor + skill resolution | Execute, Cancel, resume detection, skill resolution (Section 8.3) | T3, T4, T5 |
| 7 | Wire a2a-go handler + Agent Card | Mount handler, endpoint layout (/a2a, /mcp, /mesh), Agent Card | T3, T6 |
| 8 | Rename /partial -> /fly + A2A-native FLY | Gateway + sidecar rename, FLY dict -> SSE event mapping | T7 |

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
