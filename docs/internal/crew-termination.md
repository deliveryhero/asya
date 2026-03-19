# Crew Termination Flow

When an actor's processing fails permanently (policy exhausted, no `thenRoute`), the sidecar
routes the envelope through a two-layer termination chain:

1. **x-sink** — receives the failed envelope, persists it, and marks the task as `failed`.
2. **x-sump** — receives the envelope from x-sink (DLQ handling); logs, alerts, or discards.

x-sump is never reached directly from the sidecar. All failure paths go through x-sink first.
This invariant is enforced by `sendRetryFailure`.

## Policy exhaustion behavior

| Policy state | `thenRoute` | Outcome |
|---|---|---|
| Attempts or maxDuration exhausted | empty | `sendRetryFailure` → x-sink → x-sump |
| Attempts or maxDuration exhausted | `["recovery-actor"]` | `routeToThenRoute` → recovery-actor queue |
| No resiliency config | — | `sendRetryFailure` immediately → x-sink → x-sump |
| No matching rule AND no `default` policy | — | `sendRetryFailure` immediately → x-sink → x-sump |

## Envelope status at termination

When routed to x-sink via `sendRetryFailure`:
- `status.phase = failed`
- `status.reason = PolicyExhausted` (or `RuntimeError` for infrastructure failures)
- `status.error` contains the last exception type, MRO, message, and traceback

When routed to a custom `thenRoute` actor:
- `status.phase = failed`
- `status.reason = PolicyRouted`
- `route.next = thenRoute` (set by sidecar before dispatch)
