---
title: "ADR: URI-Based Consistent Hash Routing (No Custom Header)"
status: accepted
date: 2026-04-17
---

# ADR: URI-Based Consistent Hash Routing (No Custom Header)

## Context

The mesh-api needs consistent hash routing so that sidecar callbacks and SSE
subscribers for the same envelope land on the same pod. An earlier design
proposed a custom HTTP header (`X-Asya-Envelope-ID`) set by the sidecar on
every request and used by nginx `upstream-hash-by`.

This was rejected because:
- It requires the sidecar to add a header to every HTTP request
- It's an internal implementation detail leaking into the protocol
- The envelope ID is already in the URL path for every request that needs
  hash routing (`/api/v1/mesh/{id}/events`, `/api/v1/mesh/{id}`)

## Decision

**nginx extracts the envelope ID from the URI path** using a `map` directive.
No custom HTTP header needed.

```nginx
map $uri $envelope_id {
    ~^/api/v1/mesh/([^/]+) $1;
    default "";
}
```

Ingress annotation: `upstream-hash-by: "$envelope_id"`

When `$envelope_id` is empty (e.g., `POST /api/v1/mesh/?actor=foo` for
creation), nginx uses round-robin — which is correct (creation has no
existing ID to hash on).

## Consequences

- No `X-Asya-Envelope-ID` header in sidecar code
- No header in any HTTP request
- Simpler sidecar implementation (just POST to URL)
- The routing decision is fully in the networking layer (Ingress config)
- All ID-bearing URLs (`/api/v1/mesh/{id}/*`) are automatically hash-routed
- Creation URL (`/api/v1/mesh/?actor=foo`) has no ID segment -> empty hash -> round-robin

## Alternatives Considered

- **Custom HTTP header**: requires sidecar changes, leaks implementation
  detail, extra work per request. Rejected.
- **Ingress generates ID** (nginx $request_id): networking layer generating
  application state. Rejected.
- **Application-level routing**: pods route to each other directly. Rejected
  (unreliable, no NetworkPolicy compliance).
