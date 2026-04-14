---
title: Policy-based error handling (timeout + policies + rules replaces nonRetryableErrors)
status: merged
priority: 1
assignee: Artem Yushkovskiy
dependencies:
  - p5pyv
tags:
  - worktree:.worktrees/resiliency/7179.policy-based-error-handling-policies-retryrules
  - branch:resiliency/7179.policy-based-error-handling-policies-retryrules
  - pr:334
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
    timeout:
      actor: 120s               # per-execution deadline; kills runtime on breach (enforced by sidecar)

    policies:
      default:                  # fallback when no rule matches
        maxAttempts: 3          # xrd must validate min value 1, and -1 would mean infinity
        backoff: exponential    # exponential | constant | linear
        initialDelay: 1s
        maxInterval: 60s
        jitter: true
        maxDuration: 600s           # total wall-clock budget across all attempts (optional)
        # thenRoute omitted → x-sink (always the terminal fallback)

      retryFast:
        maxAttempts: 5
        backoff: exponential
        initialDelay: 500ms
        maxDuration: 60s            # give up fast even if attempts remain

      retryPatiently:
        maxAttempts: 3
        backoff: exponential
        initialDelay: 10s
        maxDuration: 1800s          # 30 min budget for rate-limit backoff

      logAndDiscard:
        maxAttempts: 1          # default, can omit
        thenRoute: ["log-and-discard"]

      alertDevops:
        thenRoute: ["alert-devops"]   # maxAttempts: 1 implicit

    rules:
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
| `maxDuration` | duration | — | Total wall-clock budget across all attempts; exhausted = same effect as `maxAttempts` reached |
| `thenRoute` | []string | ["x-sink"] | Where to route when `maxAttempts` or `maxDuration` exceeded |

All fields are optional. A policy with only `thenRoute` set (and `maxAttempts: 1`
implicit) is a pure routing policy — no retry, immediately route on first failure.

`resiliency.timeout.actor` vs `policies.*.maxDuration` are orthogonal concerns:
- `timeout.actor` is enforced per-execution by the sidecar (kills the runtime call); it applies to every attempt regardless of policy
- `policies.*.maxDuration` is a stopping condition evaluated before each retry — stop retrying when wall-clock since first attempt exceeds the budget

This mirrors tenacity's `stop` combinator: `stop_after_attempt(N) | stop_after_delay(T)`.
`maxAttempts` and `maxDuration` are that same pair — both are retry stopping conditions,
and whichever triggers first wins. `resiliency.timeout.actor` is the execution watchdog,
orthogonal to retry logic.

### Decision tree

```
error occurs at actor X
  └─ rules: first matching rule by MRO order?
       ├─ match found → apply matched policy
       └─ no match → apply policies.default (or built-in default if absent)

apply policy:
  └─ attempts < maxAttempts AND wall-clock since first attempt < timeout?
       ├─ yes → retryMessage (back to X's queue with backoff delay)
       └─ no (attempts exhausted OR timeout exceeded) → thenRoute configured?
                  ├─ yes → set msg.Route.Next = thenRoute; send normally
                  └─ no  → sendRetryFailure → x-sink (phase=failed) → x-sump
```

Note: `rules` first-match semantics. Rule order in spec = evaluation order.
When multiple flavors contribute rules (list append), flavor order determines priority.

### Error type matching in rules

Keys in `errors: [...]` support two forms:
- **Short name** (no `.`): matches any error where `type.__name__ == key`
  e.g., `"ConnectionError"` matches `requests.ConnectionError`, `urllib3.ConnectionError`
- **FQN** (contains `.`): matches exact `f"{type.__module__}.{type.__name__}"`
  e.g., `"openai.RateLimitError"` matches only `openai.RateLimitError`

MRO traversal: if the exact class doesn't match, ancestors are checked in MRO order.
So `"Exception"` would match all Python exceptions as a catch-all.

### rules evaluation order

**First matching rule wins.** The `rules` list is evaluated top-to-bottom;
the first rule whose `errors` list matches the error (via exact FQN or MRO
traversal) is applied. Rules below the first match are never evaluated for that error.

Rule priority in the combined list (highest → lowest):
1. **Compiler-generated rules** (e.g., from `try/except` flow compilation) — prepended before actor rules
2. **Actor inline `rules`**
3. **Flavor-contributed rules** — appended in `spec.flavors` order

`policies.default` is the fallback when no rule in the list matches at all.

This ordering means flow-level `try/except` semantics always take precedence over
actor-level retry config for the specific error types they handle. An actor's
`policies.default` (e.g., `maxAttempts: 5`) still applies for error types not
caught by any `try/except` block.

### Backward compatibility

`nonRetryableErrors: [X, Y]` — **removed with no migration path** (internal config).
Equivalent: add `policies.nonRetryable: { thenRoute: ["x-sink"] }` and
`rules: [{ errors: [X, Y], policy: nonRetryable }]`.

`retry:` shorthand — **removed with no migration path**.
Equivalent: define `policies.default` with the same fields.

### Flavor composition

`resiliency` is a map field in the flavor merge system — merges recursively.
`policies` map: each named policy is a distinct map key — two flavors defining
the same policy name conflict (error with flavor names + key path).
`rules` list: appends across flavors in `spec.flavors` order. Actor inline
rules prepend (actor-wins). See §rules evaluation order for full priority
rules and matching semantics.

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
    rules:
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
- Add `Timeout TimeoutConfig` struct: `Actor time.Duration`
- Add `Policies map[string]PolicyConfig`
- Add `Rules []RetryRule`
- Add `PolicyConfig` struct: `MaxAttempts`, `Backoff`, `InitialDelay`,
  `MaxInterval`, `Jitter`, `MaxDuration time.Duration`, `thenRoute []string`
- Add `RetryRule` struct: `Errors []string`, `Policy string`

### 3. Sidecar: error matching and policy dispatch

`src/asya-sidecar/internal/router/router.go`:
- `matchPolicy(errorType, mro, rules)` — iterates rules, returns first matching policy
  - For each rule: checks if any `errors` key matches errorType or any MRO ancestor
  - Short-name match: `type.__name__` suffix; FQN match: exact string
- `applyPolicy(ctx, msg, policy)` — dispatches based on policy:
  - attempts remaining AND within `policy.Timeout` wall-clock budget: `retryMessage` (existing)
  - Exhausted (attempts OR timeout) + `thenRoute` set: `msg.Route.Next = policy.thenRoute; send to SinkQueue`
  - Exhausted + no `thenRoute`: `sendRetryFailure` → SinkQueue (after `[nqf5]` fix)
  - Wall-clock tracking: first-attempt timestamp stored in `msg.Headers["x-asya-first-attempt"]`
- Remove `isNonRetryableError`
- Remove `handleErrorResponse` retry/non-retryable split — replace with `matchPolicy` + `applyPolicy`

### 4. XRD + Crossplane chart

`deploy/helm-charts/asya-crossplane/`:
- Remove `nonRetryableErrors` from XRD spec
- Remove `retry` top-level field
- Add `resiliency.policies` (map) and `resiliency.rules` (list) to XRD (with basic syntax validators)
- Update composition to render `ASYA_RESILIENCY_*` env vars from new schema
- Update `docs/internal/actor-flavors.md` with rules ordering note

### 5. actor-flavors.md update

Add note: `rules` list order across flavors determines rule priority (first match
wins). Flavor order in `spec.flavors` = rule evaluation order.

## Acceptance criteria

- [ ] Runtime sends FQN in `Details.Type` and `Details.MRO`
- [ ] Sidecar: `matchPolicy` correctly resolves FQN and short-name matches via MRO
- [ ] Sidecar: `applyPolicy` dispatches retry / thenRoute / x-sink correctly
- [ ] `nonRetryableErrors` and top-level `retry:` removed from XRD and sidecar
- [ ] `policies.default` is the fallback when no rule matches
- [ ] `thenRoute` sends to x-sink path (not directly to x-sump)
- [ ] Flavor composition: `policies` map merge, `rules` list append work correctly
- [ ] Unit tests: `matchPolicy` covers FQN, short-name, MRO traversal, no-match→default
- [ ] Unit tests: `applyPolicy` covers retry, exhausted+thenRoute, exhausted+no-thenRoute
- [ ] Integration test: end-to-end error routing with a custom thenRoute actor
- [ ] `docs/internal/crew-termination.md` updated to reflect new schema
- [ ] `docs/internal/actor-flavors.md` updated with rules ordering note

## Dependencies

- `[nqf5]` must land first: fixes `sendRetryFailure` to route through x-sink

## Usage patterns

### Whitelist mode (replaces `[w76v]` retryableErrors)

To retry only specific error types and fail fast on everything else, set
`policies.default` to `maxAttempts: 1` (no retry) and add explicit rules for
the errors you want to retry:

```yaml
resiliency:
  policies:
    default:
      maxAttempts: 1            # all unmatched errors → fail fast → x-sink
    standard:
      maxAttempts: 3
      backoff: exponential
      initialDelay: 1s
  rules:
    - errors: ["ConnectionError", "TimeoutError"]
      policy: standard          # only these two get retry
    # everything else hits default → x-sink immediately
```

This is equivalent to tenacity's `retry_if_exception_type`:

```python
# tenacity equivalent (in-process, single function)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

@retry(
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=60),
)
def call_api(payload):
    ...
```

The `policies` + `rules` model is the mesh-native equivalent: the retry
predicate (`retry_if_exception_type`) becomes `rules.errors`, and the retry
strategy (`stop_after_attempt` + `wait_exponential`) becomes the policy fields.
Key difference: tenacity operates inside a single process; Asya's retry sends the
envelope back through the queue (the sidecar re-delivers to the runtime), so retry
delay is enforced by `SendWithDelay` at the transport level, not by sleeping.

### Blacklist mode (replaces `nonRetryableErrors`)

Retry everything by default, but immediately route specific errors away:

```yaml
resiliency:
  policies:
    default:
      maxAttempts: 3
      backoff: exponential
    noRetry:
      thenRoute: ["x-sink"]
  rules:
    - errors: ["openai.AuthenticationError", "openai.InvalidRequestError"]
      policy: noRetry
    # everything else retries via default
```

### Mixed mode

Combine both: retry some errors differently, route others, fail fast on the rest:

```yaml
resiliency:
  policies:
    default:
      maxAttempts: 1            # fail fast unless explicitly matched
    retryFast:
      maxAttempts: 5
      backoff: exponential
      initialDelay: 500ms
    alertAndDiscard:
      thenRoute: ["alert-devops"]
  rules:
    - errors: ["ConnectionError", "TimeoutError"]
      policy: retryFast
    - errors: ["openai.AuthenticationError"]
      policy: alertAndDiscard
    # everything else → default → x-sink
```

## Supersedes

- `[tj91]` in debt (narrower design, subsumed by this)
- `[w76v]` `retryableErrors` whitelist — fully expressed via whitelist mode above

## Future extensions (out of scope)

### Circuit breakers (`[xcd1]`)

Once this policy system lands, circuit breakers integrate as an optional
sub-field on a policy — no new top-level field needed. See `[xcd1]` for full
design. The `thenRoute` of the policy handles fast-failed envelopes while the
circuit is open.

### Namespace-scoped flavor ConfigMaps (`[jgwn]`)
