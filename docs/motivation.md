# Motivation

## The Problem

AI/ML teams building production pipelines face fundamental architectural challenges:

| Challenge | Why It Matters |
|-----------|----------------|
| **Logic Entanglement** | Pipeline orchestration (`if/else`, retries, error handling) mixed with business logic (AI/ML inference, data processing, API calls, decision making). Frameworks require code instrumentation (`@flow`, `@step` decorators). Impossible to test components independently. |
| **Scaling Limitations** | All components scale together, wasting resources. GPU pods sit idle 80% of the time but still cost $1000s/month. Cannot independently deploy or scale different pipeline stages. |
| **Infrastructure Complexity** | Data scientists manage infrastructure code alongside ML code. Platform engineers struggle to operate heterogeneous deployment patterns at scale. Batch vs streaming requires completely different frameworks. |
| **Vendor Lock-in** | API rate limits throttle throughput. Model changes break pipelines. Costs scale unpredictably. |

**Core issue**: Traditional approaches treat AI workloads as HTTP services when they're actually **batch processing jobs** that need queue-based semantics.

This coupling is obvious for backend engineers to avoid, but unnatural for data science workflows.

<table style="table-layout: fixed; width: 100%; border-collapse: collapse;">
<tr>
<td style="width: 50%; padding: 10px; border: none; vertical-align: top;">
<div style="width: 100%;">
<img src="../img/async-request-response.png" alt="Traditional async request-response pattern" style="width: 100%; max-width: 100%; height: auto; display: block;"/>
<p style="margin-top: 10px; word-wrap: break-word; white-space: normal; overflow-wrap: break-word;">
<em>❌ Traditional request-response pattern: Clients orchestrate workflows, hold state in memory, get stuck on failures. Servers scale independently but clients waste resources waiting.</em>
</p>
</div>
</td>
<td style="width: 50%; padding: 10px; border: none; vertical-align: top;">
<div style="width: 100%;">
<img src="../img/async-actors.png" alt="Asya🎭 async actor pattern" style="width: 100%; max-width: 100%; height: auto; display: block;"/>
<p style="margin-top: 10px; word-wrap: break-word; white-space: normal; overflow-wrap: break-word;">
<em>✅ Asya🎭 pattern: Actors scale independently based on queue depth. Messages flow through pipeline. Errors route to DLQ. No client orchestration - framework handles everything.</em>
</p>
</div>
</td>
</tr>
</table>


## What is Asya🎭?

Asya🎭 is a Kubernetes-native async actor framework for orchestrating complex near-realtime AI pipelines at scale.

**Core principle**: Decouple pipeline logic, infrastructure logic, and component logic.

- Each component is an **independent actor**
- Each actor has a **sidecar** (routing logic) + **runtime** (user code)
- Zero pip dependencies - radically simple interface for data scientists
- Actors communicate via **async message passing** (pluggable transports: SQS, RabbitMQ)
- Pipeline structure is **data, not code** - indirectly defined by each message
- Built-in observability, reliability, extensibility, scalability
- Optional **MCP HTTP gateway** for easy integration

## When to Use Asya🎭

### Good Fit

✅ **Kubernetes-native deployments**
- Already running on K8s or planning to migrate

✅ **Near-realtime data processing**
- Latency requirements: seconds to minutes per component
- Total pipeline: tens or hundreds of components with very different latencies (ms to minutes each)

✅ **Mixed workload types**
- Self-hosted AI components (LLMs, vision models)
- Data processing components
- Backend engineering components

✅ **Bursty workloads**
- Unpredictable traffic patterns
- Need cost optimization through scale-to-zero
- GPU-intensive tasks requiring independent scaling

✅ **Resilient processing**
- Automatic retries, dead-letter queues
- Built-in error handling

✅ **Easy integration**
- Configurable MCP Gateway for HTTP API access out of the box

### Not Good Fit

❌ **Synchronous request-response APIs**
- Use HTTP services (KServe, Seldon, BentoML) instead

❌ **Sub-second latency requirements**
- Queue overhead adds ~10-500ms
- Scale-to-zero inevitably brings delays due to pod startup time (we're working on minimizing it)

❌ **Simple single-step processing**
- Operational complexity overhead may not be worth it

❌ **Stateful workflows requiring session affinity**
- Actors shine when they are stateless


## Problems Asya🎭 Solves

### No Single Point of Failure
- Fully distributed architecture
- No central orchestrator/DAG/flow
- Messages carry their own routes

### Separation of Concerns
- **Pipeline structure**: Pipeline is **data, not code** (no `@flow` decorators)
- **Infrastructure layer**: K8s-native, zero infra management for DS
- **Component logic**: Fully controlled by DS

### Scalability
- Each component independently scalable based on queue depth or custom metrics
- Scale to zero prevents wasted GPU costs
- KEDA-based autoscaling

### Extensibility
- Pluggable transports (SQS, RabbitMQ, Kafka planned)
- Easy integration with open-source tools

### Observability
- Built-in metrics for actors, sidecars, runtimes, operator, gateway
- OpenTelemetry integration

### Reliability
- Built-in retries, DLQs, error handling
- At-least-once delivery guarantees

### Usability
- Zero infrastructure management for DS
- Easy for platform engineers to operate at scale (K8s-native)

## Problems Asya🎭 Does NOT Solve

- **Pre-defined AI components**: Asya doesn't provide inference runtimes - integrate with existing ones (KAITO, LLM-d)
- **CI/CD**: Bring your own deployment pipeline
- **Data storage**: Bring your own databases, object stores
- **Data processing frameworks**: DS build their own runtimes
- **Synchronous HTTP APIs**: Cannot compete with ms-latency LLM deployments due to queue overhead
- **Managed service**: Bring your own K8s cluster

## Existing Solutions Comparison

### Workflow Orchestrators (Airflow, Prefect, Dagster, Kubeflow Pipelines, Temporal)
- Monolithic orchestrators with central DAG/flow definition
- Not truly async - state held in orchestrator
- Hard to scale different components independently
- Hard to deploy components independently

### Actor Frameworks (Dapr)
- K8s-native async actor framework
- Not designed for data science workloads
- Lacks built-in AI orchestration features (observability, reliability, autoscaling)

### Custom K8s Solutions
- Require significant engineering effort to build and maintain
- Lack standardized patterns for AI orchestration

### LLM Deployment Tools (KAITO, LLM-d)
- Perfect for deploying LLMs as REST APIs
- Asya integrates with these via HTTP calls from actors

## Key Insight

Traditional architectures treat AI workloads as HTTP services. AI workloads are actually **batch processing jobs** with unique requirements:

- Expensive GPU compute sitting idle
- Mixed latencies (10ms preprocessing + 30s inference)
- Bursty traffic patterns (10x spikes during business hours)
- Multi-step dependencies needing orchestration

Therefore, the best way to operate such systems is asynchronously, which might be tricky to implement.

**Async actors invert control**: Messages carry routes (not clients orchestrating). Actors scale based on available work (not always-on servers).
