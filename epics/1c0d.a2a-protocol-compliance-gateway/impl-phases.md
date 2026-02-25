# Implementation Phases: A2A Protocol Compliance (Epic 1c0d)

## Phase 1: A2A Foundation + Core Endpoints ✅

**Status**: Merged (PR #202)
**Branch**: `1c0d/phase1-a2a-core`

### Tasks Combined

| Ref | Title | Priority | Status |
|-----|-------|----------|--------|
| 1c0d/1fkrbh | Rename envelope to task throughout gateway | P2 | ✅ vibed |
| 1c0d/1f5jo3 | A2A error response format | P2 | ✅ vibed |
| 1c0d/1f2hre | Add context_id for conversation grouping | P2 | ✅ vibed |
| 1c0d/1f9519 | Agent Card discovery endpoint | P2 | ✅ vibed |
| 1c0d/1fuhpq | POST /messages endpoint | P2 | ✅ vibed |
| 1c0d/1fkoxi | POST /messages:stream endpoint | P2 | ✅ vibed |
| 1c0d/1f2tkx | GET /tasks/{id} A2A endpoint | P2 | ✅ vibed |
| 1c0d/1fgpla | GET /tasks/{id}:subscribe SSE endpoint | P2 | ✅ vibed |

### Deliverables

- ✅ Renamed internal types (envelope -> task in data layer)
- ✅ A2A-compliant error responses
- ✅ context_id support in task model and store (Sqitch migration 006)
- ✅ `GET /.well-known/a2a/agent-card` endpoint
- ✅ `POST /a2a/` (send message) endpoint
- ✅ `POST /a2a/` (streaming variant) endpoint
- ✅ `GET /a2a/tasks/{id}` endpoint
- ✅ `GET /a2a/tasks/{id}:subscribe` SSE endpoint
- ✅ Unit tests for all new code
- ✅ Backward compatibility for existing /mcp and /tools/call endpoints

---

## Phase 1.5: Sidecar Terminology Alignment ✅

**Status**: Merged (PR #208)
**Branch**: `1c0d/1fl5rf.update-sidecar-use-a2a-task-terminology`

| Ref | Title | Priority | Status |
|-----|-------|----------|--------|
| 1c0d/1fl5rf | Update sidecar A2A terminology | P2 | ✅ vibed |

- ✅ Replaced "envelope mode" with "VFS mode" in comments
- ✅ Updated test fixture IDs (`test-envelope-*` -> `test-msg-*`)
- ✅ Fixed db/README.md table names to match actual schema

Note: Sidecar API endpoints (`/tasks/{id}/progress`, `/tasks/{id}/final`) were already using task terminology — only comments, tests, and docs needed updates.

---

## Phase 2: Extended A2A Features

**Status**: Not started
**Branch**: TBD

### Remaining Tasks

| Ref | Title | Priority | Status |
|-----|-------|----------|--------|
| 1c0d/1fgefe | GET /tasks (list tasks) | P3 | slopped |
| 1c0d/1f5b6o | POST /tasks/{id}:cancel | P3 | slopped |
| 1c0d/1f7am4 | input_required state for human-in-the-loop | P2 | slopped |

### Deliverables

- `GET /a2a/tasks` list endpoint with filtering
- `POST /a2a/tasks/{id}:cancel` endpoint
- `input_required` task state with resume flow

---

## Deferred Tasks

| Ref | Title | Priority | Reason |
|-----|-------|----------|--------|
| 1c0d/1fw76h | AG-UI event streaming | P2 | Separate protocol, separate PR |
| 1c0d/1fkicd | Research A2A/ACP/A2UI standards | P3 | Done via RFC |
| 1c0d/1foqab | gRPC transport | P3 | Separate effort |
| 1c0d/1fgyh1 | A2UI payload support | P4 | Backlog |
| 1c0d/1f5373 | Push notification endpoints | P4 | Backlog |
