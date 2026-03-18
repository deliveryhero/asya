---
title: "fix(crew): x-sump must always be reached via x-sink (enforce two-layer termination)"
priority: 2 # medium
---

## Problem

`sendRetryFailure` in `src/asya-sidecar/internal/router/router.go:432` routes
failed envelopes **directly to x-sump**, bypassing x-sink entirely. This means
x-sink's post-hooks (`ASYA_SINK_HOOKS`: checkpoint-s3, notify-slack, etc.) and
inline checkpointing never run for:

- Non-retryable errors (`nonRetryableErrors` match)
- Max-retries-exhausted failures

Only route-exhausted (success or None return) envelopes go through x-sink today.

## Expected behavior

x-sump is the **second** termination layer — it should never receive an envelope
that has not passed through x-sink first. The intended architecture (documented in
`sink.py` docstring) is:

```
Any terminal envelope (success or failure)
    → x-sink  (checkpoint + hooks)
    → x-sump  (log + ACK, terminal)
```

## Fix

Change `sendRetryFailure` to send to `r.sinkQueue` instead of `r.sumpQueue`.
x-sink already handles `phase=failed` correctly — it inspects phase only for
fan-out filtering, not for routing.

This also makes `nonRetryableErrors: [X]` semantically equivalent to the
proposed `errorRoutes: { X: x-sink }` generalization — both mean "permanent
failure through the full termination path".

## Acceptance criteria

- [ ] `sendRetryFailure` routes to x-sink (`SinkQueue`), not x-sump (`SumpQueue`)
- [ ] x-sink's hooks fire for non-retryable and max-retries-exhausted failures
- [ ] Unit tests updated in `router_retry_test.go` to assert routing to x-sink
- [ ] `docs/internal/crew-termination.md` added

## Related

- `[1fac]` Sidecar: ASYA_ACTOR_ROLE unification
- `[w76v]` Sidecar: add retryableErrors whitelist
