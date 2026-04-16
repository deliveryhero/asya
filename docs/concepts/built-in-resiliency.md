---
description: "Resiliency: durable queues, configurable retry policies, DLQ routing, SLA deadlines, timeouts"
---

# Built-in Resiliency

Messages in Asya are durably queued. A pod can be evicted, restarted, or
replaced — the message stays in the queue until successfully processed. This
durability is the foundation for several resiliency features built into the
sidecar.

## Durable message delivery

Every transport backend (SQS, RabbitMQ, Pub/Sub) provides at-least-once
delivery. Messages are acknowledged only after the sidecar confirms successful
processing. If a pod crashes mid-processing, the message becomes visible again
and is picked up by another replica.

## Configurable retry policies

Each actor can define its own retry policy:

- **Max attempts** — how many times to retry before giving up
- **Backoff strategy** — fixed, linear, or exponential delay between retries

Retries are handled by the sidecar, not the handler. The handler code does not
need to implement retry logic.

## Dead Letter Queue (DLQ)

Messages that exhaust all retries are routed to `x-sump`, the system DLQ actor.
`x-sump` persists failed messages for later inspection and replay. Failed
messages are never silently dropped.

The error flow:

1. Handler returns an error or raises an exception
2. Sidecar applies the retry policy
3. After max attempts, sidecar routes to `x-sink` with `phase: failed`
4. `x-sink` forwards to `x-sump` for DLQ persistence

## Three-level failure model

Asya handles failures at three distinct levels, each with its own recovery
mechanism:


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
       transport     (SendWithDelay     to x-sink
       redelivers    to own queue)     (phase: failed)
            │             │
       After N            │
       redeliveries       │ (on success)
       (maxReceiveCount)  ▼
            │          ACK + route
            ▼          to next actor
       Transport       or x-sink
       DLQ queue       (phase: succeeded)
            │
            ▼
       x-dlq worker
       (persist + report
        to gateway)
```

| # | Failure | Current behavior | Desired behavior |
|---|---------|------------------|------------------|
| 1 | **Sidecar crash/panic** | Nack → redelivery loop | No ACK → after N redeliveries → transport DLQ → `x-dlq` worker persists + reports to gateway |
| 2 | **Retriable handler error** | ACK + send to error-end (no retry) | ACK + increment attempt + compute delay + `SendWithDelay` back to own queue |
| 3 | **Fatal handler error / max attempts** | Same as #2 | ACK + send to `x-sink` (phase: failed, reason: NonRetryableFailure or MaxRetriesExhausted) |


## Example: AsyncActor resiliency configuration

```yaml
spec:
  resiliency:
    actorTimeout: 90s
    policies:
      default:
        maxAttempts: 3
        backoff: exponential
        initialInterval: 1s
        maxInterval: 60s
    rules:
    - errors: ["ValueError", "KeyError"]
      policy: noRetry
```

This configures the actor to retry up to 3 times with exponential backoff and
enforce a 90-second handler execution timeout. Errors matching `ValueError` or
`KeyError` skip retries and route to x-sink immediately.

## SLA enforcement

Envelopes carry an optional `deadline_at` header. The sidecar checks this
deadline before passing the message to the runtime. If the deadline has passed,
the message is routed directly to the error path without wasting compute on
processing it.

## Handler execution timeouts

The sidecar enforces a configurable timeout on handler execution. If the handler
does not respond within the timeout, the sidecar terminates the request and
applies the retry policy.

## Further reading

- [Error handling specification](../reference/specs/error-handling.md) — error
  classification, retry behavior, DLQ routing
- [Retries setup guide](../setup/guide-retries.md) — configuring retry policies
  per actor
- [Timeouts guide](../setup/guide-timeouts.md) — handler timeouts and SLA
  deadlines
