---
title: SQS delay chaining for retry backoffs exceeding 15-minute cap
status: open
priority: 3
---

## Context

SQS caps `DelaySeconds` at 900 seconds (15 minutes). The sidecar clamps delays to this maximum. Error-handling RFC open question #1 flagged this.

## Problem

For long-running AI workloads where retry delays should grow to 30min+ (e.g. waiting for a rate limit window to reset), the 900s cap means retries happen too frequently, wasting attempts.

## Proposed Solution

**Delay chaining**: When computed delay > 900s, send with 900s delay + store remaining delay in envelope header. On re-receive, if remaining delay > 0, re-delay without calling runtime.

```go
if delay > 900*time.Second {
    msg.Headers["_retry_remaining_delay"] = (delay - 900*time.Second).String()
    transport.SendWithDelay(ownQueue, msg, 900*time.Second)
}
// On receive, check _retry_remaining_delay before calling runtime
```

### Considerations
- Each chain hop costs one SQS send + receive (~$0.0000008)
- A 1-hour delay = 4 hops (4x 900s)
- Must not count chain hops as retry attempts
- Alternative: use SQS message timers (up to 12h visibility timeout) if available

## Scope

SQS transport only. RabbitMQ (plugin-dependent, no hard cap). NATS JetStream (unlimited).
