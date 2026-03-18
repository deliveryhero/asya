---
title: "Implement circuit breaker in sidecar (Dapr-inspired, CEL trip expressions)"
priority: 2 # medium
---

## Context

The error-handling RFC (`.aint/aints/.closed/error-handling/rfc.md`) designed circuit breaker support but deferred it. This is the biggest resiliency gap vs Dapr.

**Depends on `[7179]`** (policy-based error handling). Circuit breakers extend
the `policies` system as a sub-field — `[7179]` must land first.

## Problem

Without a circuit breaker, a failing downstream dependency (LLM API outage, database down) causes `maxAttempts * queue_depth` wasted calls. Every message retries to exhaustion before failing, amplifying load on the already-struggling dependency.

Key distinction from retry policies:

| | Retry policies (`[7179]`) | Circuit breakers (this) |
|---|---|---|
| Scope | Per-envelope | Cross-envelope, shared state |
| Decision | "This envelope failed N times" | "Enough envelopes failed → stop trying" |
| Problem solved | Transient per-message failures | Protecting a struggling downstream from amplified load |

## Desired Behavior

Dapr-style circuit breaker with three states:
- **Closed** (normal): requests pass through, policy retry logic applies normally
- **Open** (tripped): requests fail-fast without calling runtime, routed via policy `thenRoute`
- **Half-Open** (recovery): allow `maxRequests` test requests to check if dependency recovered

## XRD Configuration

Circuit breaker as an optional sub-field on a `[7179]` policy (no new top-level field):

```yaml
resiliency:
  policies:
    retryPatiently:
      maxAttempts: 3
      backoff: exponential
      initialDelay: 10s
      thenRoute: ["alert-devops"]   # used when exhausted AND when circuit is open
      circuitBreaker:
        trip: consecutiveFailures > 5   # CEL expression
        timeout: 60s                    # how long to stay open before half-open
        interval: 30s                   # metrics reset window
        maxRequests: 1                  # concurrent requests allowed in half-open
  rules:
    - errors: ["openai.RateLimitError"]
      policy: retryPatiently
```

When circuit is open: skip runtime call, route directly to policy `thenRoute`.
Envelope `status.reason` set to `CircuitOpen` so the target actor can distinguish
from a normal exhausted-retry if needed.

### Trip Expression Variables (CEL)

- `consecutiveFailures` — sequential failed requests
- `totalFailures` — non-consecutive total failures in interval
- `requests` — total requests in interval

## Open Questions

1. **State storage**: Per-pod in-memory (lost on restart, simplest) or shared (Redis, NATS KV)?
2. **Scope**: Per-policy per-pod, or per-policy shared across all pods of the actor?
3. **Metrics**: Prometheus gauge for circuit state (closed=0, half-open=1, open=2)

## References

- Dapr circuit breaker: https://docs.dapr.io/operations/resiliency/policies/circuit-breakers/
- Error handling RFC ADR-006: adopted Dapr model, circuit breaker deferred
- Go library: `github.com/sony/gobreaker` (implements the same state machine)
- `[7179]` policy-based error handling (foundation, must land first)
