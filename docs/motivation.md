# Why Asya: REST in Peace, AI Needs to Be Async

## The Nightmare at Scale

Your AI pipeline runs fine in staging. In production, at peak load, a slow LLM call holds a connection open. The client retries with exponential backoff. Other clients do the same. The server queues up, hits memory limits, and starts dropping requests. A single slow component stalls everything downstream.

This is the synchronous trap: **request/response requires someone to hold state and wait**. In AI workloads — where individual steps take milliseconds to minutes, traffic is unpredictably bursty, and components run on different hardware — waiting is expensive and fragile.

Traditional orchestrators (Airflow, Prefect, Kubeflow Pipelines) invert the problem by introducing a central coordinator. Now you have a new single point of failure, and all components must scale together even when only one is bottlenecked.

## The Insight: The Message Knows the Way

Asya's core idea is to remove the coordinator entirely. Instead of a controller routing messages between actors, **each message carries its own route**:

```json
{
  "id": "env-123",
  "route": { "prev": ["preprocess"], "curr": "infer", "next": ["postprocess"] },
  "payload": { "text": "..." }
}
```

When `infer` finishes, the sidecar reads `route.next`, sends the envelope to `postprocess`, and `infer` is done. No callback, no polling, no coordinator. The message knows where to go next.

This is choreography over orchestration. The failure domain of each actor is exactly one queue. A crashed actor doesn't stall others — messages accumulate until replicas come back. Each actor scales based purely on its own queue depth.

![Asya actor mesh](website/img/actor-mesh.png)

## What Asya Is

Asya is a Kubernetes-native actor mesh framework. You write pure Python functions. Asya handles queue creation, sidecar injection, autoscaling via KEDA, and message routing. The only interface between your code and the framework is the envelope payload — a plain Python dict in, a plain Python dict out.

It is **not** a model serving platform, a training framework, a CI/CD system, or a managed cloud service. It is the async messaging layer that connects your AI components without coupling them.

## When to Use Asya

✅ **Multi-step AI/ML pipelines** where individual steps have different latencies, hardware, and scaling needs (OCR → classification → LLM → storage)

✅ **Bursty or unpredictable workloads** that benefit from scale-to-zero — GPU pods that cost nothing when idle

✅ **Agentic workflows** with dynamic routing: LLM judge loops, human-in-the-loop pause/resume, parallel fan-out

✅ **Kubernetes-native teams** that want infrastructure declared as CRDs alongside application workloads

## When Not to Use Asya

❌ **Sub-100ms latency requirements** — queue overhead adds ~10–500ms; use KServe or BentoML for synchronous model serving

❌ **Single-step processing** — a standalone REST endpoint doesn't need a message bus

❌ **Training jobs** — use Kubeflow, Ray Train, or native Kubernetes Jobs instead

## How Asya Compares

| | Asya | Airflow / Prefect | Dapr |
|---|---|---|---|
| Coordination model | Choreography (no center) | Centralized DAG executor | Sidecar + actor runtime |
| AI/ML focus | ✅ First-class (scaling, GPU, agentic) | ❌ General ETL | ❌ General microservices |
| Scale to zero | ✅ KEDA per-actor | ❌ Workers always running | ❌ Not built-in |
| Handler interface | Pure Python `dict → dict` | Decorated tasks (`@task`) | Language-specific SDK |
| Failure isolation | Per-actor queue | Central orchestrator stalls | Per-service |

Asya integrates with LLM serving tools (KAITO, LLM-d) via HTTP calls from actors — it is the pipeline
layer around them, not a replacement.

## Choreography vs Orchestration: The Trade-offs

Choreography is not universally better than orchestration. The choice depends on the workload.

### Complexity Comparison

| Concern | Orchestration | Choreography (Asya) |
|---------|--------------|---------------------|
| Adding a new step | Change the orchestrator's DAG definition | Deploy a new actor; update the route in the envelope or flow config |
| Debugging a failure | Read the orchestrator's execution log | Trace the envelope by `trace_id` across actor logs |
| Scaling a bottleneck | Scale the orchestrator + the bottleneck worker | Scale only the bottleneck actor (independent KEDA trigger) |
| Handling a crash | Orchestrator must checkpoint and resume | Queue redelivers the message; actor is stateless |
| Global visibility | Orchestrator has a complete view of all workflows | Aggregate from per-actor metrics and logs |

### Where orchestration might be better

- **Simple workflows** with 2-3 steps that rarely change — the overhead of queues and sidecars is not justified
- **Strong consistency requirements** where you need exactly-once semantics and transactional guarantees across steps
- **Tight request-response latency** under 100ms — queue overhead adds 10-500ms per hop
- **Small-scale deployments** that do not need per-component scaling

### The debuggability question

A common concern with choreography is debuggability. Asya addresses this with:

1. **Envelope IDs and trace IDs** propagated through all actors
2. **Progress reporting** from sidecars to the gateway at three points per actor
3. **Prometheus metrics** for per-actor throughput, latency, and error rates
4. **x-sink / x-sump** — all envelopes end at one of two known destinations

The trade-off is real: you lose the single-pane-of-glass that an orchestrator provides. You gain independent failure domains and scaling.
