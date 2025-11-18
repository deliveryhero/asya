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

## Basic Commands

```bash
# List actors
kubectl get asyas

# View actor details
kubectl get asya text-processor -o yaml

# View actor status
kubectl describe asya text-processor

# Watch autoscaling
kubectl get hpa -w

# View pods
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
