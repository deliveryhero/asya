# RFC: Native Error Handling with Automatic Retry

**Status**: Draft
**Authors**: Artem Yushkovskiy, Claude (brainstorm partner)
**Created**: 2026-02-10
**Epic**: asya-y4kr
**Related**: asya-ize (timeouts), asya-0gsw (handler signatures), asya-013s (CronJob scheduler), asya-pe6n (Flow DSL retry), asya-si1r (observability)

## Summary

Add native automatic error recovery to Asya: exponential backoff with jitter, configurable max attempts, fatal error classification via Python MRO, and transport-level delayed redelivery. Retry logic lives in the sidecar (no separate error-handler actor). Introduces a unified `_sink` terminal queue replacing `happy-end`/`error-end`, a standalone `_dlq` worker for infrastructure failures, and a Dapr-inspired resiliency configuration model.

## Motivation

Today, Asya has no retry mechanism for handler errors. When a handler throws an exception:
1. Runtime returns `{"error": "processing_error", "details": {...}}`
2. Sidecar ACKs the original message and sends it to `error-end` queue
3. `error-end` persists to S3 and reports failure to gateway
4. **The message is gone** — no retry, no recovery

For AI/agentic workloads, transient failures are the norm: LLM API rate limits, network blips, temporary resource exhaustion. Most errors are retriable, and a simple retry with backoff resolves them. Asya must support this natively without requiring users to implement in-handler retry logic.

### Scope

**In scope (this RFC)**:
- Automatic retry with exponential backoff, jitter, max attempts
- Fatal error classification (blacklist with MRO matching)
- Transport interface: `SendWithDelay()`, `Requeue()` (renamed from `Nack()`)
- Message schema: `status` top-level field with lifecycle phases
- Runtime: fully qualified error type with MRO in error responses
- `_sink` terminal queue (replaces `happy-end` + `error-end`)
- `_dlq` standalone worker for infrastructure failures
- Resiliency configuration (Dapr-inspired)

**Out of scope (future work)**:
- Saga pattern / reverse transactions
- Circuit breaker implementation (CEL expressions designed but deferred)
- Flow DSL retry syntax (asya-pe6n)
- Handler signature redesign for `retry_after` (asya-0gsw)
- CronJob-based scheduler for transports without `SendWithDelay` (asya-013s)
- Per-error-type retry counts
- Actor flavors for namespace-level defaults

## Architecture

### Design Principle: Retry in Sidecar, Not a Separate Actor

Early design explored a dedicated `_error` crew actor for retry routing. This was eliminated because `SendWithDelay` on the transport interface makes the queue itself the timer — the sidecar stays stateless while the queue holds the message invisibly during the backoff period. Benefits:

- No extra queue hop per retry (lower latency)
- No extra actor to deploy (simpler infrastructure)
- All retry logic in Go sidecar (native `cel-go` for future CEL expressions)
- Retrying messages keep the actor's queue non-empty (KEDA scales correctly)

### Failure Model (3 Levels)

```
                     Actor Pod
                 ┌─────────────────┐
                 │    Sidecar      │
                 │  ┌───────────┐  │
                 │  │  Runtime  │  │
                 │  └───────────┘  │
                 └────────┬────────┘
                          │
            ┌─────────────┼─────────────┐
            │             │             │
       Sidecar crash   Handler error   Handler error
       (OOM, panic,    (retriable)     (fatal / exhausted)
       bug in sidecar)     │                │
            │              │                │
            ▼              ▼                ▼
       No ACK →      ACK + retry       ACK + send
       transport     (SendWithDelay     to _sink
       redelivers    to own queue)     (phase: failed)
            │             │
       After N            │
       redeliveries       │ (on success)
       (maxReceiveCount)  ▼
            │          ACK + route
            ▼          to next actor
       Transport       or _sink
       DLQ queue       (phase: succeeded)
            │
            ▼
       _dlq worker
       (persist + report
        to gateway)
```

| # | Failure | Current behavior | Desired behavior |
|---|---------|------------------|------------------|
| 1 | **Sidecar crash/panic** | Nack → redelivery loop | No ACK → after N redeliveries → transport DLQ → `_dlq` worker persists + reports to gateway |
| 2 | **Retriable handler error** | ACK + send to error-end (no retry) | ACK + increment attempt + compute delay + `SendWithDelay` back to own queue |
| 3 | **Fatal handler error / max attempts** | Same as #2 | ACK + send to `_sink` (phase: failed, reason: NonRetryableFailure or MaxRetriesExhausted) |

### Sidecar Error Handling Contract

| Scenario | Sidecar action |
|----------|---------------|
| Handler returned success | ACK + route to next actor or `_sink` (phase: succeeded) |
| Handler returned retriable error, attempts remaining | ACK + `SendWithDelay(ownQueue, msg, delay)` |
| Handler returned retriable error, attempts exhausted | ACK + send to `_sink` (phase: failed, reason: MaxRetriesExhausted) |
| Handler returned fatal error (in nonRetryableErrors) | ACK + send to `_sink` (phase: failed, reason: NonRetryableFailure) |
| Message/task timeout exceeded | ACK + send to `_sink` (phase: failed, reason: Timeout) |
| Can't reach runtime (socket error, timeout) | ACK + retry (retriable — pod might restart) |
| Can't send to `_sink` or own queue | No ACK → transport redelivers → eventually DLQ |

## Message Schema

### Top-Level Structure (5 fields)

```json
{
  "id": "msg-abc-123",
  "route": {"actors": ["actor-a", "actor-b", "actor-c"], "current": 1},
  "headers": {"trace_id": "xyz-789"},
  "payload": {"input": "..."},
  "status": {
    "phase": "processing",
    "actor": "actor-b",
    "attempt": 1,
    "max_attempts": 5,
    "created_at": "2025-06-15T10:30:00Z",
    "updated_at": "2025-06-15T10:31:45Z"
  }
}
```

| Field | Type | Purpose |
|-------|------|---------|
| `id` | string | Unique message identifier |
| `route` | object | Routing: actor pipeline and current position |
| `headers` | object | Routing metadata: trace IDs, A/B flags, custom KV labels |
| `payload` | any JSON | Business data processed by actors |
| `status` | object | Message lifecycle state (always present) |

### `status` Object

```json
{
  "phase": "retrying",
  "reason": "RetryableError",
  "actor": "actor-b",
  "attempt": 2,
  "max_attempts": 5,
  "created_at": "2025-06-15T10:30:00Z",
  "updated_at": "2025-06-15T10:31:45Z",
  "error": {
    "type": "requests.exceptions.ConnectionError",
    "mro": ["ConnectionError", "IOError", "OSError", "Exception"],
    "message": "Connection refused",
    "traceback": "Traceback (most recent call last):..."
  }
}
```

| Field | Type | Always present | Description |
|-------|------|----------------|-------------|
| `phase` | string | ✅ | Lifecycle phase (see below) |
| `reason` | string | Only for failed | Why the message is in this phase |
| `actor` | string | ✅ | Current or last actor processing this message |
| `attempt` | int | ✅ | Current attempt number (starts at 1, per-actor scope) |
| `max_attempts` | int | ✅ | Maximum attempts allowed (from actor's resiliency config) |
| `created_at` | ISO 8601 | ✅ | When the message was created (never reset) |
| `updated_at` | ISO 8601 | ✅ | When the message was last picked up by a sidecar |
| `error` | object | Only on error | Error details (present during retrying/failed phases) |

### Phase Lifecycle

```
pending → processing → succeeded
                     → retrying → processing → ...
                     → failed
```

| Phase | Set by | Meaning |
|-------|--------|---------|
| `pending` | Gateway / message creator | Created, not yet picked up |
| `processing` | Sidecar (on receive) | Being handled by an actor |
| `retrying` | Sidecar (on retriable error) | Failed, re-queued with delay |
| `succeeded` | Sidecar (routing to `_sink`) | Terminal: completed successfully |
| `failed` | Sidecar (routing to `_sink`) | Terminal: exhausted or fatal |

### Reason Values (for `failed` phase)

| Reason | When |
|--------|------|
| `Completed` | Success (phase: succeeded) |
| `MaxRetriesExhausted` | All retry attempts used up |
| `NonRetryableFailure` | Error matched nonRetryableErrors blacklist |
| `Timeout` | Message or actor timeout exceeded |

### `status.error` Object

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Fully qualified Python exception class (e.g., `json.decoder.JSONDecodeError`) |
| `mro` | string[] | Method Resolution Order — ancestor classes excluding self and object/BaseException |
| `message` | string | Exception message |
| `traceback` | string | Full Python traceback |

### Phase Transitions During Retry

```
1. Message created:
   status: {phase: "pending", attempt: 1, max_attempts: 5, created_at: "T0"}

2. Sidecar receives:
   status: {phase: "processing", actor: "actor-b", attempt: 1, updated_at: "T1"}

3. Runtime error, sidecar retries:
   status: {phase: "retrying", actor: "actor-b", attempt: 1,
            error: {type: "TimeoutError", mro: ["Exception"], message: "..."}}
   → SendWithDelay(own queue, delay)

4. Message reappears after delay:
   status: {phase: "processing", actor: "actor-b", attempt: 2, updated_at: "T2"}
   (error cleared)

5a. Success → route to next actor:
   status: {phase: "processing", actor: "actor-c", attempt: 1, updated_at: "T3"}
   (attempt reset for new actor)

5b. Max retries → _sink:
   status: {phase: "failed", reason: "MaxRetriesExhausted", actor: "actor-b",
            attempt: 5, max_attempts: 5, error: {...}}
```

### Rules

- **Route and payload are NEVER modified** by retry logic — message must be redrivable
- **`attempt` is per-actor scoped** — resets to 1 when message moves to next actor
- **`created_at` is never reset** — used for SLA/message timeout calculation
- **`error` is cleared** when sidecar starts a new processing attempt
- **`error` is preserved** in terminal `failed` messages sent to `_sink`

## Transport Interface Changes

### Current Interface

```go
type Transport interface {
    Receive(ctx context.Context, queueName string) (QueueMessage, error)
    Send(ctx context.Context, queueName string, body []byte) error
    Ack(ctx context.Context, msg QueueMessage) error
    Nack(ctx context.Context, msg QueueMessage) error
    Close() error
}
```

### Proposed Interface

```go
type Transport interface {
    Receive(ctx context.Context, queueName string) (QueueMessage, error)
    Send(ctx context.Context, queueName string, body []byte) error
    SendWithDelay(ctx context.Context, queueName string, body []byte, delay time.Duration) error
    Ack(ctx context.Context, msg QueueMessage) error
    Requeue(ctx context.Context, msg QueueMessage) error
    Close() error
}
```

### `SendWithDelay`

Sends a message to a queue with a visibility delay. The message is invisible to consumers until the delay expires.

**Transport implementations:**

| Transport | Mechanism | Max delay |
|-----------|-----------|-----------|
| SQS | `DelaySeconds` parameter on `SendMessage` (0-900s) or schedule via message timer | 15 min per send, 12h via visibility |
| RabbitMQ | `x-delayed-message` plugin or TTL + dead-letter exchange | Plugin-dependent |
| NATS JetStream | `NakWithDelay` or re-publish with delivery delay | Unlimited |

For transports that don't support delayed delivery natively, `SendWithDelay` returns `ErrDelayNotSupported`. Future: CronJob-based scheduler crew actors (asya-013s) will handle these transports.

### `Requeue` (replaces `Nack`)

Best-effort optimization before crashing. Returns the message to the queue for immediate redelivery by another consumer. Used by the sidecar only when it detects an unrecoverable internal error but can still communicate with the broker.

**Semantic**: "I can't process this and I can't handle the error properly. Put it back for another attempt or eventual DLQ."

This is NOT used for application-level retry — that's handled by `SendWithDelay`. `Requeue` is a last-resort infrastructure signal.

## Runtime Changes

### Error Response: Fully Qualified Type + MRO

Current format:
```json
[{"error": "processing_error", "details": {"message": "...", "type": "ValueError", "traceback": "..."}}]
```

New format:
```json
[{
  "error": "processing_error",
  "details": {
    "message": "Expecting value: line 1 column 1",
    "type": "json.decoder.JSONDecodeError",
    "mro": ["ValueError", "Exception"],
    "traceback": "Traceback (most recent call last):..."
  }
}]
```

Implementation in `_error_response()`:
```python
exc_type = type(exc)
module = exc_type.__module__
qualname = exc_type.__qualname__
fqn = f"{module}.{qualname}" if module != "builtins" else qualname

mro = []
for cls in exc_type.__mro__[1:]:  # skip self
    if cls in (object, BaseException):
        continue
    m = cls.__module__
    n = cls.__qualname__
    mro.append(f"{m}.{n}" if m != "builtins" else n)
```

**Performance**: `__mro__` is a tuple cached on the type object at class definition time. Access is O(1), iteration is O(n) where n is typically 3-5. Negligible compared to `traceback.format_exception()`.

### Error Classification: MRO Matching

The sidecar checks if the error type or any of its MRO ancestors matches `nonRetryableErrors`:

```
nonRetryableErrors = ["ValueError"]
error.type = "json.decoder.JSONDecodeError"
error.mro = ["ValueError", "Exception"]

Match: "ValueError" found in mro → non-retryable
```

This enables polymorphic matching: configuring `ValueError` catches all 20+ stdlib subclasses plus user-defined subclasses.

## System Actors

### Naming Convention: `asya-` Prefix

System/crew actors use `asya-` prefix — clearly identifies framework-managed actors, distinguishes from user actors:

| Actor | Queue | Sidecar Role | Purpose |
|-------|-------|:---:|---------|
| `asya-sink` | `asya-{ns}-asya-sink` | `sink` | Reports final status to gateway, routes to hooks |
| `asya-sump` | `asya-{ns}-asya-sump` | `sump` | Final terminal: emits metrics, logs errors |
| `asya-dlq` | Transport DLQ | N/A | Standalone worker for transport-level failures |

### Sidecar Actor Roles

The sidecar's `ASYA_IS_END_ACTOR` boolean is replaced by a three-state `ASYA_ACTOR_ROLE`:

| Role | Gateway reporting | Routes responses | Env var |
|------|:-:|:-:|---------|
| `regular` (default) | Intermediate progress | ✅ to next actor | `ASYA_ACTOR_ROLE=regular` |
| `sink` | Final status (succeeded/failed) | ✅ to configured hooks | `ASYA_ACTOR_ROLE=sink` |
| `sump` | ❌ (Prometheus metrics only) | ❌ terminal | `ASYA_ACTOR_ROLE=sump` |

The separate `ASYA_ACTOR_HAPPY_END` and `ASYA_ACTOR_ERROR_END` are unified into a single `ASYA_ACTOR_SINK` (default: `asya-sink`). All sidecars (except sink/sump actors themselves) point to the same sink.

### Two-Layer Flow Termination

```
User pipeline (a -> b -> c)
    | route exhausted (succeeded or failed)
    v
asya-sink  [role=sink, ASYA_ACTOR_SINK=asya-sump]
    |-- Reports final status to gateway        [hardcoded, stable]
    |-- Routes to configured hooks             [sequential, deploy-time config]
    |     |
    |     v
    |   asya-checkpoint-s3  [role=regular, ASYA_ACTOR_SINK=asya-sump]
    |     |
    |     v
    |   asya-notify-slack   [role=regular, ASYA_ACTOR_SINK=asya-sump]
    |     |
    |     v chain completes or hook fails after retries
    |
    v
asya-sump  [role=sump]
    |-- Emits Prometheus metrics (hook_success / hook_failure)
    |-- On error: logs full message JSON to stdout
    |-- ACK. Terminal. Nothing below.
```

**Layer 1 (asya-sink)**: Graceful termination. Reports pipeline result to gateway, then dispatches message through configured hooks for finalization (S3 persistence, notifications, etc.).

**Layer 2 (asya-sump)**: Hard termination. Catches the output of completed hooks and failed hooks alike. Emits metrics for alerting. On error, logs the full message JSON to stdout as a last-resort persistence mechanism.

**No circularity**: User actors point to `asya-sink`, hooks point to `asya-sump`. Two distinct layers, no cycles.

### `asya-sink` (replaces `happy-end` + `error-end`)

The sink actor receives both succeeded and failed messages (distinguished by `status.phase`). It:
1. Validates `status.phase` is `succeeded` or `failed`
2. Constructs a hook route from deploy-time configuration (`ASYA_SINK_HOOKS=asya-checkpoint-s3,asya-notify-slack`)
3. Returns the message with the hook route for the sidecar to route
4. Sidecar (with `ASYA_ACTOR_ROLE=sink`) reports final status to gateway before routing

### `asya-sump` (final terminal)

The sump actor is the absolute bottom of the message flow:
1. Emits Prometheus metrics (counters for hook success/failure)
2. On error (`status.phase=failed`): logs the complete message JSON to stdout
3. Returns `None` (terminal — sidecar emits metrics, ACKs, done)

### Crew Actors as Dual-Purpose Integrations

Crew actors in `asya-crew` are general-purpose, reusable actors — not just finalizers. The same actor can serve different roles depending on its position in the pipeline:

| Actor | As hook (after asya-sink) | As mid-pipeline actor |
|-------|---------------------------|----------------------|
| `asya-checkpoint-s3` | Persists final message to S3 | Checkpoints intermediate state for recovery |
| `asya-notify-slack` | Sends completion notification | Sends progress notification |

**Package structure** (`src/asya-crew/asya_crew/`):
- `sink.py` — sink handler
- `sump.py` — sump handler
- `message_persistence/s3.py` — S3/GCS message persistence
- `notifications/slack.py` — Slack integration (future)

### `asya-dlq` Worker (Standalone)

A minimal Go binary (NOT an actor — no sidecar) that processes transport-level DLQ messages:

1. Polls DLQ queue using native transport SDK (not Asya's transport abstraction)
2. Parses message to extract `id`
3. POSTs failure status to gateway (`/tasks/{id}/final`)
4. Forwards complete message to `asya-sink` queue for persistence
5. ACKs from DLQ

**Design principle**: Different failure domain from sidecar. Uses native transport SDK directly to avoid sharing bugs with the component whose failure caused the DLQ event.

**Tiered approach for future**:
- Tier 1 (future): Managed platform pipes (EventBridge Pipes for SQS, Kafka Connect, Pub/Sub subscriptions)
- Tier 2 (this RFC): Universal Go binary for all transports
- Tier 3 (future): Reference Lambda/Cloud Function implementations

Note: Tier 1 is deferred because future mTLS between actors complicates identity propagation to third-party managed services.

## Resiliency Configuration

### Dapr-Inspired Structure

Resiliency config follows Dapr's proven model, adapted for Asya's per-actor configuration:

```yaml
apiVersion: asya.dev/v1alpha1
kind: AsyncActor
metadata:
  name: text-analyzer
spec:
  # ... other fields ...
  resiliency:
    retry:
      policy: exponential          # constant | exponential
      maxAttempts: 5               # 0 = no retry, -1 = infinite
      initialInterval: 1s         # first retry delay
      maxInterval: 300s            # cap for exponential growth
      backoffCoefficient: 2.0     # multiplier
      jitter: true                 # add randomness to prevent thundering herd
    nonRetryableErrors:            # blacklist: these errors skip retry
      - ValueError
      - KeyError
      - json.decoder.JSONDecodeError
    slaTimeout: 300s               # (future) message-level SLA
```

### Env Var Mapping

The Crossplane composition flattens the hierarchical structure into env vars for the sidecar:

```
ASYA_RESILIENCY_RETRY_POLICY=exponential
ASYA_RESILIENCY_RETRY_MAX_ATTEMPTS=5
ASYA_RESILIENCY_RETRY_INITIAL_INTERVAL=1s
ASYA_RESILIENCY_RETRY_MAX_INTERVAL=300s
ASYA_RESILIENCY_RETRY_BACKOFF_COEFFICIENT=2.0
ASYA_RESILIENCY_RETRY_JITTER=true
ASYA_RESILIENCY_NON_RETRYABLE_ERRORS=ValueError,KeyError,json.decoder.JSONDecodeError
ASYA_RESILIENCY_SLA_TIMEOUT=300s
```

### Reusability via EnvironmentConfig (Flavors)

Instead of a separate Resiliency CRD, resiliency profiles are reusable as Crossplane EnvironmentConfigs:

```yaml
apiVersion: apiextensions.crossplane.io/v1alpha1
kind: EnvironmentConfig
metadata:
  name: retry-3x-exponential
data:
  resiliency:
    retry:
      policy: exponential
      maxAttempts: 3
      initialInterval: 1s
      maxInterval: 60s
      backoffCoefficient: 2.0
      jitter: true
    nonRetryableErrors:
      - ValueError
```

**Priority**: Explicit actor config overrides EnvironmentConfig defaults (most specific wins).

### Backoff Formula

```
delay = min(initialInterval * backoffCoefficient^(attempt - 1), maxInterval)
if jitter:
    delay = delay * random(0.5, 1.5)  # full jitter
```

### Timeout Types

| Timeout | Scope | Configured by | Env var |
|---------|-------|---------------|---------|
| **Message timeout** | Total message lifetime | HTTP request to gateway / message creator | Set in `status` at creation |
| **Actor timeout** | One actor processing one message | AsyncActor resiliency config | `ASYA_RESILIENCY_SLA_TIMEOUT` |

Message timeout is a property of the message (set at creation, stored in status). Actor timeout is a deployment-time configuration. Both are checked by the sidecar before processing.

## ADR-001: Global vs Per-Error-Type Retry Counts

**Decision**: Global counter (`max_attempts` applies to all error types for a given actor).

**Reasoning**: If a message fails 5 times with different error types, it's likely fundamentally broken. Per-error-type counting adds complexity (need `map[error_type]int` instead of a single integer) for a rare corner case.

**Future extension**: `ASYA_RESILIENCY_RETRY_MAX_ATTEMPTS__ValueError=2` (double-underscore separator for per-type overrides).

See `docs/rfc/actor-flavors/temp.md` for full ADR.

## ADR-002: Retry State in Message — Overwrite, Not Accumulate

**Decision**: Only current actor's retry state is in `status`. No cross-pipeline retry history.

**Reasoning**: Retry history is observability data, not business state. Each retry emits metrics/logs (asya-si1r). The message carries operational state only ("what do I need to retry?"), keeping it lean for queue throughput.

## ADR-003: Eliminate `_error` Actor — Retry in Sidecar

**Decision**: Retry logic lives in the sidecar, not a separate crew actor.

**Context**: Early design proposed an `_error` crew actor as the retry router. With `SendWithDelay` on the transport interface, the queue itself becomes the timer. The sidecar calls `SendWithDelay(ownQueue, message, delay)`, ACKs the original, and is done — no state held.

**Benefits**: No extra queue hop, no extra actor deployment, CEL evaluation native in Go, KEDA scaling works naturally (retrying messages keep queue non-empty).

**Prerequisite**: All target transports must support `SendWithDelay`. For transports that don't, return `ErrDelayNotSupported` (future CronJob scheduler handles these — asya-013s).

## ADR-004: Two-Layer Termination (`asya-sink` + `asya-sump`)

**Decision**: Replace `happy-end` + `error-end` with a two-layer termination scheme: `asya-sink` (reports to gateway, routes to hooks) and `asya-sump` (final terminal, metrics only).

**Reasoning**: The original `_sink` design bundled gateway reporting with S3 persistence. Separating these concerns enables extensibility — users can configure arbitrary hooks (S3, Slack, email) without modifying the sink. The two-layer design prevents circular routing: user actors terminate at `asya-sink`, hooks terminate at `asya-sump`. Crew actors (like `asya-checkpoint-s3`) are dual-purpose — usable as post-sink hooks AND as mid-pipeline checkpointing actors.

**Sidecar changes**: `ASYA_IS_END_ACTOR` (boolean) replaced by `ASYA_ACTOR_ROLE` (regular/sink/sump). `ASYA_ACTOR_HAPPY_END` + `ASYA_ACTOR_ERROR_END` unified into `ASYA_ACTOR_SINK`. System actors prefixed with `asya-` instead of `_`.

## ADR-005: `_dlq` as Standalone Worker (Not Actor)

**Decision**: The DLQ worker is a minimal Go binary using native transport SDKs, not an Asya actor with sidecar.

**Reasoning**: Blast radius isolation. If a sidecar bug causes messages to end up in DLQ, using the same sidecar for DLQ processing means the DLQ worker fails the same way. Different failure domain = different code path.

## ADR-006: Dapr-Inspired Resiliency Configuration

**Decision**: Adopt Dapr's hierarchical resiliency structure, adapted for per-actor configuration via EnvironmentConfig flavors.

**What we adopt from Dapr**: Hierarchical structure (retry, circuitBreaker, timeout), field naming conventions, CEL for circuit breaker `trip` (future).

**What we adapt**: No separate Resiliency CRD (use EnvironmentConfig flavors), add `nonRetryableErrors` with MRO matching (from Temporal), add `jitter`, add `slaTimeout`.

## ADR-007: `Requeue()` Replaces `Nack()`

**Decision**: Rename `Nack()` to `Requeue()` with clear semantics: "best-effort optimization before crashing."

**Reasoning**: With retry logic in the sidecar, explicit Nack is only used as a last resort when the sidecar detects an unrecoverable internal error but can still talk to the broker. `Requeue` precisely describes the action (return message to queue) and avoids the ambiguous `Nack` semantics that differ across transports.

## Migration Path

### From Current to New

1. **Runtime**: Add `mro` field to `_error_response()` (backward compatible — sidecar ignores unknown fields)
2. **Transport**: Add `SendWithDelay()` and rename `Nack()` → `Requeue()` (breaking change for transport implementations, internal only)
3. **Sidecar**: Add retry logic, status management, resiliency config parsing, `ASYA_ACTOR_ROLE` (regular/sink/sump), unified `ASYA_ACTOR_SINK`
4. **Crew**: Create `asya-sink`, `asya-sump`, `asya-checkpoint-s3` actors. Remove `happy-end`/`error-end`
5. **Gateway**: Update `ResultConsumer` to listen on `asya-sink` queue (sink sidecar reports final status)
6. **Crossplane/Injector**: Set `ASYA_ACTOR_ROLE` based on actor name, create `asya-sink`/`asya-sump` queues, add resiliency fields to XRD, pass `ASYA_RESILIENCY_*` env vars
7. **Remove**: `happy-end`, `error-end`, `ASYA_ACTOR_HAPPY_END`, `ASYA_ACTOR_ERROR_END`, `ASYA_IS_END_ACTOR`

## Competitive Analysis

Temporal and Dapr research informed key design decisions. See `docs/rfc/error-handing/thoughts.md` for raw research notes.

| Aspect | Temporal | Dapr | Asya (this RFC) |
|--------|----------|------|-----------------|
| Retry location | Central server | Sidecar + Resiliency CRD | Sidecar (choreography) |
| Retry config | `RetryPolicy` on activity | Resiliency CRD (named policies) | Per-actor CRD + EnvironmentConfig flavors |
| Error classification | String type matching | HTTP status codes | MRO matching (polymorphic) |
| Attempt tracking | `attempt` field (int, starts at 1) | Not in message | `status.attempt` (int, starts at 1, per-actor) |
| DLQ handling | Server-managed | `deadLetterTopic` | Standalone Go worker (blast radius isolation) |
| Status model | Event history (immutable log) | `runtimeStatus` enum | `status.phase` lifecycle on message |
| Circuit breaker | N/A | CEL `trip` expressions | Designed, deferred to v2 |

## Open Questions

1. **SQS `DelaySeconds` limit**: SQS caps `DelaySeconds` at 900 seconds (15 min). For longer backoffs, need to chain delays (send with 900s delay, re-receive, re-delay) or use message timers. Implementation detail for SQS transport.
2. **Circuit breaker state**: Circuit breaker requires cross-message state (counting consecutive failures). Where does this state live? Sidecar memory (lost on restart) or shared storage? Deferred to v2.
3. **`retry_after` from handler**: Handler overriding backoff delay requires new handler signature (asya-0gsw). Designed but deferred.
4. **EnvironmentConfig priority**: When both EnvironmentConfig flavor and explicit actor config define the same field, which wins? Proposed: explicit actor config overrides.
