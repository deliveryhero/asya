# ML Pipeline Tools

**Kubeflow Pipelines, Flyte, Metaflow, ZenML**

## TL;DR

Kubeflow Pipelines, Flyte, Metaflow, and ZenML are **training-centric pipeline
orchestrators** with experiment tracking, artifact lineage, and managed
execution. Asya is a **runtime-centric actor mesh** for serving, inference, and
agentic workloads where independent scaling, scale-to-zero, and dynamic routing
matter more than experiment management. If you need to track 500 hyperparameter
sweeps, use KFP or Flyte. If you need 50 actors scaling independently on mixed
GPU/CPU hardware with zero SDK lock-in, use 🎭 Asya.

## Comparison Table

| Dimension | 🎭 | KFP | Flyte | Metaflow | ZenML |
|---|---|---|---|---|---|
| **Execution model** | Choreography: envelope carries the route | Orchestration: Argo Workflows executes DAG | Orchestration: FlytePropeller schedules pods | Orchestration: local or AWS Step Functions | Orchestration: pluggable orchestrator backend |
| **Scaling** | Per-actor via KEDA (queue depth) | Per-step pod; no autoscaling within a step | Per-task pod; resource quotas | AWS Batch / K8s jobs | Delegated to orchestrator |
| **Scale to zero** | 🟢 Native (KEDA 0-N) | 🔴 Pipeline pods run to completion | 🔴 Pods run to completion | 🔴 Pods/Batch jobs run to completion | 🔴 Depends on orchestrator |
| **Failure isolation** | Per-actor: crashed actor affects only its queue | Per-step: failed step retries or fails the DAG | Per-task: retries at task level | Per-step: retry decorators | Per-step: retry at step level |
| **SDK lock-in** | ✅ None (`dict -> dict`) | 🔴 `@component`, `@pipeline` decorators, KFP SDK | 🔴 `@task`, `@workflow` decorators, Flytekit | 🔴 `@step`, `@flow` decorators, Metaflow SDK | 🔴 `@step`, `@pipeline` decorators, ZenML SDK |
| **Conceptual simplicity** | One abstraction: actor | Components, pipelines, runs, experiments | Tasks, workflows, launch plans, domains | Steps, flows, runs, namespaces | Steps, pipelines, stacks, components |
| **DAG definition** | Envelope route or Flow DSL (Python) | Python DSL compiled to Argo YAML | Python DSL compiled to Flyte CRDs | Python decorators with `self.next()` | Python decorators with pipeline graph |
| **Dynamic routing** | 🟢 Actors rewrite `route.next` at runtime | 🔴 DAG is static after compilation | 🟡 Dynamic workflows possible but complex | 🔴 DAG is static | 🔴 DAG is static after compilation |
| **K8s native** | 🟢 CRD + Crossplane + Helm | 🟢 Runs on K8s (Argo Workflows) | 🟢 Runs on K8s (FlytePropeller) | 🟡 K8s optional (prefers AWS) | 🟡 K8s is one of many backends |
| **GPU support** | Per-actor resource specs, independent GPU scaling | Per-component resource specs | Per-task resource specs, GPU quotas | `@resources(gpu=1)` decorator | Via orchestrator resource config |
| **Experiment tracking** | 🔴 Not a goal | 🟢 Native (runs, metrics, artifacts) | 🟢 Native (FlyteDecks, artifact lineage) | 🟢 Native (cards, metadata, tags) | 🟢 Native (experiment tracker component) |
| **Handler UX** | Plain function, no imports | SDK decorators + typed I/O artifacts | SDK decorators + Flyte types | SDK decorators + data artifacts | SDK decorators + materializers |

## Key Differences

### Pipeline orchestrators manage DAG execution; 🎭 Asya manages actor lifecycles

KFP, Flyte, Metaflow, and ZenML compile a Python DAG into a plan, then a central
controller executes it step by step. Each step is a short-lived pod (or Batch
job) that runs once and exits. The controller tracks which steps completed, which
failed, and what artifacts were produced.

🎭 Asya deploys long-lived actor pods that continuously pull from their queues.
There is no central controller -- each envelope carries its own route. Actors
scale independently based on queue depth, and KEDA scales them to zero when idle.

```
KFP/Flyte:    Controller -> spawn Pod A -> wait -> spawn Pod B -> wait -> done
Asya:         Actor A (always running, 0-N pods) -> queue -> Actor B (0-N pods)
```

### SDK decorators vs plain functions

Every ML pipeline framework requires SDK decorators on your functions:

```python
# KFP
@component
def score(data: Input[Dataset]) -> Output[Metrics]:
    ...

# Flyte
@task
def score(data: FlyteFile) -> float:
    ...

# Metaflow
class ScoreFlow(FlowSpec):
    @step
    def score(self):
        ...

# ZenML
@step
def score(data: pd.DataFrame) -> float:
    ...
```

🎭 Asya handlers are plain Python:

```python
def score(payload: dict) -> dict:
    payload["score"] = model.evaluate(payload["input"])
    return payload
```

No SDK import. Unit-test with `assert score({"input": x}) == {"score": y}`.

### Static DAGs vs dynamic routing

ML pipeline frameworks compile the DAG before execution. Conditional branches
exist (KFP's `dsl.Condition`, Flyte's `conditional`) but the set of possible
paths is fixed at compile time.

🎭 Asya actors can rewrite the route at runtime:

```python
def llm_judge(payload: dict) -> dict:
    confidence = evaluate(payload)
    if confidence > 0.9:
        yield "SET", ".route.next", ["store"]
    else:
        yield "SET", ".route.next", ["human_review"]
    yield payload
```

The decision happens live, based on the actual data -- not a pre-compiled
branch.

### Experiment tracking is not 🎭 Asya's job

KFP, Flyte, Metaflow, and ZenML all provide experiment tracking: comparing runs,
visualizing metrics, browsing artifact lineage. This is essential for ML training
workflows where you iterate on hyperparameters and need to reproduce results.

🎭 Asya does not track experiments. It is a runtime execution layer. Pair it with
MLflow, Weights & Biases, or your framework's tracker for experiment management.

## When to Use What

### Use KFP or Flyte when

- You run **training pipelines** that produce model artifacts, metrics, and need
  lineage tracking across hundreds of experiment runs
- You want a **managed DAG executor** with built-in retry, caching, and artifact
  versioning on Kubernetes
- Your pipeline steps are **batch jobs** (run once, produce output, exit) rather
  than long-running services
- You need **Vertex AI** (KFP) or **Union.ai** (Flyte) managed service

### Use Metaflow or ZenML when

- You want **cloud-agnostic** pipeline orchestration that works across AWS, GCP,
  and Azure without deep K8s knowledge
- Your team is **data-science-first** and wants a Python-native experience with
  minimal infrastructure exposure
- You need built-in **experiment tracking and artifact management** without
  running separate infrastructure (MLflow, W&B)

### Use 🎭 Asya when

- You run **inference and serving pipelines** where actors process messages
  continuously (not batch jobs that exit)
- You need **independent per-actor scaling** -- GPU actors scale 0-5 while CPU
  actors scale 0-50, each driven by its own queue depth
- **Scale-to-zero** matters -- GPU pods cost nothing when queues are empty
- You want **zero SDK lock-in** -- handlers are plain Python, portable anywhere
- You need **dynamic routing** -- actors decide the next step based on the actual
  data, not a pre-compiled DAG
- You are building **agentic workflows** with pause/resume, human-in-the-loop,
  A2A/MCP integration, and streaming
- Your organization has a **platform team / data science split** where
  infrastructure configuration (retries, scaling, transport) is owned separately
  from business logic
