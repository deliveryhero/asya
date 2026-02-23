---
title: "Sidecar: implement retry logic with exponential backoff and MRO-based error classification"
priority: 1 # high
type: task
dependencies:
  - 1c46/1f4znp
  - 1c46/1fj60s
  - 1c46/1fsy0p
  - 1c46/1f6ff6
---





Add retry logic to the sidecar's message processing flow in src/asya-sidecar/internal/router/router.go.

When runtime returns an error:
1. Parse error type and MRO from runtime response
2. Check nonRetryableErrors list -- if error type or any MRO ancestor matches -> route to _sink (failed, NonRetryableFailure)
3. Check attempt >= max_attempts -> route to _sink (failed, MaxRetriesExhausted)
4. Otherwise: increment attempt, compute delay, ACK original, SendWithDelay(own queue, updated message, delay)

Backoff formula: delay = min(initialInterval * backoffCoefficient^(attempt-1), maxInterval)
If jitter: delay *= random(0.5, 1.5)

On success after retry: clear status.error, reset attempt to 1 for next actor, strip retry state.

Read resiliency config from ASYA_RESILIENCY_* env vars (see config parsing bead).

Depends on: transport SendWithDelay, message status field, runtime MRO.

RFC: .worktrees/rfc0/docs/rfc/error-handing/rfc-error-handing.md (Sidecar Error Handling Contract section)


---
**Close reason**: Implemented in PR #181


---
_Migrated from beads `asya-t4kc`_
