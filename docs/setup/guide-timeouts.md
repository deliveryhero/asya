# Configuring Timeouts

This guide covers timeout configuration at the platform level — how to set up timeout constraints in AsyncActor manifests, gateway configuration, and transport settings.

## Overview

Asya enforces timeouts at three levels:

1. **Actor timeout** — per-call limit enforced by the sidecar
2. **SLA timeout** — pipeline-level deadline enforced by the sidecar before calling the runtime
3. **Gateway backstop timeout** — hard limit for tool invocations enforced by the gateway

These timeouts interact in a cascading fashion:

```
actor timeout < SLA timeout < gateway backstop timeout
```

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

The gateway enforces a hard timeout for blocking tool invocations. This prevents clients from waiting indefinitely for a response.

### Configuration

Set via environment variable in the gateway deployment:

```yaml
# deploy/helm-charts/asya-gateway/values.yaml
config:
  taskTimeout: 300  # 300 seconds (5 minutes)
```

This sets `ASYA_TASK_TIMEOUT=300` in the gateway pod.

**Default**: No backstop timeout (tool can wait indefinitely)

### Behavior on timeout

When `ASYA_TASK_TIMEOUT` is exceeded:

1. Gateway returns HTTP 504 Gateway Timeout
2. The envelope **continues processing** in the mesh
3. Final result is stored in the database but not returned to the client

**Use case**: Prevent slow pipelines from blocking HTTP clients while allowing async completion.

### When to use

- **Enable** for public-facing APIs where client timeouts must be predictable
- **Disable** (or set very high) for internal tool usage or long-running workflows

## Transport-Level Timeouts

Transport-specific timeouts control message visibility and redelivery. These are **not** actor processing timeouts — they determine how long a message remains invisible after being consumed.

### SQS Visibility Timeout

When a sidecar consumes a message from SQS, the message becomes invisible to other consumers. If the sidecar doesn't delete the message within the visibility timeout, SQS redelivers it.

**Configuration** (Crossplane composition):

The SQS Queue resource is created with a fixed 30-second visibility timeout:

```yaml
# In deploy/helm-charts/asya-crossplane/templates/composition-asyncactor.yaml
spec:
  visibilityTimeout: 30
```

**Fixed value**: 30 seconds (not configurable per-actor)

**Why 30 seconds**: Short enough to quickly recover from sidecar crashes, long enough for most actors to ACK after processing.

**Interaction with actor timeout**:

- If `actorTimeout` > 30s, the actor may still be processing when SQS redelivers the message
- The old pod continues processing; a new pod receives the duplicate
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
| Gateway backstop | Tool invocation | Gateway `ASYA_TASK_TIMEOUT` | Gateway | Return 504 to client |
| SQS visibility | Message redelivery | SQS Queue (Crossplane) | SQS | Redeliver message |
| RabbitMQ consumer | Channel liveness | RabbitMQ server config | RabbitMQ | Close channel |

## Best Practices

1. **Set actor timeout longer than typical processing time** — leave headroom for variance; if 95th percentile is 30s, set `actorTimeout: 1m`.

2. **Set SLA timeout to sum of actor timeouts + buffer** — if a 3-actor pipeline has actors with 1m, 2m, 1m timeouts, set SLA to `5m` (not 4m) to account for routing overhead.

3. **Set gateway backstop longer than SLA** — if SLA is 5m, set `ASYA_TASK_TIMEOUT=360` (6 minutes) to allow for final status propagation.

4. **Monitor timeout metrics** — track `asya_actor_runtime_errors_total{error_type="timeout"}` (actor timeouts) and `x-sink` messages with `phase=failed, reason=Timeout` (SLA timeouts).

5. **Use SLA for user-facing flows** — set `timeout` in `flows.yaml` for any flow exposed as an MCP tool or A2A skill to prevent runaway pipelines.

6. **Tune visibility timeout if needed** — if actors routinely exceed 30s and you see duplicate processing, consider increasing SQS visibility timeout (requires patching the Crossplane composition).

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

---
# Gateway deployment
config:
  taskTimeout: 420  # Backstop: 7 minutes (SLA + 1m buffer)
```

**Result**:

- Each actor has a per-call timeout appropriate to its workload
- Pipeline SLA prevents end-to-end runaway (6 minutes max)
- Gateway backstop ensures HTTP clients timeout predictably (7 minutes)
- Transport visibility timeout (30s) is shorter than all actor timeouts — duplicate delivery is possible but rare

---

**Using timeouts**: To set timeouts in your actor handlers, see [usage/guide-timeouts.md](../usage/guide-timeouts.md).
