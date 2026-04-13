---
title: "Integration test: full streaming path (runtime -> sidecar -> gateway -> SSE client)"
status: merged
priority: 2
parent: nlg57
tags:
  - pr:209
---

Add an integration test (Docker Compose) that validates the full partial event
streaming pipeline end-to-end:

1. Runtime: generator handler yields `upstream({"token": "..."})` events
2. Sidecar: parses SSE, calls `POST /tasks/{id}/partial` on gateway
3. Gateway: broadcasts `event: partial` on SSE stream
4. Test client: connects to `GET /tasks/{id}/stream`, receives partial events

Test scenarios:
- Happy path: multiple partial events followed by downstream result
- Mid-stream error: partial events then error event
- No partial events: regular batch handler (no streaming)
- Late-joining SSE client: receives historical partial events

Location: `testing/integration/sidecar-runtime/` or new suite
Infrastructure: Docker Compose with runtime + sidecar + gateway containers

See RFC Section 3 for architecture and Section 4 for error handling semantics.
