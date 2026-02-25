---
title: "Integration tests: SLA enforcement across sidecar, runtime, and gateway"
priority: 2 # medium
type: task
dependencies:
  - 1crv/1k1pjy
  - 1crv/1kz8ww
---

## Scope

Integration tests validating timeout behavior across multiple components in Docker Compose.

## Test Cases

### SLA enforcement across sidecar + runtime
- Gateway sends message with 5s deadline through a 2-actor pipeline
- First actor processes in 1s (succeeds)
- Second actor receives message with ~4s remaining
- Verify effective timeout is ~4s (not full runtime timeout)

### Retry + SLA interaction
- Message with 10s deadline, actor fails on first attempt (2s processing)
- Retry fires, actor fails again (3s processing)
- Third attempt: remaining SLA < actor_timeout, uses reduced timeout
- Eventually SLA expires: message goes to x-sink, no further retries
- Verify max_attempts NOT exhausted — SLA took precedence

### Gateway backstop
- Message with 3s deadline stuck in queue (actor scaled to zero or slow to consume)
- Gateway backstop timer fires at 3s
- Task marked failed with reason=Timeout
- SSE stream closed (if streaming)
- Sidecar eventually picks up stale message, reports timeout — gateway ignores (already terminal)

## Files
- `testing/integration/sidecar-runtime/tests/` (extend existing suite)
- `testing/integration/gateway-actors/tests/` (extend existing suite)

## Dependencies
- Depends on 1crv/1k1pjy (sidecar SLA enforcement)
- Depends on 1crv/1kz8ww (gateway deadline stamping)

## Wave
Wave 4: Cross-Component Validation
