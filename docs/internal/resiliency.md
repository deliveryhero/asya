# Resiliency: Internal Architecture

Technical reference for the policy-based retry and error-routing system in
`asya-sidecar`. See `docs/features/resiliency.md` for the user-facing guide.

## Configuration Loading

Two env vars are parsed at startup by `internal/config`:

- `ASYA_RESILIENCY_POLICIES` — JSON object decoded into `map[string]PolicyConfig`
- `ASYA_RESILIENCY_RULES` — JSON array decoded into `[]RetryRule`

Both live on `ResiliencyConfig`, which is `nil` when neither var is set (no
resiliency configured; single attempt, legacy behaviour).

`PolicyConfig` fields:

```go
type PolicyConfig struct {
    MaxAttempts  int          `json:"maxAttempts"`
    Backoff      RetryPolicy  `json:"backoff"`
    InitialDelay JSONDuration `json:"initialDelay"`
    MaxInterval  JSONDuration `json:"maxInterval"`
    MaxDuration  JSONDuration `json:"maxDuration"`
    Jitter       bool         `json:"jitter"`
    OnExhausted  []string     `json:"onExhausted"`
}
```

`JSONDuration` parses Go duration strings (`"1s"`, `"500ms"`, `"5m"`) via
`time.ParseDuration`.

## Error Handling Flow

```
handleErrorResponse
  ├── _on_error header? → routeToFlowErrorHandler (flow error path)
  ├── Record metrics (error count, processing duration)
  ├── Resiliency nil? → sendRetryFailure(RuntimeError)
  ├── matchPolicy(errorType, mro)
  │     nil? → sendRetryFailure(RuntimeError)
  └── applyPolicy(policy)
        ├── attempts not exhausted AND duration not exceeded
        │     → retryMessage (SendWithDelay)
        │         SendWithDelay fails → sendRetryFailure(RuntimeError)
        ├── exhausted + OnExhausted configured
        │     → routeOnExhausted
        └── exhausted + no OnExhausted
              → sendRetryFailure(PolicyExhausted)
```

## Policy Matching (`matchPolicy`)

Builds a candidate list: `[errorType] + mro`. Iterates rules in order; for each
rule, checks every pattern against every candidate:

- **FQN pattern** (contains `.`): exact equality — `candidate == pattern`
- **Short name** (no `.`): matches `candidate[lastDot+1:]`

First matching rule wins; its `policy` key is looked up in `Policies`. If no
rule matches, `Policies["default"]` is returned. If no default exists, returns
`nil` → `sendRetryFailure(RuntimeError)`.

## Policy Application (`applyPolicy`)

1. `maxAttempts = max(policy.MaxAttempts, 1)` — zero is treated as 1
2. `msg.Status.MaxAttempts = maxAttempts` — propagated to the final x-sink envelope
3. `attemptsExhausted = msg.Status.Attempt >= maxAttempts`
4. `durationExhausted = createdAt + maxDuration < now` (only when `MaxDuration > 0`)
5. If neither exhausted: `retryMessage` → `SendWithDelay(delay)`
6. If exhausted and `OnExhausted` non-empty: `routeOnExhausted`
7. If exhausted and `OnExhausted` empty: `sendRetryFailure(PolicyExhausted)`

## Delay Computation (`computeRetryDelayForPolicy`)

Delay for attempt N (1-indexed current attempt):

| Backoff | Formula |
|---|---|
| `constant` | `initialDelay` |
| `linear` | `N * initialDelay` |
| `exponential` | `initialDelay * 2^(N-1)` |

All capped at `maxInterval` (when set). Jitter adds `rand * 0.1 * delay`.
Minimum returned delay is 0.

## Envelope Status Lifecycle

`ensureAndUpdateStatus` is called at the start of every `ProcessMessage` to
initialise or advance `msg.Status`:

| Condition | Action |
|---|---|
| `status == nil` | Create with `phase=pending`, `attempt=1`, `created_at=now` |
| `status.actor != currentActor` | Reset `attempt=1`, `created_at=now`, `error=nil` (actor transition) |
| Same actor, retry | Increment `attempt`, update `updated_at` |

The `created_at` reset on actor transition ensures `maxDuration` is scoped to
the current actor, not the entire pipeline lifetime.

On retry: `status.phase = retrying`, `status.actor = currentActor`.
On success: `status.phase = succeeded`, `status.error = nil`.
On failure: `status.phase = failed`, `status.reason = <reason>`, `status.error = <details>`.

## Retry Transport Requirement

`retryMessage` calls `transport.SendWithDelay(queue, body, delay)`. If the
transport returns `ErrDelayNotSupported` (e.g. RabbitMQ), the sidecar falls back
to `sendRetryFailure(RuntimeError)` immediately — the envelope goes to `x-sink`
on the first retry attempt.

## Metrics Emitted

| Metric call | When |
|---|---|
| `RecordMessageProcessed("error")` | Every error response |
| `RecordProcessingDuration` | Every error response (once, in `handleErrorResponse`) |
| `RecordMessageProcessed("retried")` | Successful `SendWithDelay` |
| `RecordMessageFailed("retry_send_failed")` | `SendWithDelay` fails |
| `RecordMessageProcessed("policy_routed")` | Routed to `onExhausted` actor |
| `RecordMessageFailed("policy_exhausted")` | Sent to x-sink as exhausted |

Note: `RecordProcessingDuration` is called **only** in `handleErrorResponse`,
not inside `applyPolicy` terminal branches, to avoid double-counting.

## Termination Paths

See `docs/internal/crew-termination.md` for the x-sink → x-sump chain and
the envelope status fields set by `sendRetryFailure` and `routeOnExhausted`.
