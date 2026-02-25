# Implementation Phases: A2A Protocol Compliance (Epic 1c0d)

## Phase 1: A2A Foundation + Core Endpoints

**Branch**: `1c0d/phase1-a2a-core`
**Worktree**: `.worktrees/1c0d.phase1-a2a-core`

### Tasks Combined

| Ref | Title | Priority |
|-----|-------|----------|
| 1c0d/1fkrbh | Rename envelope to task throughout gateway | P2 |
| 1c0d/1f5jo3 | A2A error response format | P2 |
| 1c0d/1f2hre | Add context_id for conversation grouping | P2 |
| 1c0d/1f9519 | Agent Card discovery endpoint | P2 |
| 1c0d/1fuhpq | POST /messages endpoint | P2 |
| 1c0d/1fkoxi | POST /messages:stream endpoint | P2 |
| 1c0d/1f2tkx | GET /tasks/{id} A2A endpoint | P2 |
| 1c0d/1fgpla | GET /tasks/{id}:subscribe SSE endpoint | P2 |

### Deliverables

- Renamed internal types (envelope -> task in data layer)
- A2A-compliant error responses
- context_id support in task model and store
- `GET /.well-known/a2a/agent-card` endpoint
- `POST /a2a/` (send message) endpoint
- `POST /a2a/` (streaming variant) endpoint
- `GET /a2a/tasks/{id}` endpoint
- `GET /a2a/tasks/{id}:subscribe` SSE endpoint
- Unit tests for all new code
- Backward compatibility for existing /mcp and /tools/call endpoints

---

## Phase 2: Extended A2A + Sidecar Alignment

**Branch**: `1c0d/phase2-a2a-extended`
**Worktree**: `.worktrees/1c0d.phase2-a2a-extended`

### Tasks Combined

| Ref | Title | Priority |
|-----|-------|----------|
| 1c0d/1fgefe | GET /tasks (list tasks) | P3 |
| 1c0d/1f5b6o | POST /tasks/{id}:cancel | P3 |
| 1c0d/1f7am4 | input_required state for human-in-the-loop | P2 |
| 1c0d/1fl5rf | Update sidecar A2A terminology | P2 |

### Deliverables

- `GET /a2a/tasks` list endpoint with filtering
- `POST /a2a/tasks/{id}:cancel` endpoint
- `input_required` task state with resume flow
- Sidecar progress/final endpoints aligned with A2A terminology
- Integration tests for sidecar <-> gateway with new terminology

---

## Deferred Tasks

| Ref | Title | Priority | Reason |
|-----|-------|----------|--------|
| 1c0d/1fw76h | AG-UI event streaming | P2 | Separate protocol, separate PR |
| 1c0d/1fkicd | Research A2A/ACP/A2UI standards | P3 | Done via RFC |
| 1c0d/1foqab | gRPC transport | P3 | Separate effort |
| 1c0d/1fgyh1 | A2UI payload support | P4 | Backlog |
| 1c0d/1f5373 | Push notification endpoints | P4 | Backlog |
