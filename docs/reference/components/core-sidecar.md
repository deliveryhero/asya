# Sidecar Architecture

Detailed architecture of the 🎭 Actor Sidecar. Please also refer to code documentation [`src/asya-sidecar/README.md`](https://github.com/deliveryhero/asya/blob/main/src/asya-sidecar/README.md)

## Overview

The 🎭 Actor Sidecar is a Go-based message routing service that sits between async message queues and actor runtime processes. It implements a pull-based architecture with pluggable transport layer.

## Key Features

- RabbitMQ support (pluggable transport interface)
- Unix socket communication with runtime
- Fan-out support (array responses)
- End actor mode
- Automatic error routing
- Prometheus metrics exposure

## Quick Start

```bash
export ASYA_ACTOR_NAME="my-queue"
export ASYA_RABBITMQ_URL="amqp://guest:guest@localhost:5672/"
./bin/sidecar
```

## Design Principles

1. **Transport Agnostic**: Pluggable interface supports multiple queue systems
2. **Simple Protocol**: JSON-based messaging over Unix sockets
3. **Fault Tolerant**: Automatic retry via NACK, timeout handling, graceful degradation
4. **Stateless**: Each message processed independently with no shared state
5. **Observable**: Structured logging for all operations

## Component Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    🎭 Actor Sidecar                      │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────┐     ┌──────────┐     ┌─────────────────┐   │
│  │ Config   │────▶│ Main     │────▶│ Router          │   │
│  └──────────┘     └──────────┘     └────────┬────────┘   │
│                                             │            │
│                   ┌─────────────────────────┼            │
│                   │                         │            │
│                   ▼                         ▼            │
│           ┌──────────────┐         ┌──────────────────┐  │
│           │  Transport   │         │ Runtime Client   │  │
│           │  Interface   │         └──────────────────┘  │
│           └──────┬───────┘                 │             │
│                  │                         │             │
│         ┌────────┴────────┐                │             │
│         │                 │                │             │
│         ▼                 ▼                ▼             │
│  ┌─────────────┐    ┌──────────┐     ┌──────────┐        │
│  │ RabbitMQ    │    │ Runtime  │     │ Metrics  │        │
│  │ Transport   │    │ Client   │     │ Server   │        │
│  └─────────────┘    └──────────┘     └──────────┘        │
│         │                  │                │            │
└─────────┼──────────────────┼────────────────┼────────────┘
          │                  │                │
          ▼                  ▼                ▼
    ┌──────────┐       ┌─────────────┐    ┌──────────┐
    │ RabbitMQ │       │   Actor     │    │Prometheus│
    │ Queues   │       │  Runtime    │    │          │
    └──────────┘       └─────────────┘    └──────────┘
```

## Message Flow

### 1. Receive Phase
```
Queue → Transport.Receive() → Router.ProcessMessage()
```
- Long polling from queue (configurable wait time)
- Parse JSON message structure
- Validate route information

### 2. Processing Phase
```
Router → Runtime Client → Unix Socket → Actor Runtime
```
- Extract payload from message
- Send payload to runtime via Unix socket
- Wait for response with timeout
- Handle multiple response scenarios:
  - Single response
  - Fan-out (array of responses)
  - Empty response (abort)
  - Error response
  - Timeout (no response)

### 3. Routing Phase
```
Router → Route Management → Transport.Send() → Next Queue
```
- Increment route.current counter
- Determine next destination:
  - Next actor in route if available
  - Happy-end if route complete or empty response
  - Error-end if error or timeout
- Send message(s) to destination queue(s)

### 4. Acknowledgment Phase
```
Router → Transport.Ack/Nack()
```
- ACK on successful processing
- NACK on error for retry

## Response Handling Summary

| Response | Action |
|----------|--------|
| Single value | Route to next actor |
| Array (fan-out) | Route each to next actor |
| Empty | Send to x-sink |
| Error (retriable) | Retry via SendWithDelay to own queue |
| Error (fatal/exhausted) | Send to x-sink (phase: failed) |
| SLA expired | Send to x-sink (phase=failed, reason=Timeout) |
| Runtime timeout | Send to x-sink (phase: failed), crash pod |
| End of route | Send to x-sink |

## Transport Interface

All transports implement this interface:

```go
type Transport interface {
    Receive(ctx context.Context, queueName string) (QueueMessage, error)
    Send(ctx context.Context, queueName string, body []byte) error
    Ack(ctx context.Context, msg QueueMessage) error
    Nack(ctx context.Context, msg QueueMessage) error
    Close() error
}
```

### Transport failures
🎭 operator owns the queues if deployed with `ASYA_QUEUE_AUTO_CREATE=true`.
This means, it will try to recreate a queue if it doesn't exist or its configuration is not as desired.

Sidecar can detect queue errors and fail after graceful period that will cause pod restart.
Consider scenario:
1. Queue gets deleted (chaos scenario, accidental deletion, infrastructure failure)
2. Sidecar detects missing queue when trying to consume messages
3. Sidecar retries with exponential backoff (`ASYA_QUEUE_RETRY_MAX_ATTEMPTS=10` attempts, `ASYA_QUEUE_RETRY_BACKOFF=1s` seconds initial backoff)
4. Operator health check (every 5 min) detects missing queue and recreates it (if `ASYA_QUEUE_AUTO_CREATE=true`)
5. Sidecar successfully reconnects once queue is recreated (or enters failing state otherwise)


## Runtime Protocol

### Request Format
```
Raw JSON bytes (payload only)
```

### Success Response

Runtime returns the mutated payload directly:

**Single value:**
```json
{"processed": true, "timestamp": "2025-10-24T12:00:00Z"}
```

**Array (fan-out):**
```json
[{"chunk": 1}, {"chunk": 2}]
```

**Empty (no further processing):**
```json
null
```
or
```json
[]
```

### Error Response
```json
{
  "error": "error_code",
  "message": "Error description",
  "type": "ExceptionType"
}
```

## End Actor Mode

For end actors (x-sink, x-sump), set `ASYA_IS_END_ACTOR=true` to disable response routing.

```bash
export ASYA_ACTOR_NAME=x-sink
export ASYA_IS_END_ACTOR=true
./bin/sidecar
```

The sidecar will consume messages, forward to runtime, discard responses, and ACK. This is used for end-of-pipeline processing where no further routing is needed.

## Deployment Patterns

### Kubernetes Sidecar (Automatic)

The 🎭 operator automatically injects the sidecar when you deploy an AsyncActor CRD.

### Manual Deployment

```yaml
containers:

- name: asya-runtime
  image: my-actor:latest
  volumeMounts:
  - name: socket
    mountPath: /tmp/sockets
- name: sidecar
  image: ghcr.io/deliveryhero/asya-sidecar:latest
  env:
    - name: ASYA_ACTOR_NAME
      value: "my-actor-queue"
  volumeMounts:
  - name: socket
    mountPath: /tmp/sockets
volumes:

- name: socket
  emptyDir: {}
```

## Error Handling Strategy

| Error Type | Action | Destination |
|---|---|---|
| Handler success | ACK + route to next actor | Next actor or x-sink (phase: succeeded) |
| Handler error (retriable, attempts remaining) | ACK + SendWithDelay | Own queue (retry) |
| Handler error (retriable, exhausted) | ACK + send failed envelope | x-sink (phase: failed, reason: PolicyExhausted) |
| Handler error (fatal / non-retryable) | ACK + send failed envelope | x-sink (phase: failed, reason: NonRetryableFailure) |
| Parse error | ACK + send failed envelope | x-sink (phase: failed, no retry) |
| SLA expired | ACK + stamp phase=failed, reason=Timeout | x-sink |
| Runtime timeout | ACK + send to x-sink + crash pod | x-sink (phase: failed, reason: Timeout) |
| Runtime connection failure | ACK + retry (retriable) | Own queue |
| Transport error (can't send) | No ACK | Transport redelivers → DLQ |

## Configuration

All configuration via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_ACTOR_NAME` | _(required)_ | Queue to consume |
| `ASYA_SOCKET_PATH` | `/tmp/sockets/app.sock` | Unix socket path |
| `ASYA_RESILIENCY_ACTOR_TIMEOUT` | `5m` | Per-call actor timeout (from XRD `resiliency.actorTimeout`) |
| `ASYA_RESILIENCY_POLICIES` | `""` | JSON object of named retry policies (from XRD `resiliency.policies`) |
| `ASYA_RESILIENCY_RULES` | `""` | JSON array of error→policy rules (from XRD `resiliency.rules`) |
| `ASYA_ACTOR_SINK` | `x-sink` | Success queue |
| `ASYA_ACTOR_SUMP` | `x-sump` | Error queue |
| `ASYA_IS_END_ACTOR` | `false` | End actor mode |
| `ASYA_GATEWAY_URL` | `""` | Gateway URL for progress reporting (optional) |
| `ASYA_RABBITMQ_URL` | `amqp://guest:guest@localhost:5672/` | RabbitMQ connection |
| `ASYA_RABBITMQ_EXCHANGE` | `asya` | Exchange name |
| `ASYA_RABBITMQ_PREFETCH` | `1` | Prefetch count |

**Benefits**:

- No config files to manage
- Container-friendly
- Easy per-environment customization
- Validation on startup

## Concurrency Model

**Current**: Single-threaded sequential processing
- One message at a time
- Simple error handling
- Predictable behavior

**Future**: Configurable worker pool
- Concurrent message processing
- Higher throughput
- More complex error scenarios


## Failure Behavior and Recovery

### Sidecar Container Failure

**What happens:**
- Kubernetes automatically restarts the sidecar container (`restartPolicy: Always`)
- Messages in-flight are NACK'd and redelivered by RabbitMQ
- Runtime container continues running independently

**Message guarantees:**
- ✅ No message loss (NACK before ACK)
- ⚠️ Possible duplicate processing if sidecar dies after routing but before ACK
- ✅ Fast recovery (sub-second container restart)

**Critical window:** Between routing response to the next actor and ACK current message. If sidecar crashes in this window, the next queue receives the message but RabbitMQ redelivers the original.

### Runtime Container Failure

#### Crash/OOM Kill
**Detection:** Sidecar fails to connect to Unix socket (`failed to connect to runtime socket`)

**Recovery:**
1. Sidecar treats connection failure as a retriable error and retries via SendWithDelay
2. Kubernetes restarts runtime container automatically
3. Socket recreated on shared emptyDir volume
4. Retried message succeeds once runtime is back; if retries exhausted → x-sink (phase: failed)

**Message fate:** Retried as retriable error; after exhaustion sent to x-sink (phase: failed)

#### Timeout (Hung Process)
**Detection:** No response within effective timeout: `min(ASYA_RESILIENCY_ACTOR_TIMEOUT, remaining_SLA)`

**Recovery:**
1. Socket read returns `context.DeadlineExceeded`
2. Message sent to x-sink (phase: failed, reason: Timeout)
3. Sidecar **crashes the pod** (exits with status code 1)
4. Kubernetes restarts the pod to recover clean state

**Rationale:** Crash-on-timeout prevents zombie processing where the runtime may still be executing after the sidecar gives up.

#### SLA Expired (Pipeline Deadline)
**Detection:** `status.deadline_at` has passed before calling runtime

**Recovery:**
1. Message routed directly to x-sink with `phase=failed`, `reason=Timeout`
2. Runtime is never called — no wasted compute
3. Pod remains healthy for subsequent messages

**Message fate:** Sent to x-sink as a failed completion (not an error). The gateway reports the task as failed with timeout reason.

#### User Code Exception
**Detection:** Runtime returns error response with traceback

**Recovery:**
1. Error matched against resiliency policy rules
2. If retriable and attempts remaining: retried via SendWithDelay to own queue
3. If non-retryable or exhausted: routed to x-sink (phase: failed)
4. Runtime container remains healthy (exception was caught)
5. Ready to process next message

**Message fate:** Retried according to policy, or routed to x-sink (phase: failed) with detailed error context

### Message Delivery Guarantees

| Failure Scenario | Message Lost? | Auto Recovery | Notes |
|------------------|---------------|---------------|-------|
| Sidecar crash | ❌ No | ✅ Yes (fast) | NACK → redelivery |
| Runtime crash | ❌ No | ✅ Yes | Retried → x-sink (phase: failed) on exhaustion |
| Runtime OOM | ❌ No | ✅ Yes (may CrashLoopBackoff) | Retried → x-sink (phase: failed) on exhaustion |
| Runtime timeout | ❌ No | ✅ Yes (crash + restart) | Via x-sink (phase: failed), pod crashes to prevent zombie |
| SLA expired | ❌ No | ✅ Yes | Via x-sink (phase=failed), runtime not called |
| Pod eviction | ❌ No | ✅ Yes | Full pod restart |
| Socket corruption | ❌ No | ✅ Yes | Transient, usually recovers |

### At-Least-Once Semantics

The sidecar implements **at-least-once delivery**, not exactly-once:

- Messages ACK'd only after successful routing
- Failures before ACK result in redelivery
- Downstream actors **must be idempotent** to handle duplicates

### Operational Considerations

**Recommended for production:**

1. **Add liveness probe** to detect hung runtimes:
   ```yaml
   livenessProbe:
     exec:
       command: ["test", "-S", "/tmp/sockets/app.sock"]
     periodSeconds: 60
     timeoutSeconds: 5
     failureThreshold: 3
   ```

2. **Monitor retry metrics** (`asya_actor_messages_total{result="retried"}`)

3. **Monitor timeout metrics** (`asya_actor_runtime_errors_total{error_type="timeout"}`)

4. **Set resource limits** to prevent zombie containers from consuming excessive resources

5. **Configure readiness probes** to prevent routing to unhealthy pods during startup

## Resiliency

The sidecar implements policy-based retry and error routing. When a handler raises an exception, the sidecar matches it against configured rules to select a policy, then applies that policy to decide whether to retry, route to a fallback actor, or fail permanently.

### Configuration

Two environment variables control resiliency behavior:

- `ASYA_RESILIENCY_POLICIES` — JSON object of named policy configurations
- `ASYA_RESILIENCY_RULES` — JSON array of error-matching rules (optional)

When no rules are configured, all errors use the `default` policy.

Example:
```bash
ASYA_RESILIENCY_POLICIES='{"default":{"maxAttempts":3,"backoff":"exponential","initialDelay":"1s","maxInterval":"30s","jitter":true}}'
ASYA_RESILIENCY_RULES='[{"errors":["ValueError","KeyError"],"policy":"nonretryable"}]'
```

### Policy Fields

Each entry in `ASYA_RESILIENCY_POLICIES` is a named `PolicyConfig` object:

| Field | Type | Description |
|---|---|---|
| `maxAttempts` | int | Maximum attempts including the first. Default: 1 (no retry). |
| `backoff` | string | Backoff strategy: `constant`, `linear`, or `exponential`. |
| `initialDelay` | duration | Delay before the first retry (e.g. `"1s"`, `"500ms"`). |
| `maxInterval` | duration | Cap on per-attempt delay (e.g. `"30s"`, `"5m"`). |
| `maxDuration` | duration | Maximum total time across all retry attempts (e.g. `"10m"`). When exceeded, the policy is exhausted regardless of `maxAttempts`. |
| `jitter` | bool | Add random jitter to delays to prevent thundering-herd bursts. |
| `onExhausted` | string[] | Actor list to route the envelope to when the policy is exhausted. If omitted, the envelope goes to `x-sink` with `reason=PolicyExhausted`. |

### Backoff Strategies

| Strategy | Delay formula |
|---|---|
| `constant` | Every attempt waits `initialDelay`. |
| `linear` | Attempt N waits `N * initialDelay`, capped at `maxInterval`. |
| `exponential` | Attempt N waits `initialDelay * 2^(N-1)`, capped at `maxInterval`. |

All strategies respect `maxDuration` — once the total elapsed time since the first attempt exceeds `maxDuration`, the policy is exhausted.

### Error-Matching Rules

`ASYA_RESILIENCY_RULES` is an ordered JSON array. Each rule maps a set of error type patterns to a named policy:

```json
[
  {"errors": ["ValueError", "KeyError"], "policy": "nonretryable"},
  {"errors": ["requests.exceptions.Timeout"], "policy": "slow-retry"}
]
```

The sidecar checks rules in order and selects the first rule whose `errors` list matches the exception. If no rule matches, the `"default"` policy is used.

#### Pattern Matching

- **Short name** (no `.`): matches the part after the last `.` in any MRO entry. `"ValueError"` matches `builtins.ValueError`, `mylib.ValueError`, etc.
- **Fully-qualified name** (contains `.`): exact string equality against the exception type or any MRO ancestor.

MRO (Method Resolution Order) is the full inheritance chain of the exception, as reported by the Python runtime. This means `"Exception"` matches any subclass of `Exception`, making it a catch-all wildcard.

### Envelope Status at Failure

When an envelope reaches `x-sink` after policy exhaustion, its `status` block contains:

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

### Transport Constraints

Retry with delay requires the transport to support `SendWithDelay`. Currently:

| Transport | Retry with delay |
|---|---|
| SQS | ✅ Supported |
| Pub/Sub | ✅ Supported |
| RabbitMQ | ❌ Not supported — policy exhausts on first retry attempt, envelope goes to x-sink |

Non-retryable patterns (policies with `maxAttempts=1`) and `onExhausted` routing work on all transports since they do not require delayed sends.

### Internal Architecture

#### Configuration Loading

Two env vars are parsed at startup by `internal/config`:

- `ASYA_RESILIENCY_POLICIES` — JSON object decoded into `map[string]PolicyConfig`
- `ASYA_RESILIENCY_RULES` — JSON array decoded into `[]RetryRule`

Both live on `ResiliencyConfig`, which is `nil` when neither var is set (no resiliency configured; single attempt, legacy behaviour).

`PolicyConfig` struct:

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

`JSONDuration` parses Go duration strings (`"1s"`, `"500ms"`, `"5m"`) via `time.ParseDuration`.

#### Error Handling Flow

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

#### Policy Matching

Builds a candidate list: `[errorType] + mro`. Iterates rules in order; for each rule, checks every pattern against every candidate:

- **FQN pattern** (contains `.`): exact equality — `candidate == pattern`
- **Short name** (no `.`): matches `candidate[lastDot+1:]`

First matching rule wins; its `policy` key is looked up in `Policies`. If no rule matches, `Policies["default"]` is returned. If no default exists, returns `nil` → `sendRetryFailure(RuntimeError)`.

#### Policy Application

1. `maxAttempts = max(policy.MaxAttempts, 1)` — zero is treated as 1
2. `msg.Status.MaxAttempts = maxAttempts` — propagated to the final x-sink envelope
3. `attemptsExhausted = msg.Status.Attempt >= maxAttempts`
4. `durationExhausted = createdAt + maxDuration < now` (only when `MaxDuration > 0`)
5. If neither exhausted: `retryMessage` → `SendWithDelay(delay)`
6. If exhausted and `OnExhausted` non-empty: `routeOnExhausted`
7. If exhausted and `OnExhausted` empty: `sendRetryFailure(PolicyExhausted)`

#### Delay Computation

Delay for attempt N (1-indexed current attempt):

| Backoff | Formula |
|---|---|
| `constant` | `initialDelay` |
| `linear` | `N * initialDelay` |
| `exponential` | `initialDelay * 2^(N-1)` |

All capped at `maxInterval` (when set). Jitter adds `rand * 0.1 * delay`. Minimum returned delay is 0.

#### Envelope Status Lifecycle

`ensureAndUpdateStatus` is called at the start of every `ProcessMessage` to initialise or advance `msg.Status`:

| Condition | Action |
|---|---|
| `status == nil` | Create with `phase=pending`, `attempt=1`, `created_at=now` |
| `status.actor != currentActor` | Reset `attempt=1`, `created_at=now`, `error=nil` (actor transition) |
| Same actor, retry | Increment `attempt`, update `updated_at` |

The `created_at` reset on actor transition ensures `maxDuration` is scoped to the current actor, not the entire pipeline lifetime.

On retry: `status.phase = retrying`, `status.actor = currentActor`.
On success: `status.phase = succeeded`, `status.error = nil`.
On failure: `status.phase = failed`, `status.reason = <reason>`, `status.error = <details>`.

#### Retry Transport Requirement

`retryMessage` calls `transport.SendWithDelay(queue, body, delay)`. If the transport returns `ErrDelayNotSupported` (e.g. RabbitMQ), the sidecar falls back to `sendRetryFailure(RuntimeError)` immediately — the envelope goes to `x-sink` on the first retry attempt.

#### Metrics Emitted

| Metric call | When |
|---|---|
| `RecordMessageProcessed("error")` | Every error response |
| `RecordProcessingDuration` | Every error response (once, in `handleErrorResponse`) |
| `RecordMessageProcessed("retried")` | Successful `SendWithDelay` |
| `RecordMessageFailed("retry_send_failed")` | `SendWithDelay` fails |
| `RecordMessageProcessed("policy_routed")` | Routed to `onExhausted` actor |
| `RecordMessageFailed("policy_exhausted")` | Sent to x-sink as exhausted |

Note: `RecordProcessingDuration` is called only in `handleErrorResponse`, not inside `applyPolicy` terminal branches, to avoid double-counting.

## Metrics and Observability

The sidecar exposes Prometheus metrics for monitoring. See the [Resiliency](#resiliency) section for metrics emitted during retry and error handling.

## Next Steps

- [Runtime Component](core-runtime.md) - Actor runtime
