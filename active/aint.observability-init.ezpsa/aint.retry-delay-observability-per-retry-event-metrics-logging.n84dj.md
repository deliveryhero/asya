---
title: "Retry delay observability: per-retry-event metrics and logging"
status: open
priority: 3
parent: ezpsa
---

## Context

Existing aint `1fbs` covers error retry metrics by message ID and actor name. This aint is specifically about per-retry-event observability — tracking actual delay durations, retry reasons, and backoff progression.

## Problem

Currently:
- Retry delays are computed but not logged or metriced
- No Prometheus histogram for actual retry delay durations
- No way to see backoff progression for a specific message
- Alert rules can't distinguish "retrying with 1s delay" from "retrying with 300s delay"

## Deliverables

1. **Prometheus metrics** emitted by sidecar on each retry:
   - `asya_retry_total{actor, error_type, policy}` — counter
   - `asya_retry_delay_seconds{actor, policy}` — histogram of actual delays
   - `asya_retry_exhausted_total{actor, reason}` — counter for MaxRetriesExhausted / NonRetryableFailure

2. **Structured log** on each retry event:
   ```json
   {"level": "warn", "msg": "retrying", "actor": "...", "attempt": 3, "delay_ms": 4000, "error_type": "TimeoutError"}
   ```

3. **Structured log** on retry exhaustion:
   ```json
   {"level": "error", "msg": "retry exhausted", "actor": "...", "attempt": 5, "reason": "MaxRetriesExhausted"}
   ```

## Dependencies

- Complements aint `1fbs` (broader error/retry observability)
- Sidecar already has Prometheus client; needs new metrics registration
