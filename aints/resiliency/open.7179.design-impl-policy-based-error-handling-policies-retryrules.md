---
title: "design+impl: policy-based error handling (policies + retryRules replaces nonRetryableErrors)"
priority: 1 # high
---

## Context

Current error handling in the sidecar is limited:
- `retry:` block — uniform retry for all errors (backoff, maxAttempts)
- `nonRetryableErrors: [X, Y]` — blacklist: these errors skip retry and route
  to x-sump directly (also bugs: bypasses x-sink, see `[nqf5]`)

This does not support: routing specific errors to custom recovery actors,
per-error-type retry config, or reusable named policies across actors.

## Proposed design

### Schema

```yaml
spec:
  resiliency:
    actorTimeout: 120s          # unchanged

    policies:
      default:                  # fallback when no retryRule matches
        maxAttempts: 3
        backoff: exponential    # exponential | constant | linear
        initialDelay: 1s
        maxInterval: 60s
        jitter: true
        # thenRoute omitted → x-sink (always the terminal fallback)

      retryFast:
        maxAttempts: 5
        backoff: exponential
        initialDelay: 500ms

      retryPatiently:
        maxAttempts: 3
        backoff: exponential
        initialDelay: 10s

      logAndDiscard:
        maxAttempts: 1          # default, can omit
        thenRoute: ["log-and-discard"]

      alertDevops:
        thenRoute: ["alert-devops"]   # maxAttempts: 1 implicit

    retryRules:
      - errors: ["ConnectionError", "NetworkError"]
        policy: retryFast
      - errors: ["openai.RateLimitError", "anthropic.OverloadedError"]
        policy: retryPatiently
      - errors: ["openai.InvalidRequestError"]
        policy: logAndDiscard
      - errors: ["openai.AuthenticationError"]
        policy: alertDevops
```

### Policy fields

| Field | Type | Default | Description |
|---|---|---|---|
| `maxAttempts` | int | 1 | Total attempts (1 = no retry) |
| `backoff` | enum | — | `exponential`, `constant`, `linear` |
| `initialDelay` | duration | — | First retry delay |
| `maxInterval` | duration | — | Cap on backoff delay |
| `jitter` | bool | false | Add ±50% jitter |
| `thenRoute` | []string | ["x-sink"] | Where to route when attempts exhausted |

All fields are optional. A policy with only `thenRoute` set (and `maxAttempts: 1`
implicit) is a pure routing policy — no retry, immediately route on first failure.

### Decision tree

```
error occurs at actor X
  └─ retryRules: first matching rule by MRO order?
       ├─ match found → apply matched policy
       └─ no match → apply policies.default (or built-in default if absent)

apply policy:
  └─ attempts < maxAttempts?
       ├─ yes → retryMessage (back to X's queue with backoff delay)
       └─ no (exhausted) → thenRoute configured?
                  ├─ yes → set msg.Route.Next = thenRoute; send normally
                  └─ no  → sendRetryFailure → x-sink (phase=failed) → x-sump
```

Note: `retryRules` first-match semantics. Rule order in spec = evaluation order.
When multiple flavors contribute rules (list append), flavor order determines priority.

### Error type matching in retryRules

Keys in `errors: [...]` support two forms:
- **Short name** (no `.`): matches any error where `type.__name__ == key`
  e.g., `"ConnectionError"` matches `requests.ConnectionError`, `urllib3.ConnectionError`
- **FQN** (contains `.`): matches exact `f"{type.__module__}.{type.__name__}"`
  e.g., `"openai.RateLimitError"` matches only `openai.RateLimitError`

MRO traversal: if the exact class doesn't match, ancestors are checked in MRO order.
So `"Exception"` would match all Python exceptions as a catch-all.

### Backward compatibility

`nonRetryableErrors: [X, Y]` — **removed with no migration path** (internal config).
Equivalent: add `policies.nonRetryable: { thenRoute: ["x-sink"] }` and
`retryRules: [{ errors: [X, Y], policy: nonRetryable }]`.

`retry:` shorthand — **removed with no migration path**.
Equivalent: define `policies.default` with the same fields.

### Flavor composition

`resiliency` is a map field in the flavor merge system — merges recursively.
`policies` map: each named policy is a distinct map key — two flavors defining
the same policy name conflict (error with flavor names + key path).
`retryRules` list: appends across flavors in `spec.flavors` order. Actor inline
rules append last (actor-wins). First matching rule in the combined list wins
at runtime.

Reusable platform flavor example:
```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: openai-resiliency
  labels:
    asya.sh/flavor: openai-resiliency
data:
  resiliency:
    policies:
      retryFast:
        maxAttempts: 5
        backoff: exponential
        initialDelay: 500ms
      alertDevops:
        thenRoute: ["alert-devops"]
    retryRules:
      - errors: ["openai.RateLimitError"]
        policy: retryFast
      - errors: ["openai.AuthenticationError"]
        policy: alertDevops
```

Actor usage: `spec.flavors: ["openai-resiliency"]`

## Implementation plan

### 1. Runtime: send FQN in error details

`src/asya-runtime/asya_runtime.py` — change error serialization:
```python
# before
"type": type(e).__name__
"mro":  [c.__name__ for c in type(e).__mro__]

# after
"type": f"{type(e).__module__}.{type(e).__name__}"
"mro":  [f"{c.__module__}.{c.__name__}" for c in type(e).__mro__]
```

### 2. Sidecar config: new ResiliencyConfig shape

`src/asya-sidecar/internal/config/config.go`:
- Remove `NonRetryableErrors []string`
- Remove `Retry RetryConfig` (top-level)
- Add `Policies map[string]PolicyConfig`
- Add `RetryRules []RetryRule`
- Add `PolicyConfig` struct: `MaxAttempts`, `Backoff`, `InitialDelay`,
  `MaxInterval`, `Jitter`, `ThenRoute []string`
- Add `RetryRule` struct: `Errors []string`, `Policy string`

### 3. Sidecar: error matching and policy dispatch

`src/asya-sidecar/internal/router/router.go`:
- `matchPolicy(errorType, mro, rules)` — iterates rules, returns first matching policy
  - For each rule: checks if any `errors` key matches errorType or any MRO ancestor
  - Short-name match: `type.__name__` suffix; FQN match: exact string
- `applyPolicy(ctx, msg, policy)` — dispatches based on policy:
  - `maxAttempts > 1` and attempts remaining: `retryMessage` (existing)
  - Exhausted + `thenRoute` set: `msg.Route.Next = policy.ThenRoute; send to SinkQueue`
  - Exhausted + no `thenRoute`: `sendRetryFailure` → SinkQueue (after `[nqf5]` fix)
- Remove `isNonRetryableError`
- Remove `handleErrorResponse` retry/non-retryable split — replace with `matchPolicy` + `applyPolicy`

### 4. XRD + Crossplane chart

`deploy/helm-charts/asya-crossplane/`:
- Remove `nonRetryableErrors` from XRD spec
- Remove `retry` top-level field
- Add `resiliency.policies` (map) and `resiliency.retryRules` (list) to XRD
- Update composition to render `ASYA_RESILIENCY_*` env vars from new schema
- Update `docs/internal/actor-flavors.md` with retryRules ordering note

### 5. actor-flavors.md update

Add note: `retryRules` list order across flavors determines rule priority (first match
wins). Flavor order in `spec.flavors` = rule evaluation order.

## Acceptance criteria

- [ ] Runtime sends FQN in `Details.Type` and `Details.MRO`
- [ ] Sidecar: `matchPolicy` correctly resolves FQN and short-name matches via MRO
- [ ] Sidecar: `applyPolicy` dispatches retry / thenRoute / x-sink correctly
- [ ] `nonRetryableErrors` and top-level `retry:` removed from XRD and sidecar
- [ ] `policies.default` is the fallback when no rule matches
- [ ] `thenRoute` sends to x-sink path (not directly to x-sump)
- [ ] Flavor composition: `policies` map merge, `retryRules` list append work correctly
- [ ] Unit tests: `matchPolicy` covers FQN, short-name, MRO traversal, no-match→default
- [ ] Unit tests: `applyPolicy` covers retry, exhausted+thenRoute, exhausted+no-thenRoute
- [ ] Integration test: end-to-end error routing with a custom thenRoute actor
- [ ] `docs/internal/crew-termination.md` updated to reflect new schema
- [ ] `docs/internal/actor-flavors.md` updated with retryRules ordering note

## Dependencies

- `[nqf5]` must land first: fixes `sendRetryFailure` to route through x-sink

## Supersedes

- `[tj91]` in debt (narrower design, subsumed by this)
- `[w76v]` `retryableErrors` whitelist — covered by `retryRules` + `policies.default` pattern:
  to whitelist only specific errors, define `policies.default: { thenRoute: ["x-sink"] }`
  and explicit retry rules for allowed error types

## Future extensions (out of scope)

- Per-policy `actorTimeout` override
- Namespace-scoped flavor ConfigMaps (`[jgwn]`)
