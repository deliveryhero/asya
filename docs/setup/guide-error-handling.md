
# Configuring Error Handling and Retries

How to configure resiliency policies, error-matching rules, and error routing
at the infrastructure level. This guide covers the `spec.resiliency` block in
AsyncActor manifests.

---

## Overview

Asya handles errors at the sidecar level using a policy-based system:

```
error occurs at actor X
  └─ rules: first matching rule by error type / MRO?
       ├─ match → apply matched policy
       └─ no match → apply policies.default (or fail to x-sink)

apply policy:
  └─ attempts < maxAttempts AND wall-clock < maxDuration?
       ├─ yes → retry (back to X's queue with backoff delay)
       └─ no  → thenRoute configured?
                  ├─ yes → route to thenRoute actors
                  └─ no  → x-sink (phase=failed)
```

## Resiliency schema

The full `spec.resiliency` block in an AsyncActor manifest:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: my-actor
spec:
  resiliency:
    timeout:
      actor: 120s              # per-execution deadline (kills runtime)

    policies:
      default:                 # fallback when no rule matches
        maxAttempts: 3
        backoff: exponential   # exponential | constant | linear
        initialDelay: 1s
        maxInterval: 60s
        jitter: true
        maxDuration: 600s      # total wall-clock budget
        # thenRoute omitted → x-sink on exhaustion

      retry-fast:
        maxAttempts: 5
        backoff: exponential
        initialDelay: 500ms

      no-retry:
        maxAttempts: 1
        thenRoute: ["alert-devops"]

    rules:
      - errors: ["ConnectionError", "TimeoutError"]
        policy: retry-fast
      - errors: ["openai.AuthenticationError"]
        policy: no-retry
```

### Policy fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `maxAttempts` | int | 1 | Total attempts (1 = no retry) |
| `backoff` | enum | — | `exponential`, `constant`, `linear` |
| `initialDelay` | duration | — | First retry delay |
| `maxInterval` | duration | — | Cap on backoff delay |
| `jitter` | bool | false | Add random jitter to delays |
| `maxDuration` | duration | — | Total wall-clock budget; exhausted = same as maxAttempts reached |
| `thenRoute` | []string | — | Where to route when exhausted; omit for x-sink |

### Error type matching

`errors` entries support two forms:

- **Short name** (no dot): matches any error where `type.__name__` equals the key.
  `"ConnectionError"` matches `requests.ConnectionError`, `urllib3.ConnectionError`, etc.
- **FQN** (contains dot): matches exact `type.__module__ + "." + type.__name__`.
  `"openai.RateLimitError"` only matches `openai.RateLimitError`.

If the exact class doesn't match, ancestors are checked in MRO order.
`"Exception"` matches all Python exceptions.

### Rules evaluation order

Rules are evaluated top-to-bottom; first match wins. When multiple sources
contribute rules, priority is:

1. **Compiler-generated rules** (from `try/except` in flows) — prepended
2. **Actor inline rules** — defined in the manifest
3. **Flavor-contributed rules** — appended in `spec.flavors` order

`policies.default` is the fallback when no rule matches.

---

## Recipes

### Retry with exponential backoff

```yaml
resiliency:
  policies:
    default:
      maxAttempts: 5
      backoff: exponential
      initialDelay: 2s
      maxInterval: 60s
      jitter: true
```

### Non-retryable errors (fail fast)

Route specific error types directly to x-sink on first failure:

```yaml
resiliency:
  policies:
    default:
      maxAttempts: 3
      backoff: exponential
      initialDelay: 1s
    hard-fail:
      maxAttempts: 1
  rules:
    - errors: ["ValueError", "TypeError"]
      policy: hard-fail
```

### Route exhausted envelopes to a recovery actor

When a policy exhausts, forward the envelope to a recovery actor
instead of x-sink:

```yaml
resiliency:
  policies:
    default:
      maxAttempts: 3
      backoff: constant
      initialDelay: 5s
      thenRoute: ["recovery-actor"]
```

The recovery actor receives the envelope with `status.phase=failed`
and `status.error` containing the error details.

### Cap total retry time

Stop retrying after 10 minutes regardless of attempt count:

```yaml
resiliency:
  policies:
    default:
      maxAttempts: 100
      backoff: exponential
      initialDelay: 1s
      maxInterval: 30s
      maxDuration: 10m
```

### Whitelist mode (retry only specific errors)

Fail fast on everything except explicitly listed types:

```yaml
resiliency:
  policies:
    default:
      maxAttempts: 1          # unmatched errors → fail fast
    retry-transient:
      maxAttempts: 3
      backoff: exponential
      initialDelay: 1s
  rules:
    - errors: ["ConnectionError", "TimeoutError"]
      policy: retry-transient
```

### Reusable resiliency via flavors

Define resiliency rules once as a flavor, apply to many actors:

```yaml
# EnvironmentConfig (flavor)
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: openai-resiliency
  labels:
    asya.sh/flavor: openai-resiliency
data:
  resiliency:
    policies:
      retry-rate-limit:
        maxAttempts: 5
        backoff: exponential
        initialDelay: 10s
        maxDuration: 1800s
      alert-auth:
        thenRoute: ["alert-devops"]
    rules:
      - errors: ["openai.RateLimitError"]
        policy: retry-rate-limit
      - errors: ["openai.AuthenticationError"]
        policy: alert-auth
```

Apply to any actor: `spec.flavors: ["openai-resiliency"]`

---

## How the compiler uses resiliency (try/except in flows)

When a flow author writes `try/except`, the compiler automatically injects
resiliency rules into the manifests of actors inside the `try` body. For
example:

```python
try:
    p = validate(p)
except ValueError:
    p = handle_error(p)
```

The compiler stamps this into `validate`'s manifest:

```yaml
resiliency:
  policies:
    try_except_line_3_0:
      maxAttempts: 1
      thenRoute: ["router-except-line-5-except-2"]
  rules:
    - errors: ["ValueError"]
      policy: try_except_line_3_0
```

These compiler-generated rules **prepend** before any actor-defined rules,
so flow-level `try/except` takes precedence for matched error types.
The actor's own `policies.default` still applies for unmatched errors.

---

## Error flow through the system

```
Actor pod                          Sidecar
┌──────────────┐              ┌─────────────────────────┐
│  Runtime     │   error      │  handleErrorResponse()  │
│  executes    │─────────────►│                         │
│  handler     │              │  1. matchPolicy()       │
│              │              │     rules: first match  │
└──────────────┘              │                         │
                              │  2. applyPolicy()       │
                              │     retry? → re-queue   │
                              │     exhausted?          │
                              │       thenRoute → send  │
                              │       no route → x-sink │
                              └─────────────────────────┘
```

The sidecar sets `status.error` on the envelope with the error's
`type`, `message`, `traceback`, and `mro` before routing. Downstream
actors can read these via `yield "GET", ".status.error"`.

---

## See also

- [Configuring Timeouts](guide-timeouts.md) — per-actor and SLA deadlines
- [Actor Flavors](guide-actor-flavors.md) — reusable resiliency via flavors
- [AsyncActor CRD Reference](../reference/specs/asyncactor-crd.md) — full schema

**Using error handling in flows**: To write `try/except` in the Flow DSL, see
[usage/guide-error-handling.md](../usage/guide-error-handling.md).
