---
description: "Deep comparison: Asya vs Kubeflow Pipelines — Argo DAGs vs actor mesh for ML pipelines"
---

# vs Kubeflow Pipelines

## TL;DR

Kubeflow Pipelines (KFP) compiles Python-decorated functions into an Argo
Workflows DAG where each step runs as a separate container in a new pod. Asya
runs each step as a long-lived actor pod pulling from its own message queue.
KFP gives you ML-optimized artifact tracking, experiment management, and
notebook-friendly UX; Asya gives you independent per-step scaling, scale-to-zero
between runs, dynamic routing, and zero SDK lock-in.

## At a Glance

| | 🎭 | Kubeflow Pipelines v2 |
|---|---|---|
| **One-liner** | Actor mesh on Kubernetes | ML pipeline platform on Argo Workflows |
| **Execution model** | Choreography: envelope carries the route | Orchestration: Argo controller executes a DAG |
| **Step isolation** | Long-lived pod per actor, scales 0-N | New pod per step per run, destroyed after |
| **Handler UX** | Plain `dict -> dict` function | `@dsl.component` decorator, typed I/O |
| **Scaling** | Per-actor via KEDA (queue depth) | Per-pipeline via Argo parallelism limits |
| **Scale to zero** | 🟢 Native (KEDA scales pods 0-N) | 🔴 Pod-per-step: cold start every run |
| **GPU cost** | Pay only while queue has messages | Pay per-run pod lifetime (cold start + execution) |
| **Artifact tracking** | ❌ External (user brings their own) | ✅ Built-in ML Metadata store |
| **Experiment management** | ❌ External | ✅ Built-in (runs, experiments, metrics) |
| **Dynamic routing** | ✅ Actors rewrite `route.next` at runtime | ❌ Static DAG, compiled before execution |
| **SDK requirement** | ✅ None (plain Python functions) | 🔴 Required (`kfp` SDK, decorators, type hints) |
| **Transport** | SQS, RabbitMQ, GCP Pub/Sub | Argo Workflows (etcd-backed) |
| **Agentic support** | ✅ A2A, MCP, pause/resume, streaming | ❌ Not designed for agentic workloads |
| **K8s native** | 🟢 CRD (`AsyncActor`), Helm, Crossplane | 🟢 CRDs (Argo Workflow, Pipeline, Run) |
| **Maturity** | 🟡 Alpha (production at Delivery Hero) | 🟢 Mature (KFP v2, CNCF project) |

## Architecture

### Kubeflow Pipelines

KFP v2 compiles a Python pipeline into an **Argo Workflow** DAG where each node
is a pod. The **KFP API server** manages pipeline versions, runs, and
experiments. **ML Metadata** tracks artifacts across runs. Each run creates a
fresh set of pods; when a step finishes, its pod terminates.

This pod-per-step-per-run model means every invocation pays the full cold start
cost: image pull, container init, Python import, model loading. For GPU steps
that load multi-GB models, this cost dominates execution time.

### Asya

Each step is a **long-lived actor pod** on Kubernetes. A Go sidecar handles
queue I/O, retries, and routing. Messages (envelopes) carry their own route --
no central controller needed. KEDA scales each actor independently based on its
queue depth, including down to zero when idle.

When work arrives, the actor pod is already warm (or KEDA spins one up) and
processes messages continuously. No cold start per invocation.

## Developer Experience

Consider an ML pipeline: preprocess, run GPU inference, evaluate results.

### Kubeflow Pipelines

```python
from kfp import dsl
from kfp.dsl import Input, Output, Dataset, Model, Metrics

@dsl.component(base_image="python:3.11", packages_to_install=["pandas"])
def preprocess(raw_data: Input[Dataset], processed: Output[Dataset]):
    import pandas as pd
    df = pd.read_csv(raw_data.path)
    df = df.dropna().reset_index(drop=True)
    df.to_parquet(processed.path)

@dsl.component(base_image="nvcr.io/nvidia/pytorch:24.01-py3")
def inference(data: Input[Dataset], model_out: Output[Model]):
    import torch
    model = torch.load("/models/classifier.pt")  # loaded every run
    # ... run inference, save results
    torch.save(results, model_out.path)

@dsl.component(base_image="python:3.11")
def evaluate(predictions: Input[Model], metrics: Output[Metrics]):
    # ... compute accuracy, F1
    metrics.log_metric("accuracy", 0.95)

@dsl.pipeline(name="ml-pipeline")
def ml_pipeline():
    prep = preprocess(raw_data=dsl.Input())
    inf = inference(data=prep.outputs["processed"])
    evaluate(predictions=inf.outputs["model_out"])
```

Each run creates 3 new pods, each pulling its base image, installing packages,
and loading models from scratch.

### Asya

```python
# preprocess/handler.py
def preprocess(payload: dict) -> dict:
    import pandas as pd
    df = pd.read_csv(payload["raw_data_path"])
    df = df.dropna().reset_index(drop=True)
    out_path = f"s3://data/{payload['run_id']}/processed.parquet"
    df.to_parquet(out_path)
    payload["processed_path"] = out_path
    return payload

# inference/handler.py -- model loaded once at import time
import torch
model = torch.load("/models/classifier.pt")

def inference(payload: dict) -> dict:
    results = model(payload["processed_path"])
    payload["predictions"] = results
    return payload

# evaluate/handler.py
def evaluate(payload: dict) -> dict:
    payload["accuracy"] = compute_accuracy(payload["predictions"])
    return payload
```

```yaml
# asyncactor.yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: inference
spec:
  image: my-inference:latest
  handler: handler.inference
  scaling:
    minReplicaCount: 0
    maxReplicaCount: 10
    queueLength: 1
  resiliency:
    actorTimeout: 600s
    policies:
      default:
        maxAttempts: 3
        backoff: exponential
        initialInterval: 2s
        maxInterval: 120s
  resources:
    limits:
      nvidia.com/gpu: "1"
```

The model is loaded once at module level and stays warm across invocations.
Retry policies and GPU requests live in the manifest, not in application code.

Or, compose all three into a flow:

```python
async def ml_pipeline(payload):
    preprocessed = await preprocess(payload)
    predicted = await inference(preprocessed)
    return await evaluate(predicted)
```

The flow compiler transforms this into standard actors linked by message routes.

## When to Choose Kubeflow Pipelines

KFP is a mature ML platform with deep Vertex AI integration. It is the stronger choice when:

- **ML experiment tracking** -- built-in pipeline versioning, run comparison,
  artifact lineage, and metrics dashboards. KFP treats experiments as
  first-class entities.
- **Artifact management** -- typed artifacts (Dataset, Model, Metrics) with
  automatic persistence and lineage tracking through ML Metadata.
- **Notebook-driven workflows** -- compile and submit pipelines directly from
  Jupyter notebooks. Data scientists never leave their notebook.
- **Vertex AI integration** -- KFP is the native pipeline format for Google
  Cloud Vertex AI. Managed execution with zero infrastructure on GCP.
- **Batch-only workloads** -- if every run is a scheduled batch job with no
  real-time traffic, the pod-per-step model is simple and sufficient.
- **Existing KFP investment** -- organizations with hundreds of KFP pipelines
  and ML Metadata lineage should evaluate migration cost carefully.

## When to Choose Asya

Asya is purpose-built for workloads where KFP's pod-per-step model becomes a bottleneck:

- **High-throughput inference** -- processing thousands of items per hour where
  cold-starting a GPU pod per run is prohibitive. Asya actors stay warm.
- **Independent per-step scaling** -- a CPU preprocessor scales 0-50 while a
  GPU inference actor scales 0-5, each based on its own queue depth. KFP
  scales the entire pipeline as one Argo Workflow.
- **Scale-to-zero GPU savings** -- KEDA scales GPU pods to zero when queues
  drain. KFP pods spin up and tear down per run, paying cold start every time.
- **Real-time and streaming** -- Asya actors process messages as they arrive.
  KFP pipelines are batch-oriented with no built-in streaming path.
- **Dynamic routing** -- an LLM judge can route high-confidence results to
  storage and uncertain results to human review at runtime. KFP DAGs are
  static and compiled before execution.
- **Agentic AI patterns** -- built-in A2A and MCP gateway, pause/resume for
  human-in-the-loop, FLY streaming for live token output. KFP was not designed
  for interactive agent workflows.
- **No SDK lock-in** -- plain `dict -> dict` functions. No `@dsl.component`,
  no typed I/O annotations, no `kfp` dependency. Platform engineers own the
  YAML; data scientists own the Python function.
