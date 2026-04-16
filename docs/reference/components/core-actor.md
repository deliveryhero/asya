---
description: "AsyncActor CRD: status model, lifecycle phases, Crossplane composition behavior"
---

# Actor

![AsyncActor pod anatomy: sidecar + runtime + optional state proxy](../../website/img/actor-anatomy.png)

An actor is a **stateless workload** that:

- Receives messages from an input queue
- Processes them via user-defined code
- Sends results to the next queue in the route

**Alternative to monolithic pipelines**: Instead of one large application handling `A → B → C`, each step is an independent actor.

## Benefits

- **Independent scaling**: Each actor scales based on its queue depth
- **Independent deployment**: Deploy actors separately, no downtime
- **Separation of concerns**: Pipeline logic decoupled from business logic
- **Resilience**: Actor failures don't affect others

## Actor Lifecycle States

- **Napping**: `minReplicaCount=0`, no pods running, queue empty
- **Running**: Active pods processing messages
- **Scaling**: KEDA adjusting replica count based on queue depth
- **Failing**: Pods crashing, requires intervention

## Pod Structure

Simplified view:

```
┌──────────────────────────────────────────────┐
│               AsyncActor Pod                 │
│  ┌────────────┐             ┌──────────────┐ │
│  │Asya Sidecar│◄───────────►│ Asya Runtime │ │
│  │            │ Unix Socket │              │ │
│  │  Routing   │             │  User Code   │ │
│  │  Transport │             │              │ │
│  │  Metrics   │             │  Handler     │ │
│  └─────▲──────┘             └──────────────┘ │
│        │                                     │
└────────┼─────────────────────────────────────┘
         │ Queue Messages
         │
         ▼
    ┌─────────┐
    │  Queue  │
    │ (SQS/   │
    │RabbitMQ)│
    └─────────┘
```

**Message flow**: Queue → Sidecar → Runtime (your handler) → Sidecar → Next Queue

## Deployment

Actors deploy via AsyncActor CRD:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: text-processor
spec:
  image: my-processor:v1
  handler: processor.TextProcessor.process
  scaling:
    minReplicaCount: 0
    maxReplicaCount: 50
    queueLength: 5
```

**Operator injects**:

- `asya-sidecar` container (routing, transport)
- `asya_runtime.py` entrypoint script via ConfigMap
- Runtime container's command calling `asya_runtime.py`
- Environment variables (`ASYA_SOCKET_DIR`, etc.)
- Volume mounts for Unix socket
- Readiness probes

**See** [`examples/asyas/`](https://github.com/deliveryhero/asya/tree/main/examples/asyas) for more `AsyncActor` examples.

## Actor Identity and Queue Naming

**Actor name** determines queue naming and routing identity. By default, it uses `metadata.name`:

```yaml
metadata:
  name: text-processor  # Actor name = text-processor
  namespace: production # Queue name = asya-production-text-processor
```

- **Filter by actor**: `kubectl get asya -n production -l asya.sh/actor=text-processor`.
- **Queue naming format**: `asya-{namespace}-{actor-name}`

## Label Propagation

Labels from AsyncActor CR automatically propagate to all child resources (Deployment, Secret, ServiceAccount, ScaledObject, TriggerAuthentication):

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: text-processor
  labels:
    asya.sh/flow: document-processing
    app: example-ecommerce
    team: ml-platform
    env: production
spec:
  # ... spec
```

**Result**: All resources created by operator inherit user labels plus operator-managed labels:
- User labels: `asya.sh/flow`, `app`, `team`, `env`
- Operator labels: `asya.sh/actor`, `app.kubernetes.io/name`, `app.kubernetes.io/component`, `app.kubernetes.io/managed-by`

**Filter resources by label**:
```bash
# Recommended: Use asya.sh/actor to find all resources for an actor
kubectl get all -l asya.sh/actor=text-processor

# Filter by custom user labels (Deployments, Secrets, ScaledObjects, etc.)
kubectl get deployments,secrets -l app=example-ecommerce
kubectl get deployments,secrets -l team=ml-platform

# Filter AsyncActors by flow or actor name
kubectl get asya -l asya.sh/flow=document-processing
kubectl get asya -l asya.sh/actor=text-processor
```

**Reserved label prefixes** (user labels using these are rejected by operator):
- `app.kubernetes.io/`
- `asya.sh/` (except `asya.sh/actor` and `asya.sh/flow` which are user-controlled)
- `keda.sh/`
- `kubernetes.io/`

## Basic Commands

```bash
# List actors
kubectl get asyas
kubectl get asyas -o wide

# Filter by flow
kubectl get asya -l asya.sh/flow=document-processing

# View actor details
kubectl describe asya -l asya.sh/flow=document-processing

# View pods
kubectl get pods -l asya.sh/flow=document-processing

# View logs (all actors in a flow)
kubectl logs -f -l asya.sh/flow=document-processing
kubectl logs -f -l asya.sh/flow=document-processing -c asya-sidecar

# Watch autoscaling
kubectl get hpa -l asya.sh/flow=document-processing -w
```

## Handler Return Values and Sidecar Behavior

The sidecar interprets the handler's return value to decide routing:

| Handler returns | Sidecar behavior |
|----------------|-----------------|
| `dict` (e.g. `{"result": ...}`) | Route payload to next actor in `route.next`, or to x-sink if route is exhausted |
| `None` | Treat as empty response — route original envelope to x-sink |
| Generator `yield payload` | Each yield emits a downstream frame routed independently |
| Generator returns without yielding | Same as `None` — route original envelope to x-sink |

**Key distinction**: returning `None` vs `{}` changes routing behavior for regular actors:
- `None` → runtime signals end-of-route (`route.curr` becomes `""`) → sidecar routes to x-sink with **original** payload
- `{}` → runtime treats as valid output → sidecar routes `{}` as payload to next actor or x-sink

**End actors** (x-sink, x-sump) are terminal — the sidecar never routes their responses. Instead, it reports final status to gateway. See [core-crew.md](core-crew.md) for details.
