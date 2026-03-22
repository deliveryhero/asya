# vs Ray Serve

## TL;DR

**Ray Serve** is a Python-native model serving framework built on the Ray distributed runtime.
It excels at multi-model composition, GPU-aware scheduling, and low-latency inference — all
within its own cluster abstraction. **Asya** is a Kubernetes-native actor mesh where each
step is an independent pod scaling on queue depth via KEDA. Ray Serve owns the cluster; Asya
delegates everything to Kubernetes.

Choose Ray Serve when you need tight GPU multiplexing and sub-50ms inter-model latency.
Choose Asya when you need independent per-step scaling, scale-to-zero, dynamic routing, and
want to stay on pure Kubernetes without a second cluster runtime.

## At a Glance

| Dimension | Ray Serve | 🎭 |
|---|---|---|
| **Runtime** | Ray cluster (head + worker nodes) | Kubernetes pods + message queues |
| **Unit of deployment** | `@serve.deployment` Python class | `AsyncActor` CRD + pure Python function |
| **Scaling** | Ray Autoscaler (replica + node level) | KEDA ScaledObject per actor (queue depth) |
| **Scale to zero** | ❌ Not supported (head node always runs) | ✅ Native — every actor scales to 0 |
| **GPU support** | First-class (`ray_actor_options={"num_gpus": 1}`) | K8s `resources.limits` + GPU node pools |
| **Inter-step communication** | In-process or Ray object store (shared memory) | Message queue (SQS, RabbitMQ, Pub/Sub) |
| **Latency** | Microseconds (shared memory) | Milliseconds–seconds (queue round-trip) |
| **Fault tolerance** | Ray reconstructs lost objects; actor restart | Queue redelivery; pod restart |
| **Multi-model composition** | Deployment graph / `bind()` API | Envelope routing (`route.next`) |
| **Dynamic routing** | ⚠️ Application code in driver | ✅ Actor rewrites `route.next` at runtime |
| **Protocol surface** | HTTP/gRPC ingress | A2A, MCP, HTTP gateway |
| **Language** | Python (primarily) | Handler: Python; sidecar: Go; infra: YAML |
| **Operational dependency** | Ray head node, GCS, dashboard | Kubernetes, KEDA, queue backend |
| **Maturity** | 🟢 Mature (Ray 2.x, widespread adoption) | 🟡 Alpha (production at Delivery Hero) |

## Architecture

### Ray Serve

Ray Serve runs on top of a **Ray cluster** — a head node plus autoscaled worker nodes. Each
deployment is a Ray actor class replicated across workers. Calls between deployments travel
through Ray's object store (shared-memory plasma, or distributed via GCS), giving near-zero
serialization overhead for in-cluster communication.

```
Client --> HTTP/gRPC Ingress
              |
         Ray Head Node (GCS, Dashboard, Autoscaler)
              |
     +--------+--------+
     |        |        |
  Worker 1  Worker 2  Worker 3
  (GPU)     (GPU)     (CPU)
  [ModelA]  [ModelA]  [PostProc]
  [ModelB]  [ModelB]
```

Deployment graph (or `bind()`) lets you compose models:

```python
from ray import serve

@serve.deployment(num_replicas=2, ray_actor_options={"num_gpus": 1})
class Embedder:
    def __init__(self):
        self.model = load_model("bge-large")

    async def __call__(self, request):
        return self.model.encode(request.json()["text"])

@serve.deployment(num_replicas=1)
class Reranker:
    def __init__(self, embedder):
        self.embedder = embedder

    async def __call__(self, request):
        embedding = await self.embedder.remote(request)
        return self.rerank(embedding)

app = Reranker.bind(Embedder.bind())
serve.run(app)
```

### Asya

Asya has no cluster runtime. Each actor is a standard Kubernetes Deployment with an injected
sidecar. Actors communicate exclusively through message queues. KEDA watches each queue
independently and scales each actor from 0 to N.

```
Client --> Gateway (A2A / MCP / HTTP)
              |
         Queue A ──> Actor A (Embedder, GPU, 0-5 pods)
                         |
                    Queue B ──> Actor B (Reranker, CPU, 0-10 pods)
                                    |
                               Queue C ──> x-sink (persist result)
```

The same pipeline as two pure functions and one manifest:

```python
# embedder/handler.py
def embed(payload: dict) -> dict:
    payload["embedding"] = model.encode(payload["text"])
    return payload
```

```python
# reranker/handler.py
def rerank(payload: dict) -> dict:
    payload["ranked"] = do_rerank(payload["embedding"])
    return payload
```

```yaml
# asyncactor.yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: embedder
spec:
  image: embedder:latest
  handler: handler.embed
  scaling:
    minReplicaCount: 0
    maxReplicaCount: 5
    queueLength: 1
  resources:
    limits:
      nvidia.com/gpu: "1"
  resiliency:
    actorTimeout: 120s
    policies:
      default:
        maxAttempts: 3
        backoff: exponential
```

## Developer Experience

| Aspect | Ray Serve | 🎭 |
|---|---|---|
| **Getting started** | `pip install ray[serve]`; run locally | Requires K8s cluster, KEDA, queue backend |
| **Local iteration** | `serve.run(app)` — instant | `python handler.py` for logic; K8s for integration |
| **Deployment** | `serve deploy config.yaml` or KubeRay operator | `kubectl apply -f asyncactor.yaml` (Crossplane) |
| **Monitoring** | Ray Dashboard (built-in) | Grafana + per-actor queue metrics |
| **Model updates** | Rolling update via Ray config | Rolling update via K8s Deployment |
| **Multi-tenancy** | Single Ray cluster, namespace isolation | Native K8s namespaces, RBAC, network policies |
| **Secrets / config** | Environment or Ray runtime env | K8s Secrets, ConfigMaps, external-secrets-operator |

## When to Choose Ray Serve

- **Low-latency model composition** — your pipeline chains 3-5 models and needs sub-50ms
end-to-end; Ray's shared-memory object store avoids serialization overhead.

- **GPU multiplexing** — you want to pack multiple models onto a single GPU with fractional
allocation (`num_gpus=0.5`); Ray handles placement and memory management.

- **Python-centric team** — your team is all Python, models are all PyTorch/TensorFlow, and
you want everything in one language with minimal YAML.

- **Batch inference pipelines** — Ray's `@serve.batch` decorator handles dynamic batching
natively, accumulating requests to fill GPU utilization.

- **Tight coupling between models** — models share tensors or embeddings in-memory;
serializing to a queue would be wasteful.

## When to Choose Asya

- **Independent per-step scaling** — each pipeline stage has a different resource profile
(CPU preprocessing, GPU inference, CPU postprocessing) and needs to scale on its own
queue depth, not a shared autoscaler.

- **Scale to zero** — GPU pods cost nothing when idle. Ray Serve requires at least one head
node running at all times; Asya actors scale to zero pods when their queue is empty.

- **Dynamic routing** — actors rewrite `route.next` at runtime based on LLM confidence,
content type, or business rules. No static DAG to rebuild.

- **Separation of concerns** — data scientists write pure Python functions; platform
engineers own the `AsyncActor` manifest (scaling, retries, timeouts). The handler has zero
infrastructure imports.

- **Agentic workflows** — human-in-the-loop pause/resume, multi-turn conversations, A2A
protocol support, MCP tool exposure. These are built into the Asya gateway.

- **Multi-transport / multi-cloud** — the same actor runs on SQS, RabbitMQ, or Pub/Sub by
changing one field in the manifest. No code changes.

- **K8s-native operations** — you already have Kubernetes with RBAC, network policies,
namespaces, GitOps (ArgoCD/Flux), and observability. Asya adds no new cluster runtime —
it is Kubernetes.

- **Queue-native resilience** — if a pod dies mid-inference, the message goes back to the
queue. No custom checkpointing, no object store reconstruction. The queue is the checkpoint.

## Further Reading

- [Motivation](../motivation.md) — why async-first, queue-based AI pipelines
- [Actor Mesh](../concepts/actor-mesh.md) — choreography vs orchestration
- [Scale to Zero](../concepts/scale-to-zero.md) — per-actor KEDA scaling
