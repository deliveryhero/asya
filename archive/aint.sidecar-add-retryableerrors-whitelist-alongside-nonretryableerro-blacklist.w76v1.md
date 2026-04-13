---
title: "Sidecar: add retryableErrors whitelist alongside nonRetryableErrors blacklist"
status: merged
priority: 2
parent: 00001
tags:
  - superseded-by:7179
---

Add `retryableErrors` (whitelist) field to `ResiliencyConfig` alongside existing `nonRetryableErrors` (blacklist).

## Context

Tenacity's `retry_if_exception_type(E)` means "retry ON these exceptions" (whitelist), while Asya's `nonRetryableErrors` is a blacklist ("don't retry these"). The compiler needs a direct mapping without lossy inversion.

## Changes

### Sidecar (`src/asya-sidecar/`)

1. **`internal/config/config.go`**: Add `RetryableErrors []string` to `ResiliencyConfig`. Parse from `ASYA_RESILIENCY_RETRYABLE_ERRORS` env var (comma-separated FQNs). Validate mutual exclusivity with `NonRetryableErrors` — fail fast if both are set.

2. **`internal/router/router.go`**: Rename `isNonRetryableError` → `shouldRetry`. Logic:
   - If `RetryableErrors` is set: return true only if errorType or MRO ancestor is in the whitelist
   - If `NonRetryableErrors` is set: return false if errorType or MRO ancestor is in the blacklist
   - If neither is set: return true (retry by default)

3. **Tests**: Update `router_retry_test.go` with whitelist scenarios (match, no match, MRO match, mutual exclusivity error).

### Crossplane (`deploy/helm-charts/asya-crossplane/`)

4. **XRD**: Add `retryableErrors` field to `spec.resiliency` (csv string, same format as `nonRetryableErrors`).

5. **Compositions**: Map `retryableErrors` → `ASYA_RESILIENCY_RETRYABLE_ERRORS` env var on sidecar container.

## FQN format

Both fields use Python fully-qualified exception names matching the runtime's `_fqn()` output:
- Builtins: `ValueError`, `KeyError`
- Non-builtins: `httpx.TimeoutException`, `json.decoder.JSONDecodeError`

The sidecar already matches these against errorType + MRO from the runtime error response.

## Related

- research-compiler-knowledge-base.md open question #1 (resolved)
- [zjt4] cumulative retry time window
