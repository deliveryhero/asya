<!-- Type: Usage Guide -->
# Actor Timeouts

How to configure per-actor timeouts in your AsyncActor specs to prevent runaway executions.

---

## What is actorTimeout?

`actorTimeout` is the maximum wall-clock time your actor has to process a single message. If the runtime doesn't respond within this duration, the sidecar cancels the message and routes it to the error queue (`x-sump`).

Set it in the AsyncActor spec under `resiliency.actorTimeout`:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: llm-inference
  namespace: prod
spec:
  actor: llm-inference

  resiliency:
    actorTimeout: 5m  # 5 minutes
```

**Format**: Duration string (`30s`, `2m`, `1h`). No default — if omitted, the actor has unlimited time.

---

## What happens when a timeout fires?

When the sidecar's deadline expires before the runtime responds:

1. **Runtime is cancelled** — the sidecar stops waiting for a response
2. **Envelope routed to x-sump** — the error queue receives the message with a timeout error
3. **Pod crashes** — the sidecar exits with status code 1 to prevent zombie processing

The pod crash forces Kubernetes to restart the container, ensuring a clean slate for the next message. This prevents scenarios where the runtime continues executing after the sidecar has given up.

**Log entry** (sidecar):

```
[ERROR] Runtime timeout: context deadline exceeded
[INFO] Routing to x-sump: timeout_error
[FATAL] Crashing pod to prevent zombie processing
```

---

## Timeout vs SLA deadline

Asya has two timeout mechanisms:

| Type | Scope | Configured in | Enforced by | On expiry |
|------|-------|---------------|-------------|-----------|
| **actorTimeout** | Single actor call | AsyncActor `resiliency.actorTimeout` | Sidecar | Routes to x-sump, crashes pod |
| **SLA deadline** | Entire pipeline | Gateway `status.deadline_at` | Sidecar | Routes to x-sink with `phase=failed, reason=Timeout` |

**actorTimeout** is per-actor: each actor in a multi-actor pipeline gets the full timeout budget.

**SLA deadline** is pipeline-wide: the gateway sets `status.deadline_at` when creating the envelope; each actor checks it before calling the runtime. If the deadline has passed, the sidecar routes the envelope directly to `x-sink` without calling the runtime.

### Example: 3-actor pipeline

```yaml
# AsyncActor: actor-a
resiliency:
  actorTimeout: 2m

# AsyncActor: actor-b
resiliency:
  actorTimeout: 5m

# AsyncActor: actor-c
resiliency:
  actorTimeout: 1m
```

With a 10-minute SLA set by the gateway:

- **actor-a** has up to 2 minutes to process
- **actor-b** has up to 5 minutes to process
- **actor-c** has up to 1 minute to process
- If the cumulative time exceeds 10 minutes, remaining actors see the SLA expired and route to `x-sink`

---

## Effective timeout calculation

The sidecar enforces the **minimum** of:

1. `actorTimeout` from the AsyncActor spec
2. Remaining time until the SLA deadline (if set)

```python
effective_timeout = min(actorTimeout, remaining_SLA_time)
```

If the SLA deadline is 30 seconds away but `actorTimeout` is 5 minutes, the runtime has only 30 seconds.

**Log entry** (sidecar):

```
[DEBUG] Computed timeout: actor=5m0s, remaining_SLA=42s, effective=42s
```

---

## Setting actorTimeout

### Short timeouts for fast actors

For actors that should complete quickly (e.g., data validation, routing logic):

```yaml
resiliency:
  actorTimeout: 30s
```

**Benefits**:
- Fail fast on unexpected hangs
- Free up queue consumers quickly
- Prevent resource waste

### Long timeouts for AI workloads

For actors that call LLM APIs or run heavy inference:

```yaml
resiliency:
  actorTimeout: 10m
```

**Benefits**:
- Allow sufficient time for model initialization
- Accommodate slow streaming responses
- Handle bursty LLM API latency

### Unlimited timeout (not recommended)

Omit `resiliency.actorTimeout` entirely:

```yaml
resiliency: {}
```

The actor has unlimited time unless an SLA deadline is set. **Discouraged** — without a timeout, a hung runtime can block a queue consumer indefinitely.

---

## Best practices

### 1. Always set a timeout

Even if you expect an actor to complete in seconds, set a generous timeout (e.g., 5 minutes) to catch unexpected hangs.

```yaml
resiliency:
  actorTimeout: 5m
```

### 2. Align timeout with workload

Match the timeout to the actor's expected latency:

| Actor type | Typical timeout |
|-----------|----------------|
| Data validation, routing | 30s - 1m |
| Database queries, API calls | 1m - 3m |
| LLM inference (streaming) | 3m - 10m |
| Batch processing, model training | 10m - 1h |

### 3. Add headroom for variability

Set the timeout to **2-3x** the expected p95 latency to accommodate:
- LLM API rate limits and retries
- Slow model initialization on cold starts
- Bursty network latency

```yaml
# Expected p95: 2 minutes
# Set timeout: 5 minutes (2.5x headroom)
resiliency:
  actorTimeout: 5m
```

### 4. Monitor timeout metrics

The sidecar exposes Prometheus metrics for timeout events:

```
asya_actor_runtime_errors_total{error_type="timeout"}
```

If timeouts are frequent, either:
- Increase the timeout (if the workload is legitimately slow)
- Investigate why the runtime is hanging (if timeouts are unexpected)

---

## Debugging timeout issues

### Symptoms of timeout problems

- **Frequent pod restarts** — Kubernetes CrashLoopBackoff due to sidecar crashes
- **Messages stuck in x-sump** — timeout errors accumulating in the error queue
- **Progress stops mid-pipeline** — later actors never receive envelopes

### Common causes

| Cause | Solution |
|-------|----------|
| Timeout too short for workload | Increase `actorTimeout` to match expected latency |
| Runtime code hangs (infinite loop, deadlock) | Add defensive timeouts in user code; review logic |
| LLM API rate limit / slow endpoint | Implement backoff in handler; increase timeout |
| Model initialization too slow | Cache model in memory (class handler with `__init__`) |
| SLA deadline too tight | Increase SLA at gateway or reduce pipeline depth |

### Inspecting timeout logs

**Sidecar logs** (where the timeout is enforced):

```bash
kubectl logs -n prod deployment/llm-inference -c asya-sidecar
```

Look for:

```
[ERROR] Runtime timeout: context deadline exceeded
[INFO] Routing to x-sump: timeout_error
```

**Runtime logs** (what the handler was doing):

```bash
kubectl logs -n prod deployment/llm-inference -c asya-runtime
```

Look for the last log entry before the timeout — that's where the runtime was stuck.

---

## Timeout propagation in multi-actor pipelines

Timeouts do NOT propagate across actors. Each actor enforces its own `actorTimeout` independently.

**Example**:

```yaml
# actor-a
resiliency:
  actorTimeout: 2m

# actor-b
resiliency:
  actorTimeout: 5m
```

If actor-a takes 1m 50s and routes to actor-b, actor-b gets the full 5 minutes — not the remaining 10 seconds from actor-a's timeout.

**However**, the SLA deadline DOES propagate:

- Gateway sets `status.deadline_at` when creating the envelope
- Each actor checks the deadline before calling the runtime
- If the deadline has passed, the actor routes to `x-sink` (phase=failed, reason=Timeout)

This ensures the **entire pipeline** respects the SLA even if individual actors have generous timeouts.

---

## Timeout vs retry policies

`actorTimeout` controls **when** the sidecar gives up on a single message.

Retry policies (configured via `resiliency.policies` and `resiliency.rules`) control **what** happens after the timeout:

```yaml
resiliency:
  actorTimeout: 5m
  policies:
    llm_retry:
      maxAttempts: 3
      delay: 10s
      backoffMultiplier: 2
  rules:
    - errorMatch: "timeout_error"
      policy: llm_retry
```

With this configuration:
1. Sidecar waits up to 5 minutes for the runtime to respond
2. If the timeout fires, the envelope is routed to `x-sump` with a `timeout_error`
3. The retry policy sees `timeout_error` and re-enqueues the message
4. After 3 attempts, the message is marked as failed

See the retry policy documentation for details on configuring error-specific retry behavior.

---

## See also

| Topic | Document |
|-------|----------|
| Sidecar timeout enforcement | [docs/reference/components/core-sidecar.md](../reference/components/core-sidecar.md) |
| Runtime behavior on timeout | [docs/reference/components/core-runtime.md](../reference/components/core-runtime.md) |
| Retry policies for timeout errors | [../reference/specs/error-handling.md](../reference/specs/retry-policies.md) |
| SLA configuration | [docs/reference/components/core-gateway.md](../reference/components/core-gateway.md) |

---
**Platform configuration**: To configure SLA, gateway backstop, and transport-level timeouts, see [setup/guide-timeouts.md](../setup/guide-timeouts.md).
