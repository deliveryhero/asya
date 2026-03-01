---
title: "Rename asya Message to Meshage"
status: ideated
priority: 2
type: epic
---

Mesh + message. Rename Asya's internal envelope (id, route, payload, status,
headers) from "message" to "meshage" to avoid collision with A2A "Message"
(immutable communication turn) and MQ "message" (queue entry).

## Motivation

- A2A protocol uses "Message" for conversation turns (user/agent role, parts,
  contextId). Asya's internal "message" is a fundamentally different thing: a
  mutable envelope with route, payload, and status that travels through the
  actor mesh.
- The naming collision causes confusion in gateway code that handles both A2A
  Messages and internal meshages.
- The rename frees "message" for exclusive A2A use in the gateway layer.

## Scope

### Go (asya-sidecar, asya-gateway)

- `src/asya-sidecar/pkg/messages/message.go` — `Message` struct -> `Meshage`
- `src/asya-sidecar/internal/` — all references to `Message`, `msg`, etc.
- `src/asya-gateway/pkg/types/` — any internal message types
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
- Changing external API field names (yet)