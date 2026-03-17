# GKE + GCP Pub/Sub Installation

Deploy Asya on Google Kubernetes Engine using native GCP Pub/Sub as the message transport.

## Prerequisites

- `gcloud` CLI authenticated (`gcloud auth login`)
- `kubectl` 1.24+, `helm` 3.14+, `docker`
- GKE cluster 1.30+ with Workload Identity enabled (see Section 2)
- GCP APIs enabled:

```bash
gcloud services enable container.googleapis.com pubsub.googleapis.com \
  artifactregistry.googleapis.com --project=$PROJECT
```

---

## 1. Environment Variables

Set these once before running any commands in this guide:

```bash
export PROJECT=<your-gcp-project-id>
export REGION=<region>              # e.g. europe-west1
export CLUSTER=<cluster-name>       # e.g. asya
export NS=<actor-namespace>         # e.g. asya
export REGISTRY=${REGION}-docker.pkg.dev/${PROJECT}/<registry-name>
export ASYA_VERSION=<release-tag>   # e.g. 0.5.5 — check github.com/deliveryhero/asya/releases
```

---

## 2. GKE Cluster Requirements

Asya has no special networking or hardware requirements. Any standard GKE cluster works.
The one Asya-specific requirement is **GKE Workload Identity** — both the Crossplane GCP
provider and actor sidecars rely on it for keyless authentication to GCP APIs.

When creating your cluster, ensure:

- `--workload-pool=${PROJECT}.svc.id.goog` is set (enables Workload Identity)
- Kubernetes 1.30+
- Cluster autoscaler recommended — KEDA scales actors to 0 when queues are empty,
  and the cluster autoscaler can then drain idle nodes to reduce cost

Configure `kubectl` access before proceeding:

```bash
gcloud container clusters get-credentials $CLUSTER --project=$PROJECT --region=$REGION
```

---

## 3. Artifact Registry

```bash
gcloud artifacts repositories create asya \
  --project=$PROJECT \
  --repository-format=docker \
  --location=$REGION

gcloud auth configure-docker ${REGION}-docker.pkg.dev
```

---

## 4. GCP Service Accounts

Three service accounts are required. The names below are suggestions — you can use any names,
but they must be consistent with the Kubernetes secrets and the Workload Identity annotation
created in the next steps. Asya Helm charts do not reference GCP SA names directly; they
reference the **Kubernetes secret names** that hold the JSON keys (configured in Section 5)
and the **KSA annotation** that links actor pods to the actor SA (configured below).

| SA | Purpose | Required roles | Referenced via |
|---|---|---|---|
| `asya-crossplane` | Crossplane creates/deletes Pub/Sub topics and subscriptions | `roles/pubsub.admin` | JSON key in K8s secret → `gcpProviderConfig.secretRef` |
| `asya-actor` | Actor sidecars publish/consume Pub/Sub; handlers call Vertex AI | `roles/pubsub.publisher`, `roles/pubsub.subscriber`, `roles/aiplatform.user` | WI annotation on the `default` KSA; JSON key in K8s secret for gateway |
| `asya-keda` | KEDA reads subscription backlog to drive autoscaling | `roles/monitoring.viewer`, `roles/pubsub.viewer` | JSON key in K8s secret → `pubsub.keda.secretRef` |

```bash
for sa in asya-crossplane asya-actor asya-keda; do
  gcloud iam service-accounts create $sa \
    --project=$PROJECT \
    --display-name="Asya: $sa"
done

# Crossplane
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:asya-crossplane@${PROJECT}.iam.gserviceaccount.com" \
  --role="roles/pubsub.admin" --condition=None

# Actors
for role in roles/pubsub.publisher roles/pubsub.subscriber roles/aiplatform.user; do
  gcloud projects add-iam-policy-binding $PROJECT \
    --member="serviceAccount:asya-actor@${PROJECT}.iam.gserviceaccount.com" \
    --role="$role" --condition=None
done

# KEDA
for role in roles/monitoring.viewer roles/pubsub.viewer; do
  gcloud projects add-iam-policy-binding $PROJECT \
    --member="serviceAccount:asya-keda@${PROJECT}.iam.gserviceaccount.com" \
    --role="$role" --condition=None
done
```

> `--condition=None` is required in projects with existing conditional IAM bindings;
> omitting it fails non-interactively.

### Actor Workload Identity (required)

Actor pods authenticate to Pub/Sub via **GKE Workload Identity** — no JSON key is
mounted in the sidecar. The `asya-crossplane` chart injects the actor secret via
`envFrom: secretRef`, but Kubernetes silently drops env var names containing dots
(like `sa-key.json`), so ADC falls back to the node service account which lacks
Pub/Sub permissions. Workload Identity bypasses this entirely.

```bash
kubectl create namespace $NS

# Annotate the default KSA in the actor namespace
kubectl annotate serviceaccount default \
  -n $NS \
  iam.gke.io/gcp-service-account=asya-actor@${PROJECT}.iam.gserviceaccount.com

# Bind WI User role — requires setIamPolicy on the service account
gcloud iam service-accounts add-iam-policy-binding \
  asya-actor@${PROJECT}.iam.gserviceaccount.com \
  --role=roles/iam.workloadIdentityUser \
  --member="serviceAccount:${PROJECT}.svc.id.goog[${NS}/default]" \
  --condition=None \
  --project=$PROJECT
```

> IAM changes propagate in ~60 seconds. Restart actor pods after this step if they
> were already running.

---

## 5. Credentials

Three authentication mechanisms coexist. Each exists for a distinct reason:

**Crossplane GCP provider — JSON key (`crossplane-system/gcp-creds`)**

Crossplane runs its GCP provider as a pod in `crossplane-system`, outside the actor namespace
and outside any KSA that Workload Identity is bound to. It needs to call GCP APIs (create/delete
Pub/Sub topics and subscriptions) using its own identity — a JSON key stored as a Kubernetes
Secret is the standard Crossplane credential mechanism for GCP.

**KEDA TriggerAuthentication — JSON key (`keda/gcp-keda-secret`)**

KEDA's `TriggerAuthentication` resource for GCP Pub/Sub does not yet support Workload Identity.
A JSON key is required until upstream KEDA adds WI support for the GCP Pub/Sub scaler.

**Actor sidecars — GKE Workload Identity (no secret)**

Covered in Section 4. Actor pods use the annotated `default` KSA, which transparently provides
GCP credentials via the GKE metadata server. No secret is needed in the pod.

**User secrets for actor handlers**

Actor handlers often need to call external services (LLM APIs, databases, etc.). Asya passes
these as Kubernetes Secrets mounted into actor pods via `EnvironmentConfig` flavors — the
`asya-crossplane` chart renders the secret reference into each actor's pod spec. Currently
Asya supports Kubernetes Secrets as the credential source; integration with secret stores
(Vault, GCP Secret Manager, AWS Secrets Manager) is planned.

Create the required secrets:

```bash
kubectl create namespace crossplane-system
kubectl create namespace keda

# Generate JSON keys
for sa in asya-crossplane asya-actor asya-keda; do
  gcloud iam service-accounts keys create /tmp/${sa}-key.json \
    --iam-account=${sa}@${PROJECT}.iam.gserviceaccount.com \
    --project=$PROJECT
done

# Crossplane provider credentials
kubectl create secret generic gcp-creds \
  --namespace=crossplane-system \
  --from-file=credentials.json=/tmp/asya-crossplane-key.json

# Actor handler credentials — store whatever your handlers need as a K8s Secret,
# then reference it in an EnvironmentConfig flavor (see examples/demo-kubecon/.asya/manifests/flavors/)
kubectl create secret generic asya-actor-creds \
  --namespace=$NS \
  --from-file=sa-key.json=/tmp/asya-actor-key.json

# KEDA scaler credentials
kubectl create secret generic gcp-keda-secret \
  --namespace=keda \
  --from-file=credentials.json=/tmp/asya-keda-key.json

rm /tmp/asya-*-key.json
```

---

## 6. Prerequisites

Two prerequisites must be installed before any Asya Helm chart. Both are independent
open-source projects that Asya builds on.

### Crossplane

[Crossplane](https://crossplane.io) is a Kubernetes control plane extension that lets you
manage cloud resources (GCP Pub/Sub topics, subscriptions) as Kubernetes CRDs. The
`asya-crossplane` Helm chart installs Crossplane's GCP Pub/Sub provider and the Asya
`AsyncActor` XRD and Compositions on top of it — but the Crossplane core itself must
already be present.

```bash
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm repo update crossplane-stable

helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system \
  --wait --timeout=5m
```

### KEDA

[KEDA](https://keda.sh) (Kubernetes Event-Driven Autoscaling) scales actor Deployments
based on Pub/Sub subscription backlog — scaling to 0 when a queue is empty and back up
when messages arrive. The `asya-crossplane` Helm chart generates `ScaledObject` resources
that KEDA watches; KEDA itself must be installed first.

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm repo update kedacore

helm install keda kedacore/keda \
  --namespace keda \
  --wait --timeout=5m
```

---

## 7. Asya components (two-step install)

### asya-crossplane — Step 1: providers only

Crossplane providers must reach `Healthy` before their CRDs exist and ProviderConfigs
can be created. Install with `providerConfigs.install=false` first.

```bash
helm install asya-crossplane deploy/helm-charts/asya-crossplane/ \
  --namespace=$NS \
  --set providerConfigs.install=false \
  --set providers.gcp.enabled=true \
  --set providers.gcp.pubsubVersion=v2.5.0 \
  --set gcpProviderConfig.name=default \
  --set gcpProviderConfig.projectId=$PROJECT \
  --set gcpProviderConfig.credentialsSource=Secret \
  --set gcpProviderConfig.secretRef.namespace=crossplane-system \
  --set gcpProviderConfig.secretRef.name=gcp-creds \
  --set gcpProviderConfig.secretRef.key=credentials.json \
  --set sidecar.gcpProjectId=$PROJECT \
  --set sidecar.gcpCredsSecret=asya-actor-creds \
  --set sidecar.gatewayURL=http://asya-gateway-mesh.${NS}.svc.cluster.local \
  --set functions.flavorsEnabled=true \
  --set keda.authProvider=secret \
  --set pubsub.keda.secretRef.name=gcp-keda-secret \
  --set pubsub.keda.secretRef.credentialsKey=credentials.json \
  --wait --timeout=10m
```

> **`sidecar.gatewayURL`** must be the base URL with **no path suffix**. The sidecar progress
> reporter appends `/health`, `/mesh`, `/mesh/{id}/final` etc. automatically. Setting it to
> `http://host/mesh` produces double-path URLs and silently breaks task completion callbacks.

Wait for the GCP Pub/Sub provider to become healthy:

```bash
kubectl wait provider.pkg.crossplane.io/crossplane-provider-gcp-pubsub \
  --for=condition=Healthy --timeout=300s
```

### asya-crossplane — Step 2: ProviderConfigs

```bash
helm upgrade asya-crossplane deploy/helm-charts/asya-crossplane/ \
  --namespace=$NS \
  --reuse-values \
  --set providerConfigs.install=true \
  --wait
```

### asya-crew

```bash
helm install asya-crew deploy/helm-charts/asya-crew/ \
  --namespace=$NS \
  --set image.tag=$ASYA_VERSION \
  --set "x-sink.transport=pubsub" \
  --set "x-sink.compositionSelector.matchLabels.asya\.sh/transport=pubsub" \
  --set "x-sump.transport=pubsub" \
  --set "x-sump.compositionSelector.matchLabels.asya\.sh/transport=pubsub" \
  --set "dlq-worker.enabled=false" \
  --wait --timeout=5m
```

### asya-gateway

The gateway needs PostgreSQL for task state. For a lightweight deployment, apply a minimal
in-cluster instance:

```bash
kubectl apply -n $NS -f - <<'EOF'
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: asya-gateway-postgresql
spec:
  serviceName: asya-gateway-postgresql
  replicas: 1
  selector:
    matchLabels:
      app: asya-gateway-postgresql
  template:
    metadata:
      labels:
        app: asya-gateway-postgresql
    spec:
      containers:
      - name: postgresql
        image: postgres:15-alpine
        env:
        - name: POSTGRES_DB
          value: asya_gateway
        - name: POSTGRES_USER
          value: asya
        - name: POSTGRES_PASSWORD
          value: asya-db-password
        ports:
        - containerPort: 5432
---
apiVersion: v1
kind: Service
metadata:
  name: asya-gateway-postgresql
spec:
  selector:
    app: asya-gateway-postgresql
  ports:
  - port: 5432
    targetPort: 5432
EOF
```

```bash
helm install asya-gateway deploy/helm-charts/asya-gateway/ \
  --namespace=$NS \
  --set image.tag=$ASYA_VERSION \
  --set transports.pubsub.enabled=true \
  --set "transports.pubsub.config.projectId=${PROJECT}" \
  --set postgresql.enabled=false \
  --set externalDatabase.host=asya-gateway-postgresql \
  --set externalDatabase.port=5432 \
  --set externalDatabase.database=asya_gateway \
  --set externalDatabase.username=asya \
  --set externalDatabase.password=asya-db-password \
  --set "volumes[0].name=gcp-creds" \
  --set "volumes[0].secret.secretName=asya-actor-creds" \
  --set "volumeMounts[0].name=gcp-creds" \
  --set "volumeMounts[0].mountPath=/secrets/gcp" \
  --set "volumeMounts[0].readOnly=true" \
  --set "env[0].name=GOOGLE_APPLICATION_CREDENTIALS" \
  --set "env[0].value=/secrets/gcp/sa-key.json" \
  --set service.type=LoadBalancer \
  --set "flowsConfig.flows[0].name=<flow-name>" \
  --set "flowsConfig.flows[0].entrypoint=<first-actor-queue>" \
  --set "flowsConfig.flows[0].description=<description>" \
  --set "flowsConfig.flows[0].mcp.progress=true" \
  --wait --timeout=5m
```

> The `gcp-creds` volume mount provides `GOOGLE_APPLICATION_CREDENTIALS` for the gateway's
> own Pub/Sub publisher and for any actor handlers using Vertex AI via the `vertex-ai`
> EnvironmentConfig flavor.

---

## 8. Actor Deployment

Build your actor image and push it to Artifact Registry:

```bash
docker build -t ${REGISTRY}/my-actors:latest .
docker push ${REGISTRY}/my-actors:latest
```

Compile the flow and apply manifests:

```bash
# Compile flow to AsyncActor manifests (if not already done)
asya compile src/my_flow.py

# Apply any EnvironmentConfig flavors (e.g. Vertex AI credentials)
kubectl apply -f .asya/manifests/flavors/ -n $NS

# Apply compiled AsyncActor manifests
kubectl apply -k .asya/manifests/<flow-name>/base/ -n $NS
```

> `asya compile` generates kustomize manifests under `.asya/manifests/`. Use
> `kubectl apply -k` directly if the `asya` CLI is not available on this machine.

---

## 9. Verification

```bash
# Cluster and actor status
kubectl get nodes
kubectl get asyncactors -n $NS

# Pub/Sub topics created by Crossplane
gcloud pubsub topics list --project=$PROJECT | grep asya

# Gateway IP and health
GATEWAY_IP=$(kubectl -n $NS get svc asya-gateway-api \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
curl http://${GATEWAY_IP}/health

# A2A agent card (shows registered flows)
curl http://${GATEWAY_IP}/.well-known/agent.json | python3 -m json.tool

# MCP tools list
SESSION_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
curl -s -X POST http://${GATEWAY_IP}/mcp \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: ${SESSION_ID}" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' > /dev/null
curl -s -X POST http://${GATEWAY_IP}/mcp \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: ${SESSION_ID}" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' | python3 -m json.tool

# End-to-end test via A2A — POST to /a2a/{flow-name}
curl -s -X POST http://${GATEWAY_IP}/a2a/<flow-name> \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"messageId":"test-1","role":"user","parts":[{"kind":"text","text":"hello"}]}}}' \
  | python3 -m json.tool
```

> `message/send` blocks until the flow completes — the gateway waits for the x-sink
> actor to POST back the final result. Flows using LLM calls typically take 30–120s.
