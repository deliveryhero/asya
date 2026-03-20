<!-- Type: Tutorial -->
# Getting Started with Asya🎭

Asya is an Actor Mesh framework for running AI/ML workloads on Kubernetes. Actors communicate
through message queues and scale independently from zero based on queue depth.

## Prerequisites

- [Docker](https://docs.docker.com/get-started/) 24+
- [kubectl](https://kubernetes.io/docs/tasks/tools/) 1.28+
- [Helm](https://helm.sh/docs/intro/install/) 3.12+
- [Kind](https://kind.sigs.k8s.io/) 0.20+

## 1. Create a Kind cluster (local K8s)

### Quick Start (Default Configuration)

```bash
kind create cluster --name asya-quickstart
```

### Advanced Configuration (with Port Mapping)

For exposing services via NodePort, create a Kind cluster with port mappings:

```yaml
# kind-config.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:

- role: control-plane
  extraPortMappings:
  - containerPort: 30080
    hostPort: 8080
    protocol: TCP
```

```bash
kind create cluster --name asya-quickstart --config kind-config.yaml
```

This maps the cluster's NodePort 30080 to your local port 8080, allowing you to access services at `http://localhost:8080`.

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
kubectl wait --for=condition=Healthy \
  providers/provider-aws-sqs providers/provider-kubernetes \
  functions/function-go-templating functions/function-patch-and-transform functions/function-auto-ready \
  --timeout=300s
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
values in each chart. See [For Platform Engineers](../operate/) for the full
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

## Alternative: Manual Installation

For more control over the installation process or to use different infrastructure backends:

### Using E2E Test Infrastructure

The E2E test infrastructure provides a complete development environment:

```bash
cd testing/e2e

# Deploy RabbitMQ + MinIO stack
make up PROFILE=rabbitmq-minio

# Or deploy AWS-style stack (LocalStack SQS + S3)
make up PROFILE=sqs-s3
```

**Includes**: Kind cluster, KEDA, Crossplane, RabbitMQ/SQS, MinIO/S3, PostgreSQL, gateway, crew actors, and test actors.

See `testing/e2e/README.md` for details.

### Manual Component Installation

1. **Install KEDA**:
```bash
helm repo add kedacore https://kedacore.github.io/charts
helm install keda kedacore/keda --namespace keda --create-namespace
```

2. **Install RabbitMQ**:
```bash
helm upgrade --install asya-rabbitmq testing/e2e/charts/rabbitmq \
  --namespace asya-e2e --create-namespace

kubectl wait --for=condition=ready pod -l app=rabbitmq \
  -n asya-e2e --timeout=300s
```

3. **Install MinIO**:
```bash
helm upgrade --install minio testing/e2e/charts/minio \
  --namespace asya-e2e --create-namespace
```

The chart automatically creates the `asya-results` and `asya-errors` buckets.

4. **Install Asya Gateway** (requires PostgreSQL):
```bash
helm upgrade --install asya-gateway-postgresql testing/e2e/charts/postgres \
  --namespace asya-e2e --create-namespace

cat > gateway-values.yaml <<'EOF'
config:
  postgresHost: asya-gateway-postgresql.asya-e2e.svc.cluster.local
  postgresDatabase: asya_gateway
  postgresUsername: postgres
  postgresPassword: postgres

routes:
  tools:
  - name: hello
    description: Hello actor
    parameters:
      who:
        type: string
        required: true
    route: [hello-actor]
EOF

helm install asya-gateway deploy/helm-charts/asya-gateway/ \
  -n asya-e2e --create-namespace \
  -f gateway-values.yaml
```

5. **Install Crew Actors**:
```bash
cat > crew-values.yaml <<'EOF'
x-sink:
  enabled: true
  env:
    ASYA_PERSISTENCE_MOUNT: /state/checkpoints

x-sump:
  enabled: true
  env:
    ASYA_PERSISTENCE_MOUNT: /state/checkpoints
EOF

helm install asya-crew deploy/helm-charts/asya-crew/ \
  --namespace asya-e2e \
  -f crew-values.yaml
```

---

## What's next?

- **[Usage Guide](usage.md)** — actor handlers, class-based actors, the Flow DSL
- **[Operate](../operate/)** — monitoring, scaling policies, troubleshooting, upgrades
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

### RabbitMQ connection errors (manual installations)

Check sidecar logs:
```bash
kubectl logs -l asya.sh/actor=hello-actor -c asya-sidecar -n asya-e2e
```

### Queue not created (manual installations)

```bash
kubectl describe asyncactor <actor-name>
kubectl get sqsqueue <queue-name> -o yaml
```

</details>
