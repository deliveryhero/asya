---
title: "design+impl: replace nonRetryableErrors with errorRoutes in resiliency config"
status: rejected
priority: 2
parent: 00001
---

superseeded by [7179]


## Background

`spec.resiliency.nonRetryableErrors` is a blacklist: errors in this list skip
retry and go to x-sump (via `sendRetryFailure`). Once `[nqf5]` is fixed,
they will correctly go to x-sink instead.

The field name and shape are limiting:
- Name `nonRetryableErrors` says what NOT to do, not what happens
- It only supports one destination (x-sink/x-sump termination path)
- Users cannot route specific error types to custom recovery actors

## Proposed design

Replace `nonRetryableErrors` with `errorRoutes` — a dict mapping error types
to actor lists (consistent with `route.next` being a list):

```yaml
spec:
  resiliency:
    actorTimeout: 120s
    retry:                          # errors that return to self (same actor queue)
      maxAttempts: 3
      backoff: exponential
      initialInterval: 1s
      maxInterval: 60s
      jitter: true
    errorRoutes:                    # errors that skip self entirely
      ValidationError: ["notify-rejection"]
      openai.AuthenticationError: ["x-sink"]
```

`nonRetryableErrors: [X]` is equivalent to `errorRoutes: { X: ["x-sink"] }`.

## Decision log

- `retry:` and `errorRoutes:` are siblings, not nested — `retry` is the
  default path for unmatched errors; `errorRoutes` entries bypass retry
- Values are `[]string` (lists) — consistent with `route.next` in envelopes
- No `"*"` wildcard — use `retry.maxAttempts: 1` to disable retry globally
- `nonRetryableErrors` removed with no backward compatibility
- FQN matching for error type keys:
  - Key has no `.` → match by `type.__name__` (short name)
  - Key has `.` → match exact `module.ClassName` (FQN)
  - Requires runtime to send FQN in `Details.Type` and `Details.MRO`
    (change from `type.__name__` to `f"{type.__module__}.{type.__name__}"`)
- NOT related to `[w76v]` retryableErrors whitelist — that is a separate
  orthogonal feature (whitelist of which errors should retry vs. this blacklist
  of where specific errors should be routed)

## Decision tree (post nqf5 + this ticket)

```
error occurs at actor X
  └─ errorRoutes key matches error type (by MRO)?
       ├─ yes → msg.Route.Next = errorRoutes[match]; send normally
       └─ no  → retry.maxAttempts remaining?
                  ├─ yes → retryMessage (back to X's queue with delay)
                  └─ no  → sendRetryFailure → x-sink (phase=failed) → x-sump
```

## Acceptance criteria

- [ ] `nonRetryableErrors` removed from XRD schema and sidecar config
- [ ] `errorRoutes: map[string][]string` added to `ResiliencyConfig`
- [ ] Sidecar: MRO lookup checks `errorRoutes` before retry logic
- [ ] Sidecar: on match, sets `msg.Route.Next` and sends normally (not via sendRetryFailure)
- [ ] Runtime sends FQN (`module.ClassName`) in `Details.Type` and `Details.MRO`
- [ ] Sidecar matching: no-dot key → short name match, dot key → exact FQN match
- [ ] XRD/Crossplane chart updated
- [ ] `docs/internal/crew-termination.md` updated to reflect new schema

## Dependencies

- `[nqf5]` must land first (fixes sendRetryFailure to route to x-sink)

## Related

- `[w76v]` retryableErrors whitelist (complementary, not superseded)
- `[6e74]` add resiliency EnvironmentConfig flavor examples
