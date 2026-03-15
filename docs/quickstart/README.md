# Getting Started with Asya🎭

Asya is an Actor Mesh framework for running AI/ML workloads on Kubernetes. Actors communicate
through message queues and scale independently from zero based on queue depth.

## Prerequisites

- [Docker](https://docs.docker.com/get-started/) 24+
- [kubectl](https://kubernetes.io/docs/tasks/tools/) 1.28+
- [Helm](https://helm.sh/docs/intro/install/) 3.12+
- [Kind](https://kind.sigs.k8s.io/) 0.20+

## 1. Create a Kind cluster (local K8s)

```bash
kind create cluster --name asya-quickstart
```

## 2. Install Crossplane

Crossplane manages actor infrastructure (SQS queues, Deployments, KEDA ScaledObjects).
It must be installed before the playground chart because the playground's providers need
Crossplane's CRDs to be registered first.

```bash
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm repo update crossplane-stable
helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system --create-namespace \
  --wait --timeout 180s
```

## 3. Install the playground chart

`asya-playground` is a batteries-included quickstart: Crossplane, KEDA, LocalStack (SQS + S3),
crew actors, and a hello-world actor — all in one release. No separate installs needed.

Installation has three phases because Crossplane providers must register their CRDs before
actor resources can be created.

### Add the Helm repository

```bash
helm repo add asya https://asya.sh/charts
helm repo update asya
```

### Phase 1 — infrastructure only (no actors yet)

```bash
helm install asya asya/asya-playground \
  --namespace asya-demo --create-namespace \
  --set global.transport=sqs \
  --set global.storage=s3 \
  --timeout 600s --wait
```

### Phase 2 — wait for providers, then enable everything

```bash
# Wait for Crossplane providers, functions, and AsyncActor XRD to become ready
kubectl wait --for=condition=Healthy providers/provider-aws-sqs --timeout=300s
kubectl wait --for=condition=Healthy providers/provider-kubernetes --timeout=300s
kubectl wait --for=condition=Healthy functions/function-go-templating --timeout=300s
kubectl wait --for=condition=Healthy functions/function-patch-and-transform --timeout=300s
kubectl wait --for=condition=Healthy functions/function-auto-ready --timeout=300s
kubectl wait --for=condition=Established xrd/xasyncactors.asya.sh --timeout=120s

# Enable ProviderConfigs and actors in one upgrade
helm upgrade asya asya/asya-playground --namespace asya-demo \
  --reuse-values \
  --set asya-crossplane.providerConfigs.install=true \
  --set enableAsyaCrew=true \
  --set helloActor.enabled=true \
  --timeout 300s --wait
```

<details>
<summary>What gets installed</summary>

| Component | Role |
|-----------|------|
| **Crossplane** | Operator that manages AsyncActor infrastructure declaratively via Compositions |
| **provider-aws-sqs** | Crossplane provider — creates SQS queues in LocalStack |
| **provider-kubernetes** | Crossplane provider — creates Deployments and KEDA ScaledObjects |
| **KEDA** | Autoscaler — reads SQS queue depth to scale actor Deployments from 0 to N |
| **LocalStack SQS** | In-cluster SQS emulator — no AWS account needed |
| **LocalStack S3** | In-cluster S3 emulator for result storage |
| **x-sink** | Crew actor — receives completed pipeline results |
| **x-sump** | Crew actor — receives failed/errored messages |
| **hello actor** | Sample actor — scales from 0, greets by name, demonstrates the full message flow |

Each `AsyncActor` resource maps to: one SQS queue + one Deployment + one KEDA ScaledObject,
all managed by Crossplane Compositions. Deleting an `AsyncActor` cascades to all three.

The sidecar (injected by Crossplane into each actor pod) handles SQS polling, runtime
communication, and routing to the next actor in the pipeline.

</details>

<details>
<summary>Production install (without asya-playground)</summary>

For production, install each component independently with your own infrastructure:

```bash
# 1. Install Crossplane
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system --create-namespace \
  --wait --timeout 120s

# 2. Create AWS credentials secret (use real credentials for production)
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Secret
metadata:
  name: aws-creds
  namespace: crossplane-system
type: Opaque
stringData:
  credentials: |
    [default]
    aws_access_key_id = YOUR_ACCESS_KEY
    aws_secret_access_key = YOUR_SECRET_KEY
  AWS_ACCESS_KEY_ID: YOUR_ACCESS_KEY
  AWS_SECRET_ACCESS_KEY: YOUR_SECRET_KEY
EOF

# 3. Install KEDA
helm repo add kedacore https://kedacore.github.io/charts
helm install keda kedacore/keda --namespace keda --create-namespace --wait

# 4. Install asya-crossplane (XRDs, Compositions, ProviderConfigs)
helm repo add asya https://asya.sh/charts
helm install asya-crossplane asya/asya-crossplane \
  --namespace asya-system --create-namespace \
  --set awsProviderConfig.secretRef.namespace=crossplane-system \
  --set actorNamespace=YOUR_NAMESPACE \
  --wait

# 5. Install asya-crew (system actors)
helm install asya-crew asya/asya-crew \
  --namespace YOUR_NAMESPACE \
  --wait
```

Configure external services (real AWS SQS/S3, RabbitMQ, etc.) by overriding the relevant
values in each chart. See [For Platform Engineers](for-platform-engineers.md) for the full
production setup guide.

</details>

## 4. Verify the installation

```bash
kubectl get pods -n asya-demo
kubectl get asyncactors -n asya-demo
kubectl get scaledobject -n asya-demo
```

Expected:
- `x-sink`, `x-sump` — `Ready` (always running, `minReplicaCount=1`)
- `hello` — `Napping` (scaled to 0 until a message arrives)

## 5. Send a test message

```bash
kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace asya-demo \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- sh -c "
    aws sqs send-message \
      --endpoint-url=http://localstack-sqs.asya-demo:4566 \
      --queue-url http://localstack-sqs.asya-demo:4566/000000000000/asya-asya-demo-hello \
      --message-body '{\"id\":\"test-1\",\"route\":{\"prev\":[],\"curr\":\"hello\",\"next\":[]},\"headers\":{},\"payload\":{\"name\":\"Asya\"}}'
  "
```

## 6. Watch scale-from-zero

KEDA detects the message and scales the hello deployment from 0 to 1 (takes ~30s):

```bash
kubectl get deployment hello -n asya-demo -w
```

Once the pod is running, it shows `2/2` containers (handler + sidecar injected by Crossplane):

```bash
kubectl get pods -n asya-demo -l asya.sh/actor=hello
```

## 7. Check logs

```bash
POD=$(kubectl get pods -n asya-demo -l asya.sh/actor=hello -o jsonpath='{.items[0].metadata.name}')

# Runtime: handler output
kubectl logs -n asya-demo "$POD" -c asya-runtime --tail=20

# Sidecar: message routing (received from SQS, called runtime, forwarded to x-sink)
kubectl logs -n asya-demo "$POD" -c asya-sidecar --tail=20
```

After the KEDA cooldown period (default 5 min), the hello actor scales back to zero.

## Clean up

```bash
helm uninstall asya -n asya-demo
kind delete cluster --name asya-quickstart
```

---

## What's next?

- **[For Data Scientists](for-data-scientists.md)** — actor handlers, class-based actors, the Flow DSL
- **[For Platform Engineers](for-platform-engineers.md)** — production deployment, scaling policies
- **[Architecture](../architecture/README.md)** — deep dive into actors, envelopes, routing
- **[Examples](../../examples/)** — sample actors and flows

---

<details>
<summary>Troubleshooting</summary>

### Providers not becoming Healthy

```bash
kubectl describe providers provider-aws-sqs
kubectl describe functions function-go-templating
```

Providers pull packages from `xpkg.upbound.io`. On slow connections, increase the `--timeout`
in the `kubectl wait` commands above.

### AsyncActor CRD not found

```bash
kubectl get xrd xasyncactors.asya.sh
# Should show ESTABLISHED=True, OFFERED=True
```

If not established, re-run Phase 2.

### Actors stuck in Creating

```bash
kubectl describe asyncactor hello -n asya-demo
```

### Pod shows 1/2 containers

Delete the pod to trigger re-creation from the updated Crossplane composition:

```bash
kubectl delete pod -n asya-demo -l asya.sh/actor=hello
```

</details>
