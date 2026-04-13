---
title: Rate limiting for outbound handler calls in sidecar
status: open
priority: 3
parent: 00001
---

## Context

Asya has no rate limiting on handler invocations. If an actor calls a rate-limited external API (e.g. OpenAI, Google APIs), rate limiting must be implemented inside the handler.

## Problem

Without framework-level rate limiting:
- Each actor pod independently hammers the API at full speed
- KEDA scales up more pods under load, multiplying the problem
- Users must implement token bucket / leaky bucket in every handler
- No coordination across pods (each pod's rate limiter is independent)

## Options

### Option A: Sidecar-level rate limiter (simple, per-pod)
```yaml
resiliency:
  rateLimit:
    requestsPerSecond: 10
    burst: 5
```
Limitation: per-pod only, no cross-pod coordination.

### Option B: Defer to infrastructure
- Rely on API gateway / service mesh (Istio) rate limiting
- Document the pattern rather than implementing it

## Recommendation

Start with documentation (Option B) showing how to combine `maxAttempts` + `actorTimeout` + handler-level rate limiting. Only build Option A if multiple users request it. The sidecar's single-threaded message loop already provides implicit concurrency=1 per pod.
