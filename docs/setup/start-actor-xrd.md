---
description: "Actor XRD deployment: deploy actors using Crossplane AsyncActor composite resource"
---

# Understanding the AsyncActor CRD

The AsyncActor is the only CRD you need to deploy an actor on Kubernetes.
This guide walks through what each section does and how Asya uses it.

## The Full Picture

Here's the full AsyncActor spec. Required fields are uncommented, everything else
is commented with defaults — uncomment what you need:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: image-enhancer
  namespace: production
  # labels:
  #   asya.sh/flow: image-pipeline    # group actors into a flow
  #   team: ml-platform               # custom labels propagate to all child resources
spec:
  # --- Required ---
  actor: image-enhancer
  image: ghcr.io/myorg/image-enhancer:v2.3
  handler: enhancer.SDXLEnhancer.process

  # --- Flavors: inherit platform-team defaults ---
  # flavors: [gpu-inference, llm-resilient]

  # --- Image settings ---
  # imagePullPolicy: Always           # default: IfNotPresent
  # pythonExecutable: /opt/conda/bin/python  # default: python3

  # --- Autoscaling (KEDA) ---
  # scaling:
  #   minReplicaCount: 0              # default: 0 (scale to zero)
  #   maxReplicaCount: 50             # default: 10
  #   queueLength: 1                  # default: 5 (messages per replica)
  #   pollingInterval: 10             # default: 30 (seconds)
  #   cooldownPeriod: 600             # default: 300 (seconds)

  # --- Fixed replicas (instead of autoscaling) ---
  # scaling:
  #   enabled: false
  # replicas: 3

  # --- Resiliency ---
  # resiliency:
  #   actorTimeout: 300s              # max processing time per message
  #   policies:
  #     default:
  #       maxAttempts: 3
  #       backoff: exponential        # constant | linear | exponential
  #       initialDelay: 1s
  #       maxInterval: 60s
  #     rate-limit:
  #       maxAttempts: 5
  #       backoff: constant
  #       initialDelay: 10s
  #   rules:
  #   - errors: ["RateLimitError"]    # retry with rate-limit policy
  #     policy: rate-limit

  # --- Environment variables ---
  # env:
  # - name: MODEL_PATH
  #   value: /models/sdxl-turbo
  # - name: API_KEY
  #   valueFrom:
  #     secretKeyRef:
  #       name: api-credentials
  #       key: key

  # --- Secret injection (per-key env var mapping) ---
  # secretRefs:
  # - secretName: aws-creds
  #   keys:
  #   - key: aws-access-key-id
  #     envVar: AWS_ACCESS_KEY_ID
  #   - key: aws-secret-access-key
  #     envVar: AWS_SECRET_ACCESS_KEY

  # --- Resources and GPU scheduling ---
  # resources:
  #   requests:
  #     cpu: "2"
  #     memory: 8Gi
  #     nvidia.com/gpu: "1"
  #   limits:
  #     cpu: "4"
  #     memory: 16Gi
  #     nvidia.com/gpu: "1"
  #
  # nodeSelector:
  #   cloud.google.com/gke-accelerator: nvidia-tesla-a100
  #
  # tolerations:
  # - key: nvidia.com/gpu
  #   operator: Exists
  #   effect: NoSchedule
```

When you `kubectl apply` this, Asya creates three resources:

1. **Message queue** (`asya-production-image-enhancer`) — the actor's inbox
2. **Deployment** with sidecar + runtime containers
3. **KEDA ScaledObject** watching the queue depth

Delete the AsyncActor and all three are cleaned up automatically.

## What Asya Fills In

You write the minimal spec. Asya's Crossplane Composition fills in everything else:

- Sidecar container (Go binary for queue polling and routing)
- Runtime container command (loads `asya_runtime.py` which calls your handler)
- Unix socket volume for sidecar-runtime communication
- Environment variables (`ASYA_HANDLER`, `ASYA_SOCKET_DIR`, etc.)
- Readiness probes
- Transport configuration (SQS endpoint, RabbitMQ URL, etc.)

Your image only needs Python and your handler code. No Asya dependencies.

## Scaling

By default, actors scale to zero and back:

```yaml
spec:
  scaling:
    minReplicaCount: 0      # zero pods when queue is empty
    maxReplicaCount: 20     # burst capacity
    queueLength: 5          # target: 5 messages per replica
    pollingInterval: 15     # check queue every 15 seconds
    cooldownPeriod: 300     # wait 5 min before scaling down
```

**How it works**: if the queue has 25 messages and `queueLength` is 5, KEDA creates
5 replicas. When the queue drains, pods scale back to 0 after the cooldown period.

To disable autoscaling (fixed replicas):

```yaml
spec:
  scaling:
    enabled: false
  replicas: 3
```

## Resiliency

Configure retries and timeouts at the infrastructure level — not in your code:

```yaml
spec:
  resiliency:
    actorTimeout: 120s
    policies:
      default:
        maxAttempts: 3
        backoff: exponential
        initialDelay: 1s
        maxInterval: 60s
    rules:
    - errors: ["RateLimitError"]
      policy: default
```

**Policies** define retry behavior (how many times, what backoff strategy).
**Rules** match error type names to policies — checked against the exception MRO.
Unmatched errors use the `default` policy. When a policy is exhausted, the envelope
routes to `x-sink` (phase: failed). Use `onExhausted` on a policy to forward to
a fallback actor instead:

```yaml
    policies:
      retryable:
        maxAttempts: 3
        backoff: exponential
        initialDelay: 1s
        onExhausted: ["fallback-actor"]
```

The sidecar applies resiliency only to handler-level errors. Infrastructure errors
(timeouts, runtime crashes, parse errors) bypass retry logic and route directly to
`x-sump`.

## Flavors

Platform engineers pre-configure common patterns as **flavors** — reusable templates
that bundle scaling, resiliency, and infrastructure settings:

```yaml
spec:
  image: my-model:latest
  handler: handler.process
  flavors: [gpu-inference, llm-resilient]
```

The actor inherits all settings from the flavors. Inline spec fields override flavor
defaults. This keeps the data scientist's YAML short while the platform team controls
infrastructure.

See [Actor Flavors guide](guide-actor-flavors.md) for how to define and use flavors.

## Environment Variables and Secrets

Inject env vars directly or from Kubernetes secrets:

```yaml
spec:
  env:
  - name: MODEL_PATH
    value: /models/v2
  - name: API_KEY
    valueFrom:
      secretKeyRef:
        name: api-credentials
        key: key

  secretRefs:
  - secretName: api-credentials
    keys:
    - key: api-key
      envVar: API_KEY
    - key: api-org
      envVar: API_ORG
```

Each `secretRefs` entry maps named Secret keys to environment variables.

## Resources and Scheduling

Standard Kubernetes resource management:

```yaml
spec:
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: "2"
      memory: 2Gi
      nvidia.com/gpu: "1"

  nodeSelector:
    cloud.google.com/gke-accelerator: nvidia-tesla-t4

  tolerations:
  - key: nvidia.com/gpu
    operator: Exists
    effect: NoSchedule
```

## What Happens Under the Hood

When you apply an AsyncActor:

```
kubectl apply -f actor.yaml
        |
        v
  Crossplane sees the AsyncActor CR
        |
        v
  Composition renders:
  +-- SQS Queue (or RabbitMQ queue, Pub/Sub subscription)
  +-- Deployment
  |     +-- sidecar container (Go)
  |     +-- runtime container (your image + asya_runtime.py)
  |     +-- shared Unix socket volume
  |     +-- env vars, secrets, volumes
  +-- KEDA ScaledObject
  +-- TriggerAuthentication (queue credentials)
        |
        v
  KEDA watches queue depth, scales 0 -> N
```

The sidecar polls the queue, delivers each envelope to your handler via Unix socket,
and routes the result to the next actor in the route. Your handler never touches queues.

## Further Reading

- **[AsyncActor CRD Reference](../reference/specs/asyncactor-crd.md)** — full field reference
- **[Separation of Concerns](../concepts/separation-of-concerns.md)** — the two-file model
- **[Scale Zero to Infinity](../concepts/scale-to-zero.md)** — KEDA autoscaling deep dive
- **[Built-in Resiliency](../concepts/built-in-resiliency.md)** — retry policies and error handling
- **[Actor Flavors](guide-actor-flavors.md)** — reusable configuration templates
