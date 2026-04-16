---
description: "Deep comparison: Asya vs Temporal — centralized replay vs decentralized queue-based routing"
---

# vs Temporal

## TL;DR

Temporal is a centralized workflow engine that replays deterministic functions to
recover state. Asya is a decentralized actor mesh where stateless handlers
communicate through durable message queues. Temporal gives you exactly-once
semantics and complex state machines; Asya gives you independent per-actor
scaling, scale-to-zero, and zero SDK lock-in.

## At a Glance

| | 🎭 | Temporal |
|---|---|---|
| **One-liner** | Actor mesh on Kubernetes | Durable execution engine |
| **Execution model** | Choreography: message carries the route | Orchestration: server replays workflow history |
| **Handler UX** | Pure `dict -> dict` Python function | SDK-wrapped activity/workflow with decorators |
| **Scaling** | Per-actor via KEDA (queue depth) | Per-task-queue worker pools |
| **Scale to zero** | 🟢 Native (KEDA scales pods 0-N) | 🔴 Workers must stay running to poll |
| **Failure isolation** | ✅ Per-actor: crashed actor affects only its queue | ⚠️ Per-worker: crashed worker affects all its workflows |
| **State management** | Stateless handlers; state travels in the envelope | Workflow state rebuilt via event-sourced replay |
| **K8s native** | 🟢 CRDs, Helm, Crossplane, GitOps | 🟡 Runs on K8s but not K8s-native (no CRDs) |
| **Conceptual simplicity** | One abstraction: actor | Workflows, activities, workers, task queues, signals, queries |
| **Dynamic routing** | ✅ Actors rewrite `route.next` at runtime | ✅ Workflow code uses conditionals and signals |
| **SDK requirement** | ✅ None (plain Python functions) | 🔴 Required (Go, Java, Python, TypeScript, .NET) |
| **Transport** | SQS, RabbitMQ, GCP Pub/Sub | Temporal Server (Cassandra/MySQL/PostgreSQL) |
| **Agentic support** | ✅ A2A, MCP, pause/resume, streaming | ⚠️ Via workflow signals and queries |
| **Maturity** | 🟡 Alpha (production at Delivery Hero) | 🟢 Mature (GA since 2020, thousands of production users) |

## Architecture Comparison

### Temporal

Temporal runs a **server cluster** (frontend, history, matching, worker services)
backed by Cassandra or a SQL database. Application code is split into
**workflows** (deterministic orchestration logic) and **activities** (side
effects). **Workers** are long-running processes that poll task queues. When a
worker crashes, Temporal replays the workflow's event history on a new worker --
this requires workflow code to be **deterministic** (no random, no direct I/O).

### Asya

Each step is an independent **actor pod** on Kubernetes. A Go sidecar handles
queue I/O, retries, and routing. The handler is a plain Python function. Messages
(envelopes) carry their own route -- no central coordinator needed. Each actor
scales independently via KEDA based on its own queue depth.

## Developer Experience

Consider a 3-step pipeline: validate input, call an LLM, store the result. Each
step retries up to 3 times with exponential backoff.

### Temporal

```python
# activities.py -- each step needs @activity.defn
@activity.defn
async def validate(data: dict) -> dict: ...

@activity.defn
async def call_llm(data: dict) -> dict: ...

@activity.defn
async def store_result(data: dict) -> dict: ...
```

```python
# workflow.py -- orchestration logic, must be deterministic
@workflow.defn
class PipelineWorkflow:
    @workflow.run
    async def run(self, data: dict) -> dict:
        retry = workflow.RetryPolicy(maximum_attempts=3,
            initial_interval=timedelta(seconds=1),
            maximum_interval=timedelta(seconds=60),
            backoff_coefficient=2.0)
        for act in [validate, call_llm, store_result]:
            data = await workflow.execute_activity(
                act, data,
                start_to_close_timeout=timedelta(seconds=300),
                retry_policy=retry)
        return data
```

```python
# worker.py -- long-running process that polls Temporal server
async def main():
    client = await Client.connect("temporal:7233")
    worker = Worker(client, task_queue="pipeline-queue",
        workflows=[PipelineWorkflow],
        activities=[validate, call_llm, store_result])
    await worker.run()
```

Three files, three concepts (activity, workflow, worker), SDK decorators
throughout, and a running Temporal server cluster.

### Asya 🎭

```python
# handler.py -- each actor gets one of these
def validate(state: dict) -> dict:
    return {**state, "validated": True}

def call_llm(state: dict) -> dict:
    state["response"] = model.generate(state["prompt"])
    return state

def store_result(state: dict) -> dict:
    db.save(state)
    return state
```

```yaml
# asyncactor.yaml -- one per actor, or use flavors for shared defaults
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: call-llm
spec:
  image: my-pipeline:latest
  handler: handler.call_llm
  scaling:
    minReplicaCount: 0
    maxReplicaCount: 10
  resiliency:
    actorTimeout: 300s
    policies:
      default:
        maxAttempts: 3
        backoff: exponential
        initialInterval: 1s
        maxInterval: 60s
```

Plain Python functions, no SDK, no decorators. Retry policies, timeouts, and
scaling live in the Kubernetes manifest, not in application code. The route
connecting the three actors is carried by the envelope itself.

## When to Choose Temporal

Temporal is a mature, battle-tested platform. It is the stronger choice when:

- **Complex state machines** -- workflows with branching, compensation (sagas),
  and long-running human approvals that span days or weeks. Temporal's replay
  model excels at resuming exactly where it left off.
- **Exactly-once semantics** -- Temporal's deterministic replay provides stronger
  delivery guarantees than at-least-once queue-based systems.
- **Timer-based scheduling** -- cron workflows, delayed execution, and durable
  timers are first-class features in Temporal.
- **Multi-language orchestration** -- Temporal has official SDKs for Go, Java,
  Python, TypeScript, and .NET, with consistent behavior across languages.
- **Mature observability** -- Temporal's Web UI provides workflow-level
  visibility, searchable execution history, and debugging tools out of the box.
- **Non-Kubernetes environments** -- Temporal runs anywhere; Asya requires
  Kubernetes.

## When to Choose Asya

Asya is purpose-built for AI/ML workloads on Kubernetes:

- **Heterogeneous hardware** -- GPU actors scale independently from CPU actors.
  An LLM inference actor on A100 GPUs scales 0-5 while a preprocessing actor on
  CPU scales 0-50, each based on its own queue depth.
- **Scale-to-zero** -- KEDA scales actor pods to zero when queues are empty. GPU
  pods cost nothing between batches. Temporal workers must stay running to poll.
- **No SDK lock-in** -- handlers are plain Python functions (`dict -> dict`). No
  decorators, no base classes, no determinism constraints. Swap the function,
  redeploy.
- **Simpler mental model** -- one abstraction (actor) instead of five (workflow,
  activity, worker, task queue, signal). Platform engineers own the YAML; data
  scientists own the Python function.
- **K8s-native operations** -- AsyncActor is a CRD. Deploy with `kubectl apply`,
  manage with Helm, integrate with GitOps. Crossplane compositions render the
  full pod spec including sidecars.
- **Dynamic routing** -- actors can rewrite the message route at runtime. An LLM
  judge can send high-confidence results to storage and low-confidence results to
  human review -- without rebuilding a DAG.
- **Agentic AI patterns** -- built-in A2A and MCP gateway, pause/resume for
  human-in-the-loop, FLY streaming for live token output.
