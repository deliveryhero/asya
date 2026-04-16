---
title: "Phase 3: A2A adapter (asya-a2a-adapter)"
status: open
priority: 1 # high
dependencies:
  - nacr7
---

A2A JSON-RPC adapter that translates A2A protocol to /mesh/ API calls. ~500-800 LOC Go.

Library: a2aproject/a2a-go v2

A2A operations:
- tasks/send -> POST /api/v1/mesh/?actor={actor}, return task status
- tasks/subscribe -> GET /api/v1/mesh/{id}/events via Ingress, proxy as A2A SSE
- tasks/sendSubscribe -> combine send + subscribe
- tasks/get -> GET /api/v1/mesh/{id} + optional state-proxy-envelopes for history
- tasks/cancel -> DELETE /api/v1/mesh/{id}
- GetExtendedAgentCard -> serve from ConfigMap
- State mapping: pending->submitted, running->working, succeeded->completed,
  failed->failed, paused->input_required, canceled->canceled
- envelope.id = A2A task_id, headers.context_id = A2A contextId
- Pause/resume: detect paused task, create resume envelope to x-resume

Implementation:
- cmd/a2a-adapter/main.go
- internal/a2a/ — A2A handler using a2aproject/a2a-go v2
- internal/watcher/ — ConfigMap polling watcher (shared)
- Optional state-proxy-envelopes sidecar (S3) for history hydration
- Agent card generated from ConfigMap (static, hot-reloadable)

ConfigMap schema (asya-a2a-agents):
  agents:
  - name: autoresearch
    description: 'Autonomous ML experimentation agent'
    actor: start-autoresearch
    timeout: 14400
    streaming: true
    skills: [{id: experiment, name: Run experiment, ...}]
    inputModes: [text/plain, application/json]
    outputModes: [text/plain, application/json]

Testing:
- Unit: A2A handler, state mapping, agent card generation
- Component: Docker Compose with mesh-api + PG + MQ, test tasks/send + subscribe
- E2E: Kind cluster, full A2A flow including pause/resume
- Docs: docs/usage/guide-gateway.md (A2A section)

Can be parallelized with Phase 3 MCP (both depend on nacr7, independent of each other).
Depends on: nacr7 (mesh-api)
