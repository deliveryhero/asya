# Error Handling

Error routing specification for the Asya actor mesh. Covers policy exhaustion, DLQ handling, and the x-sink/x-sump termination chain.

## Termination Chain

When an actor's processing fails permanently (policy exhausted, no `onExhausted` route), the sidecar routes the envelope through a two-layer termination chain:

1. **x-sink** — receives the failed envelope, persists it, and marks the task as `failed`.
2. **x-sump** — receives the envelope from x-sink (DLQ handling); logs, alerts, or discards.

x-sump is never reached directly from the sidecar. All failure paths go through x-sink first. This invariant is enforced by `sendRetryFailure` in the sidecar.

## Policy Exhaustion Behavior

| Policy state | `onExhausted` | Outcome |
|---|---|---|
| Attempts or maxDuration exhausted | empty | `sendRetryFailure` -> x-sink -> x-sump |
| Attempts or maxDuration exhausted | `["recovery-actor"]` | `routeOnExhausted` -> recovery-actor queue |
| No resiliency config | -- | `sendRetryFailure` immediately -> x-sink -> x-sump |
| No matching rule AND no `default` policy | -- | `sendRetryFailure` immediately -> x-sink -> x-sump |

## Envelope Status at Termination

When routed to x-sink via `sendRetryFailure`:

- `status.phase = failed`
- `status.reason = PolicyExhausted` (or `RuntimeError` for infrastructure failures)
- `status.error` contains the last exception type, MRO, message, and traceback

When routed to a custom `onExhausted` actor:

- `status.phase = failed`
- `status.reason = PolicyRouted`
- `route.next = onExhausted` (set by sidecar before dispatch)

## Error Categories

Errors are classified by the sidecar for policy matching:

| Error source | Classification | Default behavior |
|---|---|---|
| Runtime returns error response | Runtime error (matched against policy rules) | Retry per matching policy |
| Runtime connection failure | Transport error | Retry with backoff |
| Message parse failure | Parse error | Route to x-sink -> x-sump (no retry) |
| Validation error | Validation error | Route to x-sink -> x-sump (no retry) |

See [guide-retries.md](../../setup/guide-retries.md) for configuring retry policies.
