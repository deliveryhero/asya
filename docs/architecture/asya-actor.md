# AsyncActor

## What is an Actor?

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

- **Napping**: `minReplicas=0`, no pods running, queue empty
- **Running**: Active pods processing messages
- **Scaling**: KEDA adjusting replica count based on queue depth
- **Failing**: Pods crashing, requires intervention

## Architecture Diagram

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

## Deployment

Actors deploy via AsyncActor CRD:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: text-processor
spec:
  transport: sqs
  scaling:
    minReplicas: 0
    maxReplicas: 50
    queueLength: 5
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: my-processor:v1
          env:
          - name: ASYA_HANDLER
            value: "processor.TextProcessor.process"
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

**Custom actor name** via `asya.sh/actor` label enables multi-region/multi-cluster deployments:

```yaml
# EU region
metadata:
  name: text-processor-eu
  labels:
    asya.sh/actor: text-processor  # Actor name = text-processor
# Queue: asya-production-text-processor

# US region
metadata:
  name: text-processor-us
  labels:
    asya.sh/actor: text-processor  # Same actor name
# Queue: asya-production-text-processor (same queue!)
```

**Benefits**:
- ✅ Same logical actor across regions/clusters
- ✅ Distinct resource names for cluster management
- ✅ Shared queue for load distribution
- ✅ Filter by actor: `kubectl get asya -l asya.sh/actor=text-processor`

**Queue naming format**: `asya-{namespace}-{actor-name}`

**See**: [`examples/asyas/multi-region-actor.yaml`](https://github.com/deliveryhero/asya/tree/main/examples/asyas/multi-region-actor.yaml) for multi-region example.

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
kubectl get all -l app=example-ecommerce
kubectl get deployments,secrets -l team=ml-platform
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
# List actors (shows ACTOR column from asya.sh/actor label)
kubectl get asyas

# List actors with flow and other details
kubectl get asyas -o wide

# Filter by actor name
kubectl get asya -l asya.sh/actor=text-processor

# Filter by flow
kubectl get asya -l asya.sh/flow=document-processing

# View actor details
kubectl get asya text-processor -o yaml

# View actor status
kubectl describe asya text-processor

# Watch autoscaling
kubectl get hpa -w

# View pods (uses asya.sh/actor label for pod selection)
kubectl get pods -l asya.sh/actor=text-processor

# View logs
kubectl logs -f deploy/text-processor
kubectl logs -f deploy/text-processor -c asya-sidecar
```

## Deployment with Helm

Use `asya-actor` chart for batch deployment:

```yaml
# values.yaml
actors:
  - name: text-processor
    transport: sqs
    scaling:
      minReplicas: 0
      maxReplicas: 50
    image: my-processor:v1
    handler: processor.TextProcessor.process
```

```bash
helm install my-actors deploy/helm-charts/asya-actor/ -f values.yaml
```

**See**: [install/helm-charts.md](../install/helm-charts.md) for details.
