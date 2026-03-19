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

Receives every terminal envelope — both route-exhausted and failure paths.
Runs regardless of `status.phase`; both `succeeded` and `failed` envelopes pass through.

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
| Non-retryable error (`nonRetryableErrors`) | `sendRetryFailure` | x-sink → hooks → x-sump |
| Max retries exhausted | `sendRetryFailure` | x-sink → hooks → x-sump |
| No resiliency configured (legacy) | `sendRetryFailure` | x-sink → hooks → x-sump |

---

## Design rationale

x-sink and x-sump are deliberately split rather than merged into one actor:

- **x-sink** is configurable per deployment (hooks, persistence mount) and must
  handle both success and failure identically — it does not branch on phase.
- **x-sump** is fixed and unconditional — it is the one place in the system
  where you can assert "this message is done, no matter what".

Keeping them separate means hook failures in x-sink (e.g., checkpoint-s3 throws)
do not prevent x-sump from logging and ACKing the envelope. The sidecar routes
x-sink's output to x-sump via the normal route mechanism, so x-sink errors
would themselves be caught and eventually reach x-sump via `sendRetryFailure`.

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
