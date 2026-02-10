Failure Model (4 Levels)

Let me redraw the complete picture with your corrections:

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
        (OOM, panic,    (retriable)     (fatal, in blacklist)
        bug in sidecar)     │             │
            │               │             │
            ▼               ▼             ▼
        Nack → msg      ACK + send     ACK + send
        returns to      to asya-error  to asya-sink
        same queue        queue       (status: failed)
            │               │
            │          ┌────┴────┐
        After N        │ attempt │
        redeliveries   │ < max?  │
        (transport      ┌──┴──┐
        maxReceive)   YES    NO
            │          │      │
            ▼          ▼      ▼
        Transport   SendWith  asya-sink
        DLQ queue   Delay to  (status: failed,
            │      source     reason: exhausted)
            │      queue
            │
            ▼
        asya-dlq worker
        (persist + report
        to gateway)

Four distinct cases:
┌─────┬─────────────────────────┬────────────────────────────────────────────┬─────────────────────────────────────────────────────────────────────────────────────────────┐
│  #  │         Failure         │              Current behavior              │                                      Desired behavior                                       │
├─────┼─────────────────────────┼────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
│ 1   │ Sidecar crash/panic     │ Nack → redelivery loop (no DLQ configured) │ Nack → after N redeliveries → transport DLQ → asya-dlq worker persists + reports to gateway │
├─────┼─────────────────────────┼────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
│ 2   │ Retriable handler error │ ACK + send to error-end (no retry)         │ ACK + send to asya-error → retry with backoff → on exhaustion → asya-sink                   │
├─────┼─────────────────────────┼────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
│ 3   │ Fatal handler error     │ Same as #2                                 │ ACK + send directly to asya-sink (skip asya-error)                                          │
├─────┼─────────────────────────┼────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
│ 4   │ asya-error itself fails │ N/A (doesn't exist yet)                    │ Nack → transport DLQ → asya-dlq worker                                                      │
└─────┴─────────────────────────┴────────────────────────────────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────┘



 With the error handler, the sidecar's contract becomes:
  ┌─────────────────────────────────────────────┬─────────────────────────────────────────────────────────────┐
  │                  Scenario                   │                       Sidecar action                        │
  ├─────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ Handler returned success                    │ ACK + route to next actor (or _sink)                        │
  ├─────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ Handler returned retriable error            │ ACK + send to _error                                        │
  ├─────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ Handler returned fatal error                │ ACK + send to _sink (status: failed)                        │
  ├─────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ Can't reach runtime (timeout, socket error) │ ACK + send to _error (it's retriable — pod might restart)   │
  ├─────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ Can't send to _error or _sink               │ Don't ACK → transport redelivers → eventually transport DLQ │
  └─────────────────────────────────────────────┴─────────────────────────────────────────────────────────────┘

 several transports DO have managed, zero-code DLQ processing:
  ┌───────────────────────┬──────────────────────────────────────────────┬────────────────────────────────────────────────────┬────────────────────┐
  │       Transport       │            Native "DLQ → Storage"            │            Native "DLQ → HTTP callback"            │     Zero-code?     │
  ├───────────────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────────────┼────────────────────┤
  │ SQS                   │ EventBridge Pipes: SQS → S3                  │ EventBridge Pipes: SQS → API Gateway/HTTP endpoint │ ✅ Fully managed   │
  ├───────────────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────────────┼────────────────────┤
  │ Kafka (MSK/Confluent) │ Kafka Connect S3 Sink Connector on DLQ topic │ Kafka Connect HTTP Sink Connector                  │ ✅ Connector-based │
  ├───────────────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────────────┼────────────────────┤
  │ Google Pub/Sub        │ Native Cloud Storage subscription type       │ Pub/Sub → Push subscription (HTTP endpoint)        │ ✅ Fully managed   │
  ├───────────────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────────────┼────────────────────┤
  │ Azure Service Bus     │ Service Bus → Azure Functions → Blob         │ Service Bus → Azure Functions → HTTP               │ ⚠️ Needs Function  │
  ├───────────────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────────────┼────────────────────┤
  │ RabbitMQ              │ No native S3 integration                     │ No native HTTP callback                            │ ❌ Needs consumer  │
  ├───────────────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────────────┼────────────────────┤
  │ NATS                  │ No native S3 integration                     │ No native HTTP callback                            │ ❌ Needs consumer  │
  └───────────────────────┴──────────────────────────────────────────────┴────────────────────────────────────────────────────┴────────────────────┘
  ★ Insight ─────────────────────────────────────
  The cloud-managed transports (SQS, Pub/Sub, MSK) have converged on a common pattern: managed pipes/connectors that can route DLQ messages to storage AND HTTP endpoints with zero custom
  code. AWS EventBridge Pipes is particularly elegant — it's essentially SQS DLQ → optional transform → fan-out to [S3 + HTTP] in a single managed resource. This is more robust than any
  custom worker because AWS guarantees delivery.
  ─────────────────────────────────────────────────

  So the design becomes layered:

  Tier 1: Managed DLQ routing (preferred, zero-code)

  For SQS, Pub/Sub, Kafka — configure the platform's native pipe/connector to:
  1. Archive DLQ messages to S3/GCS/Blob (for redrivability)
  2. POST to gateway's /tasks/{id}/final endpoint (for status reporting)

  This would be configured in the Crossplane composition — when the transport is SQS, the composition creates the EventBridge Pipe alongside the DLQ queue. The user gets it for free.

  Tier 2: Universal fallback (for RabbitMQ, NATS, bare metal)

  For transports without managed pipes, Asya provides the thin Go binary (_dlq worker). It's minimal, uses native transport SDKs (not asya's transport abstraction), and does only: poll →
  parse ID → POST to gateway → forward to _sink queue.

  Tier 3: Serverless override (optional)

  For users who want Lambda/Cloud Function instead of the Go binary, Asya provides reference implementations they can deploy.

  The Tier 1 approach is the enterprise-grade answer to your question — it's not a "custom DLQ handler," it's a platform-native pipe. EventBridge Pipes, Kafka Connect, and Pub/Sub
  subscriptions are battle-tested infrastructure with SLAs. The thin Go binary is only for transports that don't have this.
