---
title: Support per-error-type retry counts in resiliency config
status: open
priority: 3
---

## Context

Error-handling RFC ADR-001 chose a global retry counter (`maxAttempts` applies to all error types). The RFC noted a future extension: `ASYA_RESILIENCY_RETRY_MAX_ATTEMPTS__ValueError=2` (double-underscore separator for per-type overrides).

## Problem

With a global counter, if a message hits 3 different transient errors (network, timeout, rate limit), it exhausts `maxAttempts` even though each error type only occurred once. For actors that interact with multiple external services, per-error-type counting gives finer control.

## Proposed Solution

### XRD Extension
```yaml
resiliency:
  retry:
    maxAttempts: 5              # global default
    perErrorAttempts:           # per-type overrides (optional)
      - error: RateLimitError
        maxAttempts: 10         # more retries for rate limits
      - error: TimeoutError
        maxAttempts: 3          # fewer for timeouts
```

### Sidecar Changes
- Track `map[errorType]int` instead of single `attempt` counter
- Status field: keep flat `attempt` for backward compat, add `attempts_by_type` as supplementary
- Exhaustion check: per-type count >= per-type max, OR global count >= global max

## Complexity Assessment

Medium. Main risk is status field bloat and backward compatibility with existing `attempt` integer field.
