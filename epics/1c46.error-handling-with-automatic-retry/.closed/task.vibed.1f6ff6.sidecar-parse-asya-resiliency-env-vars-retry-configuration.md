---
title: "Sidecar: parse ASYA_RESILIENCY_* env vars for retry configuration"
priority: 2 # medium
type: task
---




Add resiliency configuration parsing to the sidecar in src/asya-sidecar/internal/config/.

New env vars:
- ASYA_RESILIENCY_RETRY_POLICY (constant|exponential, default: exponential)
- ASYA_RESILIENCY_RETRY_MAX_ATTEMPTS (int, default: 3)
- ASYA_RESILIENCY_RETRY_INITIAL_INTERVAL (duration, default: 1s)
- ASYA_RESILIENCY_RETRY_MAX_INTERVAL (duration, default: 300s)
- ASYA_RESILIENCY_RETRY_BACKOFF_COEFFICIENT (float, default: 2.0)
- ASYA_RESILIENCY_RETRY_JITTER (bool, default: true)
- ASYA_RESILIENCY_NON_RETRYABLE_ERRORS (comma-separated list, default: empty)
- ASYA_RESILIENCY_SLA_TIMEOUT (duration, default: empty/no timeout)

Parse into a ResiliencyConfig struct. Validate: maxAttempts >= 0, coefficient >= 1.0, intervals > 0.
Fail fast on invalid config (following project's no-defaults policy for required vars -- but these have sensible defaults as this is optional config).

Note: these env vars follow project fail-fast policy for REQUIRED vars, but resiliency config is OPTIONAL -- actors without it simply don't retry (attempt=1, max_attempts=1).

Unit tests: test parsing, validation, edge cases.

RFC: .worktrees/rfc0/docs/rfc/error-handing/rfc-error-handing.md (Resiliency Configuration section)


---
**Close reason**: Implemented ResiliencyConfig parsing with 12 new unit tests


---
_Migrated from beads `asya-na6q`_
