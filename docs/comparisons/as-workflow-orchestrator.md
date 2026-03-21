# 🎭 Asya vs Workflow Orchestrators

**Temporal, Argo Workflows, Apache Airflow, Prefect, Dagster**

## TL;DR

Temporal, Argo Workflows, Airflow, Prefect, and Dagster are centralized orchestrators --
a coordinator schedules and monitors every step. Asya is a decentralized actor mesh where
stateless handlers communicate through durable message queues and each message carries its
own route. This gives Asya per-actor independent scaling (including to zero), fault
isolation per step, and zero SDK lock-in -- at the cost of requiring Kubernetes.

## Comparison Table

| Dimension | 🎭 | Temporal | Argo Workflows | Apache Airflow | Prefect | Dagster |
|---|---|---|---|---|---|---|
| **Execution model** | Choreography: message carries the route | Orchestration: server replays deterministic workflows | Orchestration: K8s-native DAG of containers | Orchestration: scheduler executes DAG of tasks | Orchestration: hybrid (server + agent workers) | Orchestration: scheduler executes asset/op graphs |
| **Scaling** | Per-actor via KEDA (0-N pods each) | Per-task-queue worker pools | Per-step pod (one pod per step) | Celery/K8s workers, shared pool | Work pools with auto-scaling | Per-run via run launchers |
| **Scale to zero** | 🟢 KEDA-driven per actor | 🔴 Workers must poll continuously | 🟢 Pods terminate after step | 🔴 Scheduler + workers always running | 🔴 Agent must stay running | 🔴 Daemon + webserver always running |
| **Failure isolation** | 🟢 Per actor (queue buffers on crash) | 🟡 Per worker (all its workflows affected) | 🟢 Per step (each step is a pod) | 🔴 Shared worker pool | 🟡 Per work pool | 🟡 Per run launcher |
| **SDK lock-in** | ✅ None -- plain `dict -> dict` | 🔴 Required (decorators, determinism constraints) | ✅ None -- any container image | 🔴 Required (`@task`, `@dag` decorators, Operators) | 🔴 Required (`@task`, `@flow` decorators) | 🔴 Required (`@asset`, `@op` decorators) |
| **Polyglot** | 🟢 Any language in container | 🟢 Go, Java, Python, TS, .NET SDKs | 🟢 Any container image | 🟡 Python-only (operators wrap other languages) | 🟡 Python-only | 🟡 Python-only |
| **Conceptual simplicity** | One abstraction: actor | Workflows, activities, workers, task queues, signals | Templates, steps, DAGs, artifacts | DAGs, operators, sensors, hooks, connections | Flows, tasks, work pools, deployments | Assets, ops, jobs, resources, I/O managers |
| **State management** | Stateless handlers; state travels in the envelope | Event-sourced replay (deterministic) | Artifacts passed between pods | XComs (serialized, size-limited) | Task results (serialized) | I/O managers (typed, partitioned) |
| **Dynamic routing** | 🟢 Actors rewrite `route.next` at runtime | 🟢 Workflow conditionals + signals | 🟡 DAG conditionals (limited runtime changes) | 🟡 BranchPythonOperator (static DAG structure) | 🟢 Runtime conditionals in flow code | 🟡 Dynamic partitions (not arbitrary routing) |
| **K8s native** | 🟢 CRD + Crossplane + KEDA + GitOps | 🔴 Runs on K8s but no CRDs | 🟢 CRD-based, K8s-native | 🔴 Deployed on K8s, not K8s-native | 🔴 Deployed on K8s, not K8s-native | 🔴 Deployed on K8s, not K8s-native |
| **AI/ML focus** | 🟢 Built for heterogeneous GPU/CPU pipelines | 🔴 General-purpose workflow engine | 🟡 Used for ML, not purpose-built | 🟡 Data engineering focus, ML via providers | 🟡 General-purpose, ML via integrations | 🟢 Asset-oriented data + ML lineage |
| **Handler UX** | `def handle(payload: dict) -> dict` | `@activity.defn` + `@workflow.defn` | Dockerfile + entrypoint | `@task` + Operator subclass | `@task` + `@flow` | `@asset` + `@op` |

## Key Differences

### Choreography vs centralized orchestration

Every orchestrator in this comparison runs a central scheduler or server that decides what
executes next. Temporal replays workflow history. Airflow's scheduler triggers tasks. Argo
submits pods according to a DAG spec. If the coordinator goes down, all pipelines stall.

Asya has no coordinator. Each envelope carries its own route (`prev/curr/next`), and each
actor forwards the result to the next queue. A crashed actor affects only its own queue --
messages accumulate until replicas recover, while other actors continue independently.
Global visibility requires aggregating per-actor metrics rather than querying a scheduler.

### Per-actor scale-to-zero

Airflow, Prefect, and Dagster require always-on scheduler/daemon processes. Temporal
workers must poll continuously. Even Argo, which runs each step as a pod, keeps the
workflow controller running permanently.

Asya scales each actor independently via KEDA based on queue depth -- including down to
zero pods. A GPU inference actor on A100s costs nothing between batches. When traffic
arrives, KEDA spins up pods in seconds -- particularly cost-effective for bursty AI/ML
workloads where idle GPU time dominates cost.

### No SDK, no determinism constraints

Temporal requires workflow code to be deterministic -- no random calls, no direct I/O, no
non-deterministic library usage. Airflow, Prefect, and Dagster require decorators and
framework-specific constructs. Argo is the exception: any container image works.

Asya handlers are plain Python functions with a `dict -> dict` signature:

```python
def score_image(payload: dict) -> dict:
    payload["score"] = model.predict(payload["image_url"])
    return payload
```

No decorators, no base classes, no determinism rules. Retry policies, timeouts, and
scaling live in the AsyncActor manifest:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: score-image
spec:
  image: scoring:latest
  handler: handler.score_image
  scaling:
    minReplicaCount: 0
    maxReplicaCount: 10
  resiliency:
    actorTimeout: 120s
    policies:
      default:
        maxAttempts: 3
        backoff: exponential
        initialInterval: 2s
        maxInterval: 30s
```

### Dynamic routing at runtime

Airflow and Dagster define DAG structure at parse time -- the graph is static. Prefect
allows runtime conditionals but within a single flow execution. Temporal supports dynamic
branching through workflow code but requires deterministic replay.

Asya actors can rewrite the message route at runtime. An LLM judge can route
high-confidence results directly to storage and low-confidence results to human review:

```python
def judge(payload: dict):
    if payload["confidence"] > 0.9:
        yield "SET", ".route.next", ["store"]
    else:
        yield "SET", ".route.next", ["human-review"]
    yield payload
```

The route is data, not code structure. No DAG rebuild, no redeployment.

## When to Use What

**Use 🎭 Asya when:**

- You run on Kubernetes and need per-step independent scaling with scale-to-zero
- GPU and CPU steps must scale on different hardware profiles independently
- Multiple teams own different pipeline steps and deploy independently
- Workloads are bursty or latency-tolerant (seconds to minutes per step)
- You want zero SDK lock-in -- plain Python functions, no framework imports

**Use Temporal when:**

- You need exactly-once semantics and durable execution guarantees
- Complex state machines with compensation (sagas) span days or weeks
- Timer-based scheduling (cron, durable timers) is a first-class requirement
- Multi-language orchestration across Go, Java, Python, and TypeScript matters
- You need a mature Web UI with searchable execution history out of the box

**Use Argo Workflows when:**

- You need K8s-native DAG execution with per-step container isolation
- CI/CD pipelines or batch jobs are the primary use case
- Polyglot steps (any container image) with artifact passing between pods
- You already run Argo CD and want a unified Argo ecosystem

**Use Apache Airflow when:**

- Data engineering pipelines with scheduled batch processing (ETL/ELT)
- You need 1000+ community-maintained operators and provider integrations
- The team knows Airflow and the workload is primarily scheduled DAGs

**Use Prefect when:**

- You want Python-native workflow orchestration with minimal boilerplate
- Hybrid execution (cloud-managed + self-hosted workers) fits your model
- Dynamic, parameterized flows with runtime branching are common

**Use Dagster when:**

- Data assets and lineage tracking are central to your architecture
- Software-defined assets align with how your team thinks about data pipelines
