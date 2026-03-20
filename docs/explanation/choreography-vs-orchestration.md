<!-- Type: Explanation -->

# Why Choreography?

Asya uses choreography -- decentralized message passing -- instead of
centralized orchestration. This document explains the fundamental difference,
the trade-offs, and when each approach is appropriate.

## Two coordination models

### Orchestration: a central coordinator controls the flow

In an orchestrated system, a central component (the orchestrator) decides what
happens next. It calls services in sequence, handles branching, and manages
state. Frameworks like LangGraph, CrewAI, Airflow, and Prefect follow this
model.

```
Orchestrator
    |
    |---> Service A ---> result
    |---> Service B ---> result
    |---> Service C ---> result
    |
    v
  Done
```

The orchestrator holds the execution plan, tracks progress, and routes data
between steps. Every service reports back to the center.

### Choreography: each message carries its own route

In a choreographed system, there is no central coordinator. Each message knows
where it needs to go next. Components react to incoming messages and forward
results to the next destination.

```
Message: {route: [A, B, C], payload: {...}}

Queue A ---> Actor A ---> Queue B ---> Actor B ---> Queue C ---> Actor C ---> Done
```

The route is embedded in the message. When Actor A finishes, the sidecar reads
`route.next` and sends the envelope to Actor B. No coordinator is involved.

## Why Asya chose choreography

### Independent failure domains

In an orchestrated system, the orchestrator is a single point of failure. If
it crashes, all in-flight pipelines stall. Even if the orchestrator is
replicated, its state store (workflow state, step progress) must be consistent
and available -- a hard distributed systems problem.

In Asya, each actor's failure domain is exactly one queue. A crashed actor
does not stall other actors. Messages accumulate in the queue until replicas
recover. There is no central state to lose.

### Independent scaling

Each Asya actor scales based on its own queue depth via KEDA. A slow LLM
inference actor can run on 2 GPU pods while a fast preprocessor scales to 20
CPU pods. The scaling decisions are completely independent.

In orchestrated systems, scaling the orchestrator and the workers are coupled
concerns. The orchestrator must track all in-flight work, and its memory
footprint grows with concurrency.

### Queue-native resilience

Messages in Asya are durably queued (RabbitMQ, SQS). If an actor pod is
evicted, restarted, or OOM-killed, the message is NACK'd and redelivered.
The sidecar ACKs only after routing the result to the next queue. This gives
at-least-once delivery without custom retry logic in application code.

### Stateless actors, stateless infrastructure

Actors are pure functions: `dict -> dict`. They hold no state between
envelopes. This means actors can be Deployments (not StatefulSets), can scale
to zero, and can be replaced without draining. The envelope carries all
context needed for processing.

## Trade-offs

Choreography is not universally better than orchestration. The choice depends
on the workload.

### Where choreography shines

- **Multi-step AI/ML pipelines** with heterogeneous latencies and hardware
  (CPU preprocessing, GPU inference, CPU postprocessing)
- **Bursty workloads** that benefit from scale-to-zero and per-actor
  autoscaling
- **Agentic workflows** with dynamic routing: the actor itself decides where
  the envelope goes next via `yield "SET", ".route.next", [...]`
- **Kubernetes-native teams** that want infrastructure declared as CRDs
- **Long-running steps** where holding an HTTP connection open is expensive

### Where orchestration might be better

- **Simple workflows** with 2--3 steps that rarely change -- the overhead of
  queues and sidecars is not justified
- **Strong consistency requirements** where you need exactly-once semantics
  and transactional guarantees across steps
- **Tight request-response latency** under 100ms -- queue overhead adds
  10--500ms per hop
- **Small-scale deployments** that do not need per-component scaling and where
  a single process is sufficient

### Complexity comparison

| Concern | Orchestration | Choreography |
|---------|--------------|--------------|
| Adding a new step | Change the orchestrator's DAG definition | Deploy a new actor; update the route in the envelope or flow config |
| Debugging a failure | Read the orchestrator's execution log | Trace the envelope by `trace_id` across actor logs |
| Scaling a bottleneck | Scale the orchestrator + the bottleneck worker | Scale only the bottleneck actor (independent KEDA trigger) |
| Handling a crash | Orchestrator must checkpoint and resume | Queue redelivers the message; actor is stateless |
| Global visibility | Orchestrator has a complete view of all workflows | Must aggregate from per-actor metrics and logs |

### The debuggability question

A common concern with choreography is debuggability: without a central
orchestrator log, how do you trace a request?

Asya addresses this with:

1. **Envelope IDs and trace IDs**: every envelope carries `id` and
   `headers.trace_id` through all actors
2. **Progress reporting**: sidecars report progress to the gateway at three
   points per actor (received, processing, completed)
3. **Prometheus metrics**: per-actor throughput, latency, and error rates
4. **x-sink / x-sump**: all envelopes end at one of two known destinations --
   successful completions in x-sink, errors in x-sump

The trade-off is real: you lose the single-pane-of-glass that an orchestrator
provides. You gain independent failure domains and scaling.

## Further reading

- [Why Asya](../motivation.md) -- positioning and comparison with alternatives
- [Core Concepts](../concepts.md) -- envelope, actor, sidecar, crew
- [How to Debug an Envelope](../howto/debug-envelope.md) -- practical
  debugging steps for the choreography model
