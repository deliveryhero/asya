---
title: Rename asya Message to Envelope
status: merged
priority: 2
---

Rename Asya's internal envelope (id, route, payload, status,
headers) from "message" to "envelope" to avoid collision with A2A "Message"
(immutable communication turn) and MQ "message" (queue entry).

## Motivation

- A2A protocol uses "Message" for conversation turns (user/agent role, parts,
  contextId). Asya's internal "message" is a fundamentally different thing: a
  mutable envelope with route, payload, and status that travels through the
  actor mesh.
- The naming collision causes confusion in gateway code that handles both A2A
  Messages and internal envelopes.
- The rename frees "message" for exclusive A2A use in the gateway layer.

## Scope

### Gateway internal routes: `/tasks/` -> `/mesh/`

The sidecar-facing internal endpoints currently live under `/tasks/`:

```
POST /tasks/{id}/progress   — sidecar reports actor progress
POST /tasks/{id}/final      — end actors report completion
GET  /tasks/{id}/active     — sidecar checks envelope liveness
GET  /tasks/{id}/stream     — SSE streaming (legacy clients)
GET  /tasks/{id}            — envelope status
POST /tasks/{id}/partial    — streaming partial data
POST /tasks                 — fanout child creation
```

These are about **envelope lifecycle**, not A2A tasks. Rename to `/mesh/`:

```
POST /mesh/{id}/progress
POST /mesh/{id}/final
GET  /mesh/{id}/active
GET  /mesh/{id}/stream
GET  /mesh/{id}
POST /mesh/{id}/partial
POST /mesh
```

This frees `/tasks/` for exclusive A2A use (`/a2a/tasks/{id}`, etc.) and
eliminates the collision between the sidecar-facing internal API and the
client-facing A2A API.

**Sidecar changes**: Update the gateway URL format strings in
`src/asya-sidecar/internal/progress/reporter.go`:
- `"%s/tasks/%s/progress"` -> `"%s/mesh/%s/progress"`
- `"%s/tasks/%s/final"` -> `"%s/mesh/%s/final"`
- `"%s/tasks/%s/active"` -> `"%s/mesh/%s/active"`
- etc.

**Crew actor changes**: Update x-sink and x-sump gateway URL references.

### Go (asya-sidecar, asya-gateway)

- `src/asya-sidecar/pkg/messages/message.go` — `Message` struct -> `Envelope`
- `src/asya-sidecar/internal/` — all references to `Message`, `msg`, etc.
- `src/asya-sidecar/internal/progress/reporter.go` — gateway URL format strings
- `src/asya-gateway/pkg/types/` — any internal message types
- `src/asya-gateway/cmd/gateway/main.go` — route registrations (`mux.HandleFunc`)
- Variable names, function names, log messages

### Python (asya-runtime, asya-crew, asya-cli)

- `src/asya-runtime/asya_runtime.py` — internal references
- `src/asya-crew/` — crew actor message handling
- `src/asya-cli/` — flow compiler references
- ABI protocol documentation

### Documentation

- `docs/architecture/` — all architecture docs
- `AGENTS.md` — message protocol section

### Tests

- All test files referencing "message" in the internal envelope sense

## Constraints

- A2A wire protocol uses "message" — stays as-is
- AMQP/SQS term "message" for queue entries — stays as-is (external)
- Only Asya's own type names, variable names, and documentation change
- Name is provisional — may be renamed again later

## Non-Goals

- Changing the queue-level wire format (JSON field names in transit)
- Changing MCP or A2A protocol endpoints (those stay as `/mcp`, `/a2a/`)
- Changing the JSON field names inside envelope bodies (id, route, payload, etc.)
