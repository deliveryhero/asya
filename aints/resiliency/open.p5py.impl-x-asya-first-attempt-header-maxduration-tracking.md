---
title: "impl: x-asya-first-attempt header for maxDuration tracking"
priority: 2 # medium
dependencies:
  - nqf5
---

## Context

`[7179]` adds `policies.*.maxDuration` — a total wall-clock budget across all retry
attempts. The sidecar needs to know when the *first* attempt occurred to evaluate
`time.Since(firstAttempt) >= policy.MaxDuration` before each retry.

This cannot be derived from attempt count alone (backoff delays vary). It must be
stored in the envelope and survive re-enqueue across retry hops.

## Design

### Header: `x-asya-first-attempt`

A RFC3339 timestamp set by the sidecar on the first attempt and never overwritten.

**Lifecycle:**
- On first execution of a message (no prior `x-asya-first-attempt` in headers):
  sidecar sets `msg.Headers["x-asya-first-attempt"] = time.Now().UTC().Format(time.RFC3339)`
  before calling the runtime
- On retry: header already present — sidecar leaves it unchanged
- On `retryMessage`: header is preserved in the re-enqueued envelope (sidecar copies
  all headers when constructing the retry message)

**Evaluation (in `applyPolicy`):**

```go
if policy.MaxDuration > 0 {
    if raw, ok := msg.Headers["x-asya-first-attempt"].(string); ok {
        if first, err := time.Parse(time.RFC3339, raw); err == nil {
            if time.Since(first) >= policy.MaxDuration {
                // treat as exhausted — apply thenRoute or sendRetryFailure
            }
        }
    }
    // if header absent or unparseable: skip maxDuration check (backward compat)
}
```

**Backward compatibility:** Not needed. But for durability, if `x-asya-first-attempt` is absent (messages enqueued
before this feature ships), the `maxDuration` check is skipped with explicit warning. 
`maxAttempts` still applies normally.

### Edge cases

- **Clock skew**: using `time.Since` on the sidecar's local clock. Retry messages
  stay within the same cluster; skew between sidecar pods is negligible (NTP-synced).
  No cross-datacenter concern.
- **Header poisoning**: if a caller injects a past timestamp, `maxDuration` could
  fire on the first attempt. Acceptable — this header is internal (`x-asya-*` prefix
  convention signals internal headers not to be set by flow authors).
- **maxDuration = 0 / unset**: check skipped entirely; only `maxAttempts` governs
  stopping.

## Implementation plan

### 1. Sidecar: set header on first attempt

`src/asya-sidecar/internal/router/router.go`:

In the message dispatch path, before calling `callRuntime`:
```go
if _, exists := msg.Headers["x-asya-first-attempt"]; !exists {
    msg.Headers["x-asya-first-attempt"] = time.Now().UTC().Format(time.RFC3339)
}
```

### 2. Sidecar: evaluate maxDuration in applyPolicy

`src/asya-sidecar/internal/router/router.go` (part of `[7179]` `applyPolicy`):

Add `isDurationExhausted(msg, policy) bool` helper:
```go
func isDurationExhausted(msg *envelopes.Envelope, policy PolicyConfig) bool {
    if policy.MaxDuration <= 0 {
        return false
    }
    raw, ok := msg.Headers["x-asya-first-attempt"].(string)
    if !ok {
        return false
    }
    first, err := time.Parse(time.RFC3339, raw)
    if err != nil {
        return false
    }
    return time.Since(first) >= policy.MaxDuration
}
```

Stopping condition in `applyPolicy`:
```go
exhausted := msg.Status.Attempt >= policy.MaxAttempts || isDurationExhausted(msg, policy)
```

### 3. Sidecar config

`src/asya-sidecar/internal/config/config.go` (part of `[7179]`):

`PolicyConfig.MaxDuration time.Duration` — parsed from YAML duration string
(`600s`, `10m`, `1h`). Already captured in `[7179]` schema.

### 4. Unit tests

`src/asya-sidecar/internal/router/router_retry_test.go`:

- `maxDuration` not set → only `maxAttempts` governs stopping
- `maxDuration` exceeded before `maxAttempts` → exhausted, applies thenRoute
- `maxAttempts` exhausted before `maxDuration` → exhausted, applies thenRoute
- Header absent → `maxDuration` check skipped (backward compat)
- Header unparseable → `maxDuration` check skipped
- Header already set on retry → preserved unchanged, not overwritten

## Acceptance criteria

- [ ] `x-asya-first-attempt` set on first attempt, never overwritten on retry
- [ ] `isDurationExhausted` returns false when header absent or `maxDuration` unset
- [ ] Stopping condition is `maxAttempts OR maxDuration exceeded` (whichever first)
- [ ] Re-enqueued retry messages preserve `x-asya-first-attempt` header
- [ ] Unit tests cover all edge cases above

## Dependencies

- `[nqf5]` — `sendRetryFailure` must route through x-sink before this lands
