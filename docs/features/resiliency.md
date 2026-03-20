<!-- Type: Reference -->

# Resiliency: Policies and Retry Rules

Configure per-actor retry behavior via named policies and error-matching rules.

For practical recipes (exponential backoff, non-retryable errors, recovery
actors, time-capped retries), see
[How to Configure Retries](../howto/configure-retries.md).
When a handler raises an exception, the sidecar matches it against the configured
rules to select a policy, then applies that policy to decide whether to retry,
route to a fallback actor, or fail permanently.

## Quick Start

Set two environment variables on the actor's sidecar container:

```bash
# Named retry policies (JSON object)
ASYA_RESILIENCY_POLICIES='{"default":{"maxAttempts":3,"backoff":"exponential","initialDelay":"1s","maxInterval":"30s","jitter":true}}'

# Error-matching rules (JSON array, optional)
ASYA_RESILIENCY_RULES='[]'
```

With no rules, all errors use the `default` policy.

## Policy Fields

Each entry in `ASYA_RESILIENCY_POLICIES` is a named `PolicyConfig` object:

| Field | Type | Description |
|---|---|---|
| `maxAttempts` | int | Maximum attempts including the first. Default: 1 (no retry). |
| `backoff` | string | Backoff strategy: `constant`, `linear`, or `exponential`. |
| `initialDelay` | duration | Delay before the first retry (e.g. `"1s"`, `"500ms"`). |
| `maxInterval` | duration | Cap on per-attempt delay (e.g. `"30s"`, `"5m"`). |
| `maxDuration` | duration | Maximum total time across all retry attempts (e.g. `"10m"`). When exceeded, the policy is considered exhausted regardless of `maxAttempts`. |
| `jitter` | bool | Add random jitter to delays to prevent thundering-herd bursts. |
| `onExhausted` | string[] | Actor list to route the envelope to when the policy is exhausted. If omitted, the envelope goes to `x-sink` with `reason=PolicyExhausted`. |

## Backoff Strategies

| Strategy | Delay formula |
|---|---|
| `constant` | Every attempt waits `initialDelay`. |
| `linear` | Attempt N waits `N * initialDelay`, capped at `maxInterval`. |
| `exponential` | Attempt N waits `initialDelay * 2^(N-1)`, capped at `maxInterval`. |

All strategies respect `maxDuration` — once the total elapsed time since the first
attempt exceeds `maxDuration`, the policy is exhausted.

## Rules

`ASYA_RESILIENCY_RULES` is an ordered JSON array. Each rule maps a set of error
type patterns to a named policy:

```json
[
  {"errors": ["ValueError", "KeyError"], "policy": "nonretryable"},
  {"errors": ["requests.exceptions.Timeout"], "policy": "slow-retry"}
]
```

The sidecar checks rules in order and selects the first rule whose `errors` list
matches the exception. If no rule matches, the `"default"` policy is used.

### Pattern Matching

- **Short name** (no `.`): matches the part after the last `.` in any MRO entry.
  `"ValueError"` matches `builtins.ValueError`, `mylib.ValueError`, etc.
- **Fully-qualified name** (contains `.`): exact string equality against the
  exception type or any MRO ancestor.

MRO (Method Resolution Order) is the full inheritance chain of the exception,
as reported by the Python runtime. This means `"Exception"` matches any subclass
of `Exception`, making it a catch-all wildcard.

## Envelope Status at Failure

When an envelope reaches `x-sink` after policy exhaustion, its `status` block
contains:

```json
{
  "phase": "failed",
  "reason": "PolicyExhausted",
  "actor": "my-actor",
  "attempt": 3,
  "max_attempts": 3,
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-01T00:00:05Z",
  "error": {
    "type": "ValueError",
    "mro": ["ValueError", "Exception", "BaseException", "object"],
    "message": "...",
    "traceback": "..."
  }
}
```

When routed to an `onExhausted` actor instead, `reason` is `PolicyRouted`.

## Transport Constraints

Retry with delay requires the transport to support `SendWithDelay`. Currently:

| Transport | Retry with delay |
|---|---|
| SQS | ✅ Supported |
| RabbitMQ | ❌ Not supported — policy exhausts on first retry attempt, envelope goes to x-sink |

Non-retryable patterns (policies with `maxAttempts=1`) and `onExhausted` routing
work on all transports since they do not require delayed sends.

---

## See also

- [How to Configure Retries](../howto/configure-retries.md) — practical
  recipes for common retry scenarios
