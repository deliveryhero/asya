# Quickstart (Kind)

Asya is an Actor Mesh framework for running AI/ML workloads on Kubernetes. Actors communicate
through message queues and scale independently from zero based on queue depth.

## Prerequisites

- [Docker](https://docs.docker.com/get-started/) 24+
- [kubectl](https://kubernetes.io/docs/tasks/tools/) 1.28+
- [Helm](https://helm.sh/docs/intro/install/) 3.12+
- [Kind](https://kind.sigs.k8s.io/) 0.20+ (for local development)

## 1. Create cluster

### Local (Kind)

```bash
kind create cluster --name asya-quickstart
```

### Production

For managed Kubernetes, see the cloud-specific guides:

- **[AWS EKS](start-aws-eks.md)** — SQS transport, S3 storage, IRSA for IAM
- **[GCP GKE](start-gcp-gke.md)** — Pub/Sub transport, GCS storage, Workload Identity

```bash
# EKS example (sketch):
# eksctl create cluster --name asya --region us-east-1
# eksctl create iamserviceaccount --name asya-sa ...  # IRSA for SQS/S3 access

# GKE example (sketch):
# gcloud container clusters create asya --region us-central1
# gcloud iam service-accounts create asya-sa ...      # Workload Identity
```

<details>
<summary>Kind with port mapping (to avoid local port-forwarding)</summary>

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

Maps NodePort 30080 to `http://localhost:8080`.

</details>

## 2. Install Asya

### Playground (all-in-one)

`asya-playground` installs Crossplane providers, LocalStack (SQS + S3), crew actors,
and a hello-world actor. Prerequisites: Crossplane operator and KEDA (installed separately).

Two phases: install infrastructure first, then enable actors after Crossplane providers
have registered their CRDs.

```bash
# Prerequisites
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm repo add kedacore https://kedacore.github.io/charts
helm repo add asya https://asya.sh/charts
helm repo update

helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system --create-namespace \
  --wait --timeout 120s

helm install keda kedacore/keda \
  --namespace keda --create-namespace --wait

# Phase 1: install playground (providers, LocalStack, XRDs)
helm install asya asya/asya-playground \
  --namespace asya-demo --create-namespace \
  --set global.transport=sqs \
  --set global.storage=s3 \
  --timeout 600s --wait

# Phase 2: wait for CRDs, enable actors
kubectl wait --for=condition=Healthy \
  providers/provider-aws-sqs providers/provider-kubernetes \
  functions/function-go-templating functions/function-patch-and-transform functions/function-auto-ready \
  --timeout=300s
kubectl wait --for=condition=Established xrd/xasyncactors.asya.sh --timeout=120s

helm upgrade asya asya/asya-playground --namespace asya-demo \
  --reuse-values \
  --set asya-crossplane.providerConfigs.install=true \
  --set enableAsyaCrew=true \
  --set helloActor.enabled=true \
  --timeout 300s --wait
```

<details>
<summary>What the playground installs</summary>

| Component | Role |
|-----------|------|
| **Crossplane** | Operator that manages infrastructure declaratively via Compositions |
| **Crossplane providers** | Manage SQS queues and K8s Deployments declaratively |
| **KEDA** | Autoscale actors 0 to N based on queue depth |
| **LocalStack** | In-cluster SQS + S3 emulator (no AWS account needed) |
| **x-sink** | Crew actor — persists completed results |
| **x-sump** | Crew actor — collects failed messages |
| **hello** | Sample actor — greets by name, demonstrates full message flow |

Each `AsyncActor` maps to: one SQS queue + one Deployment + one KEDA ScaledObject,
all managed by Crossplane Compositions. Deleting an `AsyncActor` cascades to all three.

</details>

<details>
<summary>Manual installation (without asya-playground)</summary>

For production, install each component individually with your own infrastructure:

```bash
# 1. Crossplane (manages actor infrastructure declaratively)
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system --create-namespace \
  --wait --timeout 120s

# 2. KEDA (autoscales actors based on queue depth)
helm repo add kedacore https://kedacore.github.io/charts
helm install keda kedacore/keda \
  --namespace keda --create-namespace --wait

# 3. Cloud credentials
#    AWS: create secret with access key, or use IRSA (see EKS guide)
#    GCP: use Workload Identity (see GKE guide)
#
#    The secret must exist in crossplane-system (for ProviderConfig)
#    AND in the actor namespace (for KEDA TriggerAuthentication).
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

# Also create credentials in the actor namespace (used by KEDA)
kubectl create namespace YOUR_NAMESPACE
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Secret
metadata:
  name: aws-creds
  namespace: YOUR_NAMESPACE
type: Opaque
stringData:
  AWS_ACCESS_KEY_ID: YOUR_ACCESS_KEY
  AWS_SECRET_ACCESS_KEY: YOUR_SECRET_KEY
EOF

# 4. Asya Crossplane chart (XRDs, Compositions, ProviderConfigs)
#    This installs cluster-scoped resources (XRDs, Compositions, Providers,
#    RBAC) and a namespace-scoped runtime ConfigMap. Only one asya-crossplane
#    release can exist per cluster.
helm repo add asya https://asya.sh/charts
helm install asya-crossplane asya/asya-crossplane \
  --namespace asya-system --create-namespace \
  --set providers.aws.enabled=true \
  --set transport=sqs \
  --set awsProviderConfig.secretRef.namespace=crossplane-system \
  --set actorNamespace=YOUR_NAMESPACE \
  --wait --timeout 300s

# Wait for Crossplane providers and XRD to become ready
kubectl wait --for=condition=Healthy \
  providers/provider-aws-sqs providers/provider-kubernetes \
  functions/function-go-templating functions/function-patch-and-transform functions/function-auto-ready \
  --timeout=300s
kubectl wait --for=condition=Established xrd/xasyncactors.asya.sh --timeout=120s

# Enable ProviderConfigs (after provider CRDs are registered)
helm upgrade asya-crossplane asya/asya-crossplane \
  --namespace asya-system --reuse-values \
  --set providerConfigs.install=true \
  --wait

# 5. Crew actors (x-sink, x-sump)
helm install asya-crew asya/asya-crew \
  --namespace YOUR_NAMESPACE \
  --wait
```

See [Helm Charts Guide](guide-helm-charts.md) and [Gateway Setup](guide-gateway.md) for
full configuration reference.

</details>

## 3. Send a message

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

KEDA detects the message and scales the hello actor from 0 to 1 (~30s). After processing,
the result routes to `x-sink` and the actor scales back to zero.

## 4. Verify

```bash
# Check actor status
kubectl get asyncactors -n asya-demo

# Watch scale-from-zero
kubectl get deployment hello -n asya-demo -w

# Pod should show 2/2 containers (handler + sidecar)
kubectl get pods -n asya-demo -l asya.sh/actor=hello
```

Expected:
- `x-sink`, `x-sump` — `Ready` (always running)
- `hello` — scales 0 to 1 on message, back to 0 after cooldown

## 5. Check logs

```bash
POD=$(kubectl get pods -n asya-demo -l asya.sh/actor=hello -o jsonpath='{.items[0].metadata.name}')

# Handler output
kubectl logs -n asya-demo "$POD" -c asya-runtime --tail=20

# Message routing (SQS -> runtime -> x-sink)
kubectl logs -n asya-demo "$POD" -c asya-sidecar --tail=20
```

## 6. Clean up

```bash
helm uninstall asya -n asya-demo
helm uninstall keda -n keda
helm uninstall crossplane -n crossplane-system
kind delete cluster --name asya-quickstart
```

---

## What's next?

- **[Build Your First Actor](../usage/start-first-actor.md)** — actor handlers, class-based actors, the Flow DSL
- **[AWS EKS Guide](start-aws-eks.md)** — production deployment with SQS, S3, IRSA
- **[GCP GKE Guide](start-gcp-gke.md)** — production deployment with Pub/Sub, GCS, Workload Identity
- **[Monitoring](ops-observability.md)** — observability, scaling policies, troubleshooting
- **[Architecture](../architecture.md)** — actors, envelopes, routing deep dive
- **[Examples](https://github.com/deliveryhero/asya/tree/main/examples)** — sample actors and flows

---

<details>
<summary>Troubleshooting</summary>

### Providers not becoming Healthy

```bash
kubectl describe providers provider-aws-sqs
kubectl describe functions function-go-templating
```

Providers pull packages from `xpkg.upbound.io`. On slow connections, increase the `--timeout`.

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
