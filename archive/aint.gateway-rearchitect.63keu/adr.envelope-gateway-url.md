---
title: "ADR: Gateway URL in Envelope Header, Not Env Var"
status: accepted
date: 2026-04-14
---

# ADR: Gateway URL in Envelope Header, Not Env Var

## Context

Sidecars currently read `ASYA_GATEWAY_URL` from an environment variable
injected at deploy time by the Crossplane composition. This creates coupling:

- Gateway URL changes require redeploying all actors
- Different dispatchers can't route tasks through the same actors
- Multi-namespace/multi-cluster setups need per-actor configuration
- The env var is set once at pod creation, immutable for the pod's lifetime

## Decision

**The envelope carries `x-asya-gateway-url` in its headers.** The dispatcher
stamps its own Internal Ingress URL when creating the envelope. The sidecar
reads the URL from the envelope and uses it for all status/FLY callbacks.

```json
{
  "id": "abc123",
  "headers": {
    "x-asya-gateway-url": "http://asya-dispatcher-mesh.asya-system"
  }
}
```

Sidecar falls back to `ASYA_GATEWAY_URL` env var if the header is missing
(backward compatibility with older dispatchers).

## Consequences

- Actors fully decoupled from gateway topology
- Different dispatchers can dispatch to same actors (multi-tenant)
- Gateway URL changes don't require actor redeployment
- No custom HTTP header needed for Ingress routing — the envelope ID is
  already in the URL path (`/api/v1/mesh/{id}/events`), Ingress extracts
  it with a URI map directive
- Backward-compatible: env var works as fallback

## Alternatives Considered

- **Keep env var only**: maintains deploy-time coupling
- **ConfigMap with hot reload**: complex, still per-namespace
- **Service discovery (DNS)**: sidecar would need to know the service name
