---
title: "ADR: Two-Step Dispatch (Create then Subscribe)"
status: accepted
date: 2026-04-14
---

# ADR: Two-Step Dispatch (Create then Subscribe)

## Context

The dispatcher uses consistent hash routing (nginx Ingress, upstream-hash-by
X-Asya-Envelope-ID) so that sidecar callbacks and SSE subscribers for the same
task land on the same pod.

Problem: when creating a task, the envelope ID doesn't exist yet. The first
request has no hash key. If creation round-robins to Pod B but hash("abc123")
maps to Pod A, sidecar callbacks go to Pod A while SSE is held on Pod B.

We considered: generating the ID in the Ingress (nginx $request_id), generating
in agentgateway, application-level re-routing between pods. All added
complexity or violated separation of concerns.

## Decision

**Split task creation into two HTTP calls:**

1. `POST /mesh/` -- round-robin, any pod. Generates ID, dispatches to MQ,
   returns {id, stream_url}. No SSE held.
2. `GET /mesh/{id}/stream` -- hash-routed by X-Asya-Envelope-ID. Consistent
   pod holds SSE connection.

The ID exists before the hash-routed request, solving the chicken-and-egg.

## Consequences

- Standard REST pattern (POST creates, GET observes)
- Maps to A2A spec (tasks/send + tasks/subscribe)
- agentgateway combines both for MCP (transparent to MCP clients)
- Timing gap between create and subscribe: catch-up from DB on subscribe
- Idempotent observation: /mesh/{id}/stream retryable without re-creating task
- ID generation stays in application code (dispatcher), not Ingress

## Alternatives Considered

- **Ingress generates ID** (nginx $request_id): violates separation of concerns,
  networking layer generating protocol-critical application state
- **agentgateway generates ID**: too many conditional paths (if agentgateway
  present, if header missing, etc.)
- **Application-level pod-to-pod routing**: pods can't directly communicate
  reliably across nodes, requires additional infra or service mesh
- **Single request with redirect**: adds latency, client must follow redirects
