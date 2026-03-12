---
title: "Implement circuit breaker in sidecar (Dapr-inspired, CEL trip expressions)"
priority: 2 # medium
---

## Context

The error-handling RFC (`.aint/aints/.closed/error-handling/rfc.md`) designed circuit breaker support but deferred it. This is the biggest resiliency gap vs Dapr.

## Problem

Without a circuit breaker, a failing downstream dependency (LLM API outage, database down) causes `maxAttempts * queue_depth` wasted calls. Every message retries to exhaustion before failing, amplifying load on the already-struggling dependency.

## Desired Behavior

Dapr-style circuit breaker with three states:
- **Closed** (normal): requests pass through
- **Open** (tripped): requests fail-fast without calling runtime, routed to x-sump
- **Half-Open** (recovery): allow `maxRequests` test requests to check if dependency recovered

### XRD Configuration

```yaml
resiliency:
  circuitBreaker:
    maxRequests: 1          # concurrent requests in half-open state
    interval: 30s           # metrics reset window
    timeout: 60s            # how long to stay open before half-open
    trip: consecutiveFailures > 5  # CEL expression
```

### Trip Expression Variables (CEL)

- `consecutiveFailures` — sequential failed requests
- `totalFailures` — non-consecutive total failures in interval
- `requests` — total requests in interval

## Open Questions

1. **State storage**: Circuit breaker state is per-pod (in-memory). Lost on pod restart. Acceptable? Or shared storage (Redis, NATS KV)?
2. **Scope**: Per-actor-type (shared across all messages) or per-destination?
3. **Metrics**: Prometheus gauge for circuit state (closed=0, half-open=1, open=2)

## References

- Dapr circuit breaker: https://docs.dapr.io/operations/resiliency/policies/circuit-breakers/
- Error handling RFC ADR-006: adopted Dapr model, circuit breaker deferred
- Go library: `github.com/sony/gobreaker` (implements the same state machine)
