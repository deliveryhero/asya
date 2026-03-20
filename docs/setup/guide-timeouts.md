# Configuring Timeouts

This guide covers timeout configuration at the platform level — how to set up timeout constraints in AsyncActor manifests, gateway configuration, and transport settings.

## Overview

Asya enforces timeouts at three levels:

1. **Actor timeout** — per-call limit enforced by the sidecar
2. **SLA timeout** — pipeline-level deadline enforced by the sidecar before calling the runtime
3. **Gateway backstop timeout** — hard limit for tool invocations enforced by the gateway

These timeouts interact in a layered fashion:

```
actor timeout (per-call) < SLA timeout = gateway backstop (per-pipeline)
```

The SLA timeout and gateway backstop share the same `timeout` value from `flows.yaml`. The actor timeout is a per-call limit; the SLA is a pipeline-wide deadline.

## Actor Timeout (Per-Call)

The actor timeout is the maximum duration a single runtime invocation can take. It is configured in the AsyncActor spec under `resiliency.actorTimeout` and enforced by the sidecar.

### Configuration

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: ml-inference
  namespace: prod
spec:
  actor: ml-inference
  image: my-org/ml-inference:latest
  handler: inference.handle

  resiliency:
    actorTimeout: 5m  # 5 minutes per call
```

**Format**: Duration string — `30s`, `5m`, `1h30m`

**Default**: `5m` (set by Crossplane composition if not specified)

### Behavior on timeout

When the runtime exceeds `actorTimeout`:

1. Sidecar sends the envelope to `x-sump` with a timeout error
2. Sidecar **crashes the pod** (exits with status 1)
3. Kubernetes restarts the pod to recover clean state

**Rationale**: Crash-on-timeout prevents zombie processing where the runtime may still be executing after the sidecar gives up.

### When to adjust

- **Increase** for long-running tasks: model loading, heavy inference, large file processing
- **Decrease** for fast operations: lookups, simple transforms, caching

**Example** — GPU model inference with 2-minute timeout:

```yaml
resiliency:
  actorTimeout: 2m
```

## SLA Timeout (Pipeline Deadline)

The SLA timeout is the maximum end-to-end duration for an entire pipeline. It is set by the gateway when a tool is invoked and stored in the envelope's `status.deadline_at` field.

The sidecar checks `status.deadline_at` **before** calling the runtime. If the deadline has already passed, the envelope is routed directly to `x-sink` with `phase=failed`, `reason=Timeout` — the runtime is never called.

### Configuration

SLA is configured per flow in the gateway's `flows.yaml` ConfigMap:

```yaml
flows:
- name: image-enhance
  entrypoint: download-image
  route_next: [enhance, upload]
  description: Enhance image quality
  timeout: 120  # SLA: 120 seconds (2 minutes)
  mcp:
    inputSchema:
      type: object
      properties:
        image_url:
          type: string
      required: [image_url]
```

**Field**: `timeout` (integer, seconds)

**Default**: No SLA — envelope can run indefinitely

### How it works

1. Gateway receives tool invocation
2. Gateway stamps `status.deadline_at = now + timeout_seconds`
3. Envelope travels through actors
4. Each sidecar checks: `if now > deadline_at, route to x-sink (failed)`
5. Otherwise, sidecar calculates effective timeout: `min(actorTimeout, deadline_at - now)`

**Example timeline**:

```
t=0:    Gateway creates envelope (SLA: 120s, deadline_at = t+120)
t=10:   Actor A starts (remaining SLA: 110s, actorTimeout: 5m)
        Effective timeout: min(5m, 110s) = 110s
t=30:   Actor A completes (remaining SLA: 90s)
t=40:   Actor B starts (remaining SLA: 80s, actorTimeout: 5m)
        Effective timeout: min(5m, 80s) = 80s
t=125:  Actor C receives envelope (remaining SLA: -5s)
        Sidecar routes to x-sink immediately (phase=failed, reason=Timeout)
```

### When to adjust

- **Increase** for multi-actor pipelines with slow steps
- **Decrease** for single-actor tools or fast pipelines

**Monitoring**: Check `x-sink` for `phase=failed, reason=Timeout` to identify SLA violations.

## Gateway Backstop Timeout

The gateway maintains an independent backstop timer per task. This timer fires when a message is stuck in a queue and no sidecar ever picks it up, ensuring the task eventually reaches a terminal state.

### Configuration

The backstop timer uses the same `timeout` value from `flows.yaml` that sets `status.deadline_at` on the envelope. There is no separate environment variable.

```yaml
# Gateway flows.yaml
flows:
- name: image-enhance
  entrypoint: download-image
  route_next: [enhance, upload]
  timeout: 120  # Backstop timer fires after 120 seconds
```

**Default**: No backstop timer (task can wait indefinitely if `timeout` is omitted)

### Behavior on timeout

When the backstop timer fires:

1. Gateway marks the task as `failed` with error "envelope timed out"
2. SSE subscribers are notified with a failure event
3. Subsequent sidecar timeout reports are ignored (task is already terminal, first-write-wins)

### When to use

- **Enable** (set `timeout` in flows.yaml) for any flow exposed as an MCP tool or A2A skill
- **Omit** for internal pipelines or long-running workflows where no client is waiting

## Transport-Level Timeouts

Transport-specific timeouts control message visibility and redelivery. These are **not** actor processing timeouts — they determine how long a message remains invisible after being consumed.

### SQS Visibility Timeout

When a sidecar consumes a message from SQS, the message becomes invisible to other consumers. If the sidecar doesn't delete the message within the visibility timeout, SQS redelivers it.

**Configuration**:

The sidecar computes the default visibility timeout as `actorTimeout * 2`. With the default 5m actor timeout, visibility timeout is 600s (10 minutes). Override with `ASYA_SQS_VISIBILITY_TIMEOUT` (seconds).

```yaml
# Override in AsyncActor spec (injected as ASYA_SQS_VISIBILITY_TIMEOUT)
resiliency:
  actorTimeout: 2m  # → default visibility timeout = 240s
```

**Default**: `actorTimeout * 2` (e.g., 600s for 5m actor timeout)

**Why 2x**: The safety margin covers sidecar overhead (message parsing, routing, progress reporting) beyond the actor processing time.

**Interaction with actor timeout**:

- Visibility timeout should always be longer than `actorTimeout`
- If visibility timeout is shorter, SQS may redeliver while the actor is still processing
- Actors **must be idempotent** to handle duplicate delivery

### RabbitMQ Consumer Timeout

RabbitMQ uses a consumer timeout to detect stuck consumers. If a consumer doesn't ACK or NACK within the timeout, RabbitMQ closes the channel.

**Configuration** (RabbitMQ server-side):

```bash
# In RabbitMQ config (not AsyncActor spec)
consumer_timeout = 3600000  # 1 hour in milliseconds
```

**Default**: Infinite (RabbitMQ 3.8+)

**When to adjust**: Set a consumer timeout longer than your longest `actorTimeout` to prevent RabbitMQ from killing long-running actors.

## Timeout Hierarchy Summary

| Timeout | Scope | Configured in | Enforced by | On exceed |
|---------|-------|---------------|-------------|-----------|
| Actor timeout | Per-call | AsyncActor `resiliency.actorTimeout` | Sidecar | Send to x-sump, crash pod |
| SLA timeout | Pipeline | Gateway `flows.yaml` (`timeout` field) | Sidecar (pre-check before runtime) | Send to x-sink (phase=failed) |
| Gateway backstop | Tool invocation | Gateway `flows.yaml` (`timeout` field) | Gateway | Mark task as `failed` |
| SQS visibility | Message redelivery | `ASYA_SQS_VISIBILITY_TIMEOUT` (default: `actorTimeout * 2`) | SQS | Redeliver message |
| RabbitMQ consumer | Channel liveness | RabbitMQ server config | RabbitMQ | Close channel |

## Best Practices

1. **Set actor timeout longer than typical processing time** — leave headroom for variance; if 95th percentile is 30s, set `actorTimeout: 1m`.

2. **Set SLA timeout to sum of actor timeouts + buffer** — if a 3-actor pipeline has actors with 1m, 2m, 1m timeouts, set SLA to `5m` (not 4m) to account for routing overhead.

3. **The gateway backstop and SLA use the same timeout** — the `timeout` field in `flows.yaml` sets both `status.deadline_at` on the envelope and the gateway backstop timer. They fire at approximately the same time; whichever fires first wins (first-write-wins).

4. **Monitor timeout metrics** — track `asya_actor_runtime_errors_total{error_type="timeout"}` (actor timeouts) and `x-sink` messages with `phase=failed, reason=Timeout` (SLA timeouts).

5. **Use SLA for user-facing flows** — set `timeout` in `flows.yaml` for any flow exposed as an MCP tool or A2A skill to prevent runaway pipelines.

6. **Tune visibility timeout if needed** — the default `actorTimeout * 2` should work for most cases. Override `ASYA_SQS_VISIBILITY_TIMEOUT` if you see duplicate processing from SQS redelivery.

## Example: Multi-Actor Pipeline

```yaml
# AsyncActor: download-image
resiliency:
  actorTimeout: 1m  # Download typically takes 20s

---
# AsyncActor: enhance-image
resiliency:
  actorTimeout: 3m  # Model inference takes up to 2m

---
# AsyncActor: upload-image
resiliency:
  actorTimeout: 1m  # Upload typically takes 30s

---
# Gateway flows.yaml
flows:
- name: image-enhance
  entrypoint: download-image
  route_next: [enhance-image, upload-image]
  timeout: 360  # SLA: 6 minutes (buffer: 1m + 3m + 1m + 1m)
  mcp:
    inputSchema: {...}

```

**Result**:

- Each actor has a per-call timeout appropriate to its workload
- Pipeline SLA prevents end-to-end runaway (6 minutes max)
- Gateway backstop timer uses the same 360s timeout to mark the task failed if no sidecar reports
- SQS visibility timeout defaults to `actorTimeout * 2` per actor, ensuring adequate processing time

---

**Using timeouts**: To set timeouts in your actor handlers, see [usage/guide-timeouts.md](../usage/guide-timeouts.md).
