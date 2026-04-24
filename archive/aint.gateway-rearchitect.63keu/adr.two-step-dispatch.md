---
title: "ADR: Two-Step Dispatch (Create then Subscribe)"
status: accepted
date: 2026-04-16
---

# ADR: Two-Step Dispatch (Create then Subscribe)

## Context

asya-mesh-api uses consistent hash routing (nginx Ingress, upstream-hash-by
envelope ID extracted from URI path) so that sidecar callbacks and SSE
subscribers for the same message land on the same pod.

Problem: when creating a message, the envelope ID doesn't exist yet. The first
request has no hash key. If creation round-robins to Pod B but hash("abc123")
maps to Pod A, sidecar callbacks go to Pod A while SSE is held on Pod B.

## Decision

**Split message creation into two HTTP calls:**

1. `POST /api/v1/mesh/?actor=foo` -- round-robin, any pod. Generates ID,
   dispatches to MQ, returns `{"id": "abc123"}`. No SSE held.
2. `GET /api/v1/mesh/abc123/events` -- hash-routed by URI-extracted envelope ID.
   Consistent pod holds SSE connection.

The ID exists before the hash-routed request, solving the chicken-and-egg.

## Consequences

- Standard REST pattern (POST creates, GET observes)
- Maps to A2A spec (tasks/send + tasks/subscribe)
- MCP adapter combines both internally (transparent to MCP clients)
- Timing gap between create and subscribe: catch-up from DB on subscribe
- Idempotent: /events retryable on disconnect without re-creating message
- ID generation stays in application code (mesh-api), not Ingress

## Alternatives Considered

- **Ingress generates ID** (nginx $request_id): networking layer generating
  protocol-critical application state violates separation of concerns
- **agentgateway generates ID**: too many conditional paths
- **Application-level pod-to-pod routing**: unreliable across nodes
- **Single request with redirect**: adds latency, client must follow redirects
