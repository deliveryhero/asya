---
title: "Timeouts: per-actor and per-flow"
priority: 2 # medium
type: epic
---


Design and implement a comprehensive timeout system that supports: (1) per-actor processing and graceful shutdown timeouts, (2) per-N-actors (flow or partial flow) end-to-end timeouts, (3) SQS visibility timeout coordination - actor processing timeout must align with SQS visibilityTimeout to prevent duplicate processing, (4) error handling edge cases - what happens when a timeout fires mid-processing, how retries interact with timeouts, (5) DLQ implications - messages that timeout vs messages that error, (6) multi-hop timeout budgets - a flow-level timeout that decrements as messages pass through actors. This is an epic that needs design before implementation.


---
## Notes

[Error Handling RFC context] [[1c46]] The per-message SLA timeout connects directly to error retry flow:

1. Every message carries status.created_at (set by gateway/first actor, never reset)
2. Every sidecar checks: now - status.created_at > SLA_TIMEOUT before processing
3. If SLA exceeded, sidecar routes directly to _sink with status.reason=Timeout
4. This prevents retries from continuing past the SLA deadline
5. For messages stuck in queues, gateway implements its own timeout monitoring

Env var: ASYA_RESILIENCY_SLA_TIMEOUT (or inside resiliency config structure)
Maps to Temporal's schedule_to_close_timeout concept.

Key interaction with retry: total timeout takes precedence over max_attempts. Even if attempts remain, an SLA-expired message goes directly to _sink.

Related: asya-y4kr (error handling RFC), status.created_at field in message schema.


---
_Migrated from beads `asya-ize`_
