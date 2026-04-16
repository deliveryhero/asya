---
title: "Phase 2: asya-mesh-api core (/api/v1/mesh/)"
status: open
priority: 1 # high
dependencies:
  - 9bb3j
---

Core mesh API binary: envelope CRUD + SSE streaming + sidecar event receiving. Uses PG state-proxy connector for storage. ~1,000-1,500 LOC Go.

API routes (port 8080 external):
- POST /api/v1/mesh/?actor={name} — create message, dispatch to MQ, return {id}
- GET /api/v1/mesh/{id} — message status from DB
- GET /api/v1/mesh/{id}/events — SSE subscribe (catch-up from DB + live Go channels)
- DELETE /api/v1/mesh/{id} — cancel (set status=canceled)
- GET /api/v1/mesh/ — list messages (filter via /query)

API routes (port 8081 internal):
- POST /api/v1/mesh/{id}/events — sidecar publishes event (type: status|fly)
- GET /api/v1/mesh/{id} — sidecar heartbeat/cancel check

Implementation:
- cmd/mesh-api/main.go — binary entry point
- internal/mesh/ — HTTP handlers
- internal/store/ — MessageStore interface over state-proxy HTTP client
- internal/subscribers/ — in-process Go channel pub/sub for SSE
- pkg/types/ — Message, Event, ListParams types
- Monotonic status ordering (reject stale updates ~10 LOC)
- Stamps x-asya-gateway-url in envelope headers
- Generates envelope ID (UUID)
- Sets route.prev=[], route.next=[], route.curr={actor}
- Queue client: publish envelope to actor queue (reuse existing internal/queue/)

Testing:
- Unit: handlers, status ordering, store client
- Component: Docker Compose with PG state-proxy + MQ, test full CRUD + SSE
- E2E: Kind cluster, sidecar callbacks, cancel/pause flow
- Docs: docs/reference/components/mesh-api.md

Depends on: 9bb3j (PG state-proxy)
