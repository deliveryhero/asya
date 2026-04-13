# Implementation Phases: A2A Protocol Compliance

**Source of truth**: `rfc.md` (supersedes all previous design)
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

**Status**: Complete (all merged)

| # | Ref | Task | Deps | Status |
|---|-----|------|------|--------|
| 1 | `1qtbxr` | DB migration: tools table + new status values | None | Merged |
| 2 | `1qcmsr` | Import a2a-go v0.3.7 + state mapping | None | Merged |
| 3 | `1qn6p7` | Tool registry + /mesh/expose API | T1 | Merged |
| 4 | `1qzr7p` | Message-to-envelope translator | T2 | Merged |
| 5 | `1qv3q2` | A2AStoreAdapter wrapping PgStore | T2 | Merged |
| 6 | `1qx70r` | AsyaExecutor + skill resolution | T3, T4, T5 | Merged |
| 7 | `1qdvt8` | Wire a2a-go handler + Agent Card + endpoint layout | T3, T6 | Merged |
| 8 | `1q8x33` | Rename /partial → /fly + A2A-native FLY format | T7 | Merged |

## Phase 2: Production Readiness

**Status**: Complete (PR #259, merged)

| # | Ref | Task | Deps | Status |
|---|-----|------|------|--------|
| 9 | `932x` | ListTasks with cursor pagination | None | Merged |
| 10 | `m19w` | CancelTask endpoint | None | Merged |
| 11 | `zr7m` | Blocking mode for SendMessage | None | Merged |
| 12 | `tuw5` | API Key authentication middleware | None | Merged |
| 13 | `8cnd` | Runtime FLY helpers (fly_text, fly_status) | None | Merged |

## Phase 3: Advanced Features

**Status**: Complete (all merged)

| # | Ref | Task | Deps | Status |
|---|-----|------|------|--------|
| 14 | `7fuy` | Bearer/JWT authentication | T12 (`tuw5`) | Merged |
| 15 | `qf0l` | Extended Agent Card (GetExtendedAgentCard) | T14 (`7fuy`) | Merged |
| 16 | `tgfp` | GetTask history and artifacts from S3 | None | Merged (PR #273) |

## Phase 4: Extended Protocol

| # | Task | Description |
|---|------|-------------|
| 17 | Push notification CRUD | 4 methods + webhook delivery + DB table |
| 18 | gRPC transport | `a2agrpc.NewHandler()` from a2a-go |
