---
title: "fix(crew): x-sump must always be reached via x-sink (enforce two-layer termination)"
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/debt/nqf5.fix-crew-x-sump-must-always-be-reached
  - branch:debt/nqf5.fix-crew-x-sump-must-always-be-reached
  - pr:330
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

## Acceptance criteria

- [ ] `sendRetryFailure` routes to `r.sinkQueue`, not `r.sumpQueue`
- [ ] x-sink's hooks fire for all failure modes (non-retryable, max-retries-exhausted)
- [ ] Unit tests in `router_retry_test.go` updated to assert routing to x-sink
- [ ] `docs/internal/crew-termination.md` added

## Related

- `[1fac]` Sidecar: ASYA_ACTOR_ROLE unification
- `[w76v]` Sidecar: add retryableErrors whitelist
- see also: design aint for nonRetryableErrors → errorRoutes redesign


---

## Reference:

Sample contents of `docs/internal/crew-termination.md`:

<details>

# Crew Termination: x-sink and x-sump

## Overview

All terminal envelopes — whether succeeded or failed — are processed by a
two-layer termination pipeline built from two crew actors:

```
Any terminal envelope
    → x-sink  [role=sink]     checkpoint + hooks
    → x-sump  [role=sump]     log + ACK (terminal)
```

**Invariant: x-sump must never receive an envelope that has not passed through
x-sink first.** x-sump is the second layer only. It has no checkpointing or
hook logic of its own beyond logging.

---

## x-sink

**Source**: `src/asya-crew/asya_crew/sink.py`

Receives every envelope whose route is exhausted (sidecar sets `route.next = []`
or handler returns `None`). Runs regardless of `status.phase` — both `succeeded`
and `failed` envelopes pass through.

Responsibilities:
- Inline checkpoint via state proxy (if `ASYA_PERSISTENCE_MOUNT` is set)
- Route to configurable post-hooks (`ASYA_SINK_HOOKS`: comma-separated actor names)
- Pass through to x-sump when hooks are done (or immediately if none configured)

Special cases that **skip hooks** (silently pass to x-sump):
- Fan-in partials (`x-asya-fan-in` header present) — accumulating slices, not final results
- Fan-out children with a `parent_id` — unless `ASYA_SINK_FANOUT_HOOKS=true`

## x-sump

**Source**: `src/asya-crew/asya_crew/sump.py`

Terminal actor. Receives every envelope after x-sink and all hooks have run.

Responsibilities:
- Log at `ERROR` level if `status.phase == "failed"`
- Log at `DEBUG` level if `status.phase == "succeeded"`
- Optional final checkpoint via state proxy
- Yield payload and ACK — no further routing

x-sump has no configurable hooks. It is the absolute end of every message path.

---

## Routing paths

| Situation | Sidecar action | Path |
|---|---|---|
| Route exhausted / handler returns `None` | Send to `SinkQueue` | x-sink → hooks → x-sump |
| Handler returns payload, route has actors | Send to next actor | normal mesh routing |
| `_on_error` header set (flow try-except) | Send to named handler | custom actor (bypasses both) |
| Non-retryable error (`nonRetryableErrors`) | `sendRetryFailure` | ⚠️ x-sump directly (bug, see below) |
| Max retries exhausted | `sendRetryFailure` | ⚠️ x-sump directly (bug, see below) |

---

## Known bug: sendRetryFailure bypasses x-sink

**Tracked in**: `[nqf5]` fix(crew): x-sump must always be reached via x-sink

`sendRetryFailure` in `src/asya-sidecar/internal/router/router.go:496` sends
directly to `r.sumpQueue` (x-sump) instead of `r.sinkQueue` (x-sink). This
means x-sink's post-hooks and checkpointing **do not run** for:

- Non-retryable errors (`nonRetryableErrors` match)
- Max-retries-exhausted failures

**Impact**: `notify-slack` and `checkpoint-s3` hooks configured in
`ASYA_SINK_HOOKS` silently do not fire for these failure modes. Failed
envelopes are not checkpointed at x-sink.

**Fix**: Change `sendRetryFailure` to send to `r.sinkQueue`. x-sink already
handles `phase=failed` — it inspects phase only for fan-out filtering, not
for its hook routing logic.

---

## Design rationale

x-sink and x-sump are deliberately split rather than merged into one actor:

- **x-sink** is configurable per deployment (hooks, persistence mount) and must
  handle both success and failure identically — it does not branch on phase.
- **x-sump** is fixed and unconditional — it is the one place in the system
  where you can add an assertion "this message is done, no matter what".

Keeping them separate means hook failures in x-sink (e.g., checkpoint-s3 throws)
do not prevent x-sump from logging and ACKing the envelope. The sidecar routes
x-sink's output to x-sump via the normal route mechanism, so x-sink errors
would themselves be caught and eventually reach x-sump via `sendRetryFailure`
(modulo the bug above).

---

## Error phase vs. success phase

x-sink does **not** fork on `status.phase`. Both `succeeded` and `failed`
envelopes get the same hooks. If you need phase-specific behavior (e.g.,
only checkpoint failures), implement it inside a custom hook actor that reads
`status.phase` via the ABI:

```python
status = yield "GET", ".status"
if status.get("phase") != "failed":
    return  # skip for succeeded
# ... custom failure handling
yield payload
```

---

## Related docs

- [crew-checkpointer.md](crew-checkpointer.md) — checkpointer implementation
  called from x-sink and x-sump

</details>
