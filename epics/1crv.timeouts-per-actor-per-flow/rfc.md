# RFC: Timeouts — Per-Actor and Per-Flow

**Epic**: 1crv
**Status**: Draft
**Date**: 2026-02-25

## Summary

Implement end-to-end timeout enforcement for Asya actor pipelines using absolute
deadlines on messages. The gateway stamps a `status.deadline_at` on every message;
every sidecar checks the deadline before processing and short-circuits expired
messages. Per-actor processing timeouts (`ASYA_RESILIENCY_ACTOR_TIMEOUT`) are wired
up as a secondary, more granular control.

## Motivation

### Current State

The timeout landscape has significant scaffolding but critical enforcement gaps:

**Working:**
- `ASYA_RUNTIME_TIMEOUT` (5m default) — enforced via `context.WithTimeout` in
  `runtime/client.go:CallRuntime()`. On timeout: crash pod (`os.Exit(1)`) to
  prevent zombie processing
- `ASYA_SQS_VISIBILITY_TIMEOUT` — coordinated with runtime timeout (2x fallback
  in `cmd/sidecar/main.go`)
- Retry backoff (`ASYA_RESILIENCY_RETRY_*`) — fully working with exponential/constant
  policies
- `status.created_at` — set in `router.go:ensureAndUpdateStatus()`, never reset
  across retries
- Gateway task timeout — `time.AfterFunc` timer per task, stored in PostgreSQL

**Scaffolded but dead:**
- `ASYA_RESILIENCY_ACTOR_TIMEOUT` — full pipeline exists (XRD field in
  `xrd-asyncactor.yaml:154`, injector extraction in `webhook/asyncactor.go:249`,
  env injection in `injection/inject.go:247`, config parsing in `config.go:227`)
  but the router **never reads `cfg.Resiliency.ActorTimeout`**
- Gateway `TimeoutSec` and `Deadline` fields on `types/task.go:43-44` — defined
  but not propagated to messages

**Missing:**
- No per-message SLA enforcement — stale messages consume actor resources
- Retries continue past useful lifetime of a request
- No coordination between gateway task timeout and sidecar processing

### Why This Matters

Without SLA enforcement, a slow 5-actor pipeline with 3 retries per actor can
process a message for `5 actors * 3 attempts * 5 min = 75 minutes` while the
caller gave up after 30 seconds. The gateway has no way to tell sidecars to stop
processing a stale request.

## Design

### Approach: Absolute Deadline

Each message carries an absolute deadline timestamp. Every sidecar computes
`remaining = deadline - now` and uses it to bound processing time. This is
equivalent to a decrementing budget but simpler:

- One field, set once by gateway, never mutated
- No per-hop message mutation needed
- Clock skew negligible within a K8s cluster (NTP-synced)
- Each sidecar implicitly gets the "remaining budget" by computing `deadline - now`

Crash-on-timeout is preserved as the hard safety net. For stateless actors this is
correct. For semi-stateful actors using CAS (state proxy connectors), pod crash is
safe by design — CAS is atomic, and version conflicts on retry are the expected
recovery path.

### 1. Message Protocol Changes

The `status` struct gains one new field (`deadline_at`):

```json
{
  "id": "msg-123",
  "route": {"prev": [], "curr": "analyzer", "next": ["summarizer"]},
  "status": {
    "phase": "processing",
    "created_at": "2026-02-25T10:00:00Z",
    "deadline_at": "2026-02-25T10:00:30Z",
    "updated_at": "2026-02-25T10:00:05Z",
    "actor": "analyzer",
    "attempt": 1,
    "max_attempts": 3
  },
  "payload": {}
}
```

| Field | Existing? | Set by | Mutated? | Purpose |
|-------|-----------|--------|----------|---------|
| `created_at` | Yes | First sidecar | Never | Emission timestamp for debugging, rollback |
| `deadline_at` | **New** | Gateway | Never | Absolute SLA deadline |
| `updated_at` | Yes | Each sidecar | Each hop | Last processing timestamp |

Messages without `deadline_at` (direct queue publish without gateway) skip the SLA
check entirely. Per-actor timeout still applies.

### 2. Sidecar SLA Enforcement

The sidecar checks the deadline **before invoking the runtime**:

```
Receive message from queue
    |
    v
Parse status.deadline_at
    |
    v
now > deadline_at? ----yes----> Report timeout to gateway (HTTP)
    |                           Route to x-sink (phase=failed, reason=Timeout)
    | no                        Ack message. No retry.
    v
Compute remaining = deadline_at - now
    |
    v
effective_timeout = min(remaining, actor_timeout, runtime_timeout)
    |
    v
CallRuntime(ctx with effective_timeout)
```

**Timeout precedence** (lowest wins):

1. `remaining_sla` — from `deadline_at - now` (per-message)
2. `ASYA_RESILIENCY_ACTOR_TIMEOUT` — per-actor, from XRD (0 = disabled)
3. `ASYA_RUNTIME_TIMEOUT` — global fallback, 5m default

**Expired message flow:**

1. Sidecar reports status to gateway: `{status: "failed", reason: "Timeout"}`
2. Sidecar routes message to x-sink with `status.phase = "failed"`,
   `status.reason = "Timeout"`
3. Message is acked from the queue
4. No retry — SLA expiry is terminal

**Important:** x-sump is NOT used for timeouts. x-sump is the error recovery path
for x-sink failures. Timeout is a normal (albeit failed) completion — it goes to
x-sink.

### 3. Wiring Up ActorTimeout

`ASYA_RESILIENCY_ACTOR_TIMEOUT` is already parsed into `cfg.Resiliency.ActorTimeout`
but never used. The router computes effective timeout per-message:

```go
func (r *Router) effectiveTimeout(msg *messages.Message) time.Duration {
    // Start with the global fallback
    timeout := r.cfg.Timeout  // ASYA_RUNTIME_TIMEOUT (5m default)

    // Per-actor override (if configured in XRD)
    if r.cfg.Resiliency != nil && r.cfg.Resiliency.ActorTimeout > 0 {
        timeout = r.cfg.Resiliency.ActorTimeout
    }

    // SLA remaining (if deadline exists on message)
    if deadline, ok := msg.DeadlineAt(); ok {
        remaining := time.Until(deadline)
        if remaining < timeout {
            timeout = remaining
        }
    }

    return timeout
}
```

The runtime client is changed to accept timeout per-call (as a parameter) instead
of storing it as a struct field. This enables per-message timeout without creating
new client instances.

### 4. Visibility Timeout Coordination

Updated formula in `cmd/sidecar/main.go`:

```go
visibilityTimeout = max(actorTimeout, runtimeTimeout) * 2
```

The `* 2` safety margin covers sidecar overhead (message parsing, routing, progress
reporting). SLA remaining does NOT affect visibility timeout because:

- Visibility timeout is set per-actor at subscription time, not per-message
- For messages that will be SLA-rejected immediately, the visibility timeout is
  unnecessarily long but harmless (message is acked quickly)

### 5. Gateway: Setting Deadlines

The gateway stamps `deadline_at` when creating a message:

```
status.created_at  = now
status.deadline_at = now + TimeoutSec
```

**Where `TimeoutSec` comes from:**

- Per-tool: `timeout_seconds` in tool configuration YAML
- Per-gateway default: `ASYA_GATEWAY_DEFAULT_TIMEOUT` env var (default: 5m)
- Explicit 0: no deadline stamped (no SLA enforcement)

### 6. Gateway Backstop Timer

The gateway maintains an independent `time.AfterFunc` timer per task. This is the
**backstop** for messages stuck in queues that no sidecar ever picks up.

When the timer fires:
1. Mark task as `failed` with `reason: "Timeout"`
2. Close SSE stream with timeout event (if client is streaming)
3. Subsequent sidecar timeout reports are ignored (task already terminal)

**No double-counting:** sidecar timeout report and gateway timer converge on the
same final state. Whichever fires first wins; the other is a no-op.

Race condition scenarios:

| Scenario | Result |
|----------|--------|
| Sidecar detects expiry first | Reports to gateway -> task marked failed. Gateway timer fires later, no-op. |
| Gateway timer fires first | Task marked failed. Sidecar eventually picks up stale message, reports timeout, gateway ignores. |
| Both fire simultaneously | First write wins (task state transition is atomic). Second is no-op. |

### 7. Retry + Timeout Interaction

**Total timeout takes precedence over max_attempts.**

Messages keep their original `created_at` and `deadline_at` across retries (never
reset). The SLA check runs before every attempt:

```
Attempt 1:  remaining=30s, actor_timeout=10s -> process (fails after 8s)
Attempt 2:  remaining=20s, actor_timeout=10s -> process (fails after 6s)
Attempt 3:  remaining=4s,  actor_timeout=10s -> process with 4s timeout
Attempt 4:  remaining=-2s  -> SLA expired, route to x-sink. No more retries.
```

Even if `max_attempts = 10`, the SLA stops retries once the deadline passes.

Non-retryable errors (matching `ASYA_RESILIENCY_NON_RETRYABLE_ERRORS`) still go
directly to x-sink without retry, regardless of remaining SLA. This is unchanged.

### 8. CAS + Pod Crash Safety

Semi-stateful actors using CAS (state proxy connectors — s3-buffered-cas,
redis-buffered-cas) are safe on pod crash:

| Crash timing | State impact |
|-------------|--------------|
| Before CAS write | No state change. Retry reads same state. |
| During CAS write | Atomic — succeeds or fails entirely. |
| After CAS write, before ack | Message redelivered. CAS detects version conflict on retry. Handler receives conflict error. |

CAS is designed for exactly this scenario. The only risk is multi-key non-atomic
updates (handler writes key A, crashes before writing key B), which is a handler
design concern, not a timeout concern.

## Configuration Reference

| Env Var | Component | Default | Purpose |
|---------|-----------|---------|---------|
| `ASYA_RUNTIME_TIMEOUT` | Sidecar | 5m | Global hard timeout for runtime calls |
| `ASYA_RESILIENCY_ACTOR_TIMEOUT` | Sidecar (via injector) | 0 (disabled) | Per-actor processing timeout from XRD |
| `ASYA_SQS_VISIBILITY_TIMEOUT` | Sidecar | `max(actor,runtime)*2` | SQS message invisibility period |
| `ASYA_GATEWAY_DEFAULT_TIMEOUT` | Gateway | 5m | Default task SLA when tool config omits it |

XRD field:
```yaml
spec:
  resiliency:
    actorTimeout: "30s"  # Per-actor processing timeout
```

## Changes Required

| Component | Files | Change |
|-----------|-------|--------|
| messages | `messages/message.go` | Add `DeadlineAt` string field + `ParseDeadline() (time.Time, bool)` helper |
| router | `router/router.go` | Add `effectiveTimeout()`, SLA check before `CallRuntime`, use per-message timeout |
| runtime client | `runtime/client.go` | Accept `timeout time.Duration` parameter in `CallRuntime` instead of struct field |
| sidecar main | `cmd/sidecar/main.go` | Update visibility timeout: `max(actorTimeout, runtimeTimeout) * 2` |
| config | `config/config.go` | No change (ActorTimeout already parsed) |
| injector | `injection/inject.go` | No change (already injects ASYA_RESILIENCY_ACTOR_TIMEOUT) |
| XRD | `xrd-asyncactor.yaml` | No change (actorTimeout field already exists) |
| gateway queue | `internal/queue/*.go` | Stamp `deadline_at` on message at publish time |
| gateway taskstore | `internal/taskstore/*.go` | Enforce backstop timer, mark task failed on fire |
| gateway types | `pkg/types/task.go` | Ensure `TimeoutSec` -> `Deadline` computation on task creation |

## Testing Strategy

### Unit Tests (src/)

- `effectiveTimeout` logic: correct precedence across all combinations
- `ParseDeadline`: valid RFC3339, missing field, malformed value
- SLA-expired message routing: no runtime call, report + route to x-sink
- Visibility timeout formula: `max(actor_timeout, runtime_timeout) * 2`
- Gateway deadline stamping: `deadline_at = created_at + TimeoutSec`
- Gateway backstop: task marked failed on timer, subsequent reports ignored

### Component Tests (testing/component/)

- Sidecar receives expired message: acked, routed to x-sink, runtime never called
- Sidecar receives message with tight SLA: runtime called with reduced timeout

### Integration Tests (testing/integration/)

- SLA enforcement across sidecar + runtime: expired mid-pipeline -> x-sink
- Retry + SLA interaction: retries stop on SLA expiry, not max_attempts
- Gateway backstop: message stuck in queue -> gateway times out independently

### E2E Tests (testing/e2e/)

- Full pipeline with SLA: task completes or times out within SLA
- Slow actor exceeds SLA: pod crash, task marked timed out
- Gateway backstop race: message delayed past SLA in queue, gateway marks task
  failed first, sidecar later reports timeout (ignored, already terminal)

## Out of Scope

- **Graceful cancellation**: crash-on-timeout is correct for stateless actors and
  GPU workloads. Adding a `/cancel` endpoint to runtime would require all handlers
  to support cooperative cancellation (significant contract change)
- **Decrementing budget**: absolute deadline achieves the same outcome with less
  complexity. Each sidecar implicitly gets the remaining budget via `deadline - now`
- **RabbitMQ consumer timeout**: RabbitMQ does not have visibility timeout semantics
- **Graceful shutdown timeout**: separate concern from SLA enforcement
- **Flow-level timeout distinct from message SLA**: the message SLA IS the flow
  timeout — the deadline travels with the message through the entire pipeline
