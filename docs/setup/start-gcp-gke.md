---
description: "GCP GKE deployment: production setup, Workload Identity, Pub/Sub transport, GCS storage"
---

# GKE + GCP Pub/Sub Installation

Deploy Asya on Google Kubernetes Engine using native GCP Pub/Sub as the message transport.

For a full map of all secrets, service accounts, and namespaces, see
[Credentials Reference](../reference/credentials.md).

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
| `asya-crossplane` | Crossplane creates/deletes Pub/Sub topics and subscriptions | `roles/pubsub.admin` | JSON key in K8s secret → `gcpProviderConfig.secretRef` (default); or WI via `credentialsSource: InjectedIdentity` (see Section 5) |
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

Several authentication mechanisms coexist. Each exists for a distinct reason:

**Crossplane GCP provider — JSON key (`crossplane-system/gcp-creds`)**

The Crossplane GCP provider supports both `credentialsSource: Secret` (JSON key) and
`credentialsSource: InjectedIdentity` (Workload Identity). WI is preferable in production,
but has a bootstrapping constraint: the provider pod's Kubernetes Service Account is
**auto-generated by Crossplane at install time** with a hash suffix
(`crossplane-provider-gcp-pubsub-<hash>`). You cannot annotate it with a GCP SA before
installing the provider — it doesn't exist yet. Using WI requires a two-phase setup:
install the provider first, look up the generated KSA name, bind WI, then reconfigure
the ProviderConfig. A JSON key avoids this ordering dependency and is simpler to start with.

To switch to Workload Identity after the provider is `Healthy`:

```bash
PROVIDER_KSA=$(kubectl get sa -n crossplane-system \
  -o name | grep crossplane-provider-gcp-pubsub | head -1 | cut -d/ -f2)

kubectl annotate serviceaccount $PROVIDER_KSA -n crossplane-system \
  iam.gke.io/gcp-service-account=asya-crossplane@${PROJECT}.iam.gserviceaccount.com

gcloud iam service-accounts add-iam-policy-binding \
  asya-crossplane@${PROJECT}.iam.gserviceaccount.com \
  --role=roles/iam.workloadIdentityUser \
  --member="serviceAccount:${PROJECT}.svc.id.goog[crossplane-system/${PROVIDER_KSA}]" \
  --condition=None --project=$PROJECT
```

Then set `--set gcpProviderConfig.credentialsSource=InjectedIdentity` and drop the `secretRef`
flags from the `helm upgrade` command. The JSON key approach below works without this extra step.

**KEDA TriggerAuthentication — JSON key (actor namespace — TriggerAuthentication references it locally)**

KEDA's `TriggerAuthentication` resource for GCP Pub/Sub does not yet support Workload Identity.
A JSON key is required until upstream KEDA adds WI support for the GCP Pub/Sub scaler.

**Actor sidecars — GKE Workload Identity (no secret)**

Covered in Section 4. Actor pods use the annotated `default` KSA, which transparently provides
GCP credentials via the GKE metadata server. No secret is needed in the pod.

**User secrets for actor handlers**

Actor handlers often need credentials for external services (LLM APIs, databases, etc.).
Create a Kubernetes Secret in your actor namespace (`$NS`) and reference it in your
`AsyncActor` spec via standard `env` or `envFrom` — Asya renders these directly into the
actor pod. EnvironmentConfig flavors are cluster-scoped and not the recommended mechanism
for per-namespace secrets. Integration with external secret stores (Vault, GCP Secret Manager,
AWS Secrets Manager) is planned.

Create the required secrets:

```bash
kubectl create namespace crossplane-system
kubectl create namespace keda

# Generate JSON keys for Crossplane and KEDA
for sa in asya-crossplane asya-actor asya-keda; do
  gcloud iam service-accounts keys create /tmp/${sa}-key.json \
    --iam-account=${sa}@${PROJECT}.iam.gserviceaccount.com \
    --project=$PROJECT
done

# Crossplane provider credentials (crossplane-system namespace)
kubectl create secret generic gcp-creds \
  --namespace=crossplane-system \
  --from-file=credentials.json=/tmp/asya-crossplane-key.json

# GCP credentials for the gateway and actor handlers that call GCP APIs (actor namespace)
kubectl create secret generic asya-actor-creds \
  --namespace=$NS \
  --from-file=sa-key.json=/tmp/asya-actor-key.json

# KEDA scaler credentials (actor namespace — TriggerAuthentication references it locally)
kubectl create secret generic gcp-keda-secret \
  --namespace=$NS \
  --from-file=credentials.json=/tmp/asya-keda-key.json

rm /tmp/asya-*-key.json

# Gateway API keys — stored in a Secret, never in Helm values or shell history
kubectl create secret generic asya-gateway-auth \
  --namespace=$NS \
  --from-literal=a2a-api-key=$(openssl rand -hex 24) \
  --from-literal=mcp-api-key=$(openssl rand -hex 24)
```

For any other handler secrets (API keys, database passwords, etc.), create them in `$NS`
the same way and reference them in your `AsyncActor` spec:

```yaml
spec:
  env:
  - name: MY_API_KEY
    valueFrom:
      secretKeyRef:
        name: my-secret
        key: api-key
```

---

## 6. Prerequisites

Two prerequisites must be installed before any Asya Helm chart. Both are independent
open-source projects that Asya builds on.

### 🍭 Crossplane

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

### ⚡ KEDA

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

## 7. 🎭 Asya components  (two-step install)

### asya-crossplane — step 1: providers only

Crossplane providers must reach `Healthy` before their CRDs exist and ProviderConfigs
can be created. Install with `providerConfigs.install=false` first.

```bash
helm repo add asya https://asya.sh/charts
helm repo update asya

helm install asya-crossplane asya/asya-crossplane --version $ASYA_VERSION \
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
  --set functions.flavorsEnabled=true \
  --set keda.authProvider=secret \
  --set pubsub.keda.secretRef.name=gcp-keda-secret \
  --set pubsub.keda.secretRef.credentialsKey=credentials.json \
  --wait --timeout=10m
```

> Sidecars no longer need a gateway URL at install time. The mesh-api stamps its
> internal callback URL (`asya-gateway-mesh-api-int`) into the `x-asya-gateway-url`
> envelope header on every task it creates, and the sidecar reads it from there.

Wait for the GCP Pub/Sub provider to become healthy:

```bash
kubectl wait provider.pkg.crossplane.io/provider-gcp-pubsub \
  --for=condition=Healthy --timeout=300s
```

### asya-crossplane — step 2: ProviderConfigs

```bash
helm upgrade asya-crossplane asya/asya-crossplane --version $ASYA_VERSION \
  --namespace=$NS \
  --reuse-values \
  --set providerConfigs.install=true \
  --wait
```

### asya-crew

The `dlq-worker` archives envelopes that land in the Pub/Sub dead letter topic — those are
messages where the sidecar itself crashed before acking, bypassing the normal `x-sump` path.

**Set up a dead letter topic and subscription before installing asya-crew:**

```bash
# Dead letter topic — receives messages after maxDeliveryAttempts failures
gcloud pubsub topics create asya-dlq --project=$PROJECT

# Dead letter subscription for the dlq-worker to pull from
gcloud pubsub subscriptions create asya-dlq-pull \
  --topic=asya-dlq \
  --project=$PROJECT

# GCS bucket for archiving failed envelopes (optional, stdout mode if omitted)
gcloud storage buckets create gs://asya-dlq-${PROJECT} \
  --project=$PROJECT \
  --location=$REGION

# Grant the actor SA permission to write to the DLQ bucket
gcloud storage buckets add-iam-policy-binding gs://asya-dlq-${PROJECT} \
  --member="serviceAccount:asya-actor@${PROJECT}.iam.gserviceaccount.com" \
  --role=roles/storage.objectCreator

# Grant the actor SA permission to pull from the dead letter subscription and ack messages
for role in roles/pubsub.subscriber roles/pubsub.viewer; do
  gcloud projects add-iam-policy-binding $PROJECT \
    --member="serviceAccount:asya-actor@${PROJECT}.iam.gserviceaccount.com" \
    --role="$role" --condition=None
done
```

> To attach the dead letter policy to an existing subscription:
> `gcloud pubsub subscriptions modify-push-config my-sub --dead-letter-topic=asya-dlq --max-delivery-attempts=5`
> Each `AsyncActor`'s subscription must be updated individually after the DLQ topic exists.

```bash
export DLQ_SUBSCRIPTION="projects/${PROJECT}/subscriptions/asya-dlq-pull"
export DLQ_GCS_BUCKET="asya-dlq-${PROJECT}"

helm install asya-crew asya/asya-crew --version $ASYA_VERSION \
  --namespace=$NS \
  --set image.tag=$ASYA_VERSION \
  --set "dlq-worker.enabled=true" \
  --set "dlq-worker.config.queueURL=${DLQ_SUBSCRIPTION}" \
  --set "dlq-worker.config.gcsBucket=${DLQ_GCS_BUCKET}" \
  --wait --timeout=5m
```

> The dlq-worker pod runs under the `default` KSA, which is already annotated with the
> `asya-actor` Workload Identity binding (Section 4). No additional credentials are needed.

### asya-gateway

The gateway is one image (`asya-gateway`) that runs as several containers in a
single pod: `mesh-api` (core HTTP), optional `mcp-adapter` and `a2a-adapter`, and a
`state-proxy-mesh` sidecar. Task state is pluggable via `stateProxy.mesh.backend`:

- **`pvc-kv`** — local files / in-memory, **no database**. Simplest to start with
  (requires `replicaCount: 1`).
- **`pg-kv`** _(default)_ — PostgreSQL. For production use Cloud SQL, AlloyDB, or
  another managed service.

The gateway publishes envelopes to Pub/Sub, so its Service Account needs Pub/Sub
publish access. Bind the gateway SA to the `asya-actor` GCP SA via Workload Identity
(the chart creates an SA named `asya-gateway` by default):

```bash
kubectl annotate serviceaccount asya-gateway -n $NS \
  iam.gke.io/gcp-service-account=asya-actor@${PROJECT}.iam.gserviceaccount.com \
  --overwrite 2>/dev/null || true

gcloud iam service-accounts add-iam-policy-binding \
  asya-actor@${PROJECT}.iam.gserviceaccount.com \
  --role=roles/iam.workloadIdentityUser \
  --member="serviceAccount:${PROJECT}.svc.id.goog[${NS}/asya-gateway]" \
  --condition=None --project=$PROJECT
```

> If the SA does not exist yet, install the gateway first (below), then run the
> annotate/bind commands and `kubectl rollout restart deployment/asya-gateway -n $NS`.

#### Option A: pvc-kv (no PostgreSQL)

```bash
helm install asya-gateway asya/asya-gateway --version $ASYA_VERSION \
  --namespace=$NS \
  --set replicaCount=1 \
  --set stateProxy.mesh.backend=pvc-kv \
  --set transports.pubsub.enabled=true \
  --set "transports.pubsub.config.projectId=${PROJECT}" \
  --set mcp.enabled=true \
  --set a2a.enabled=true \
  --set a2a.auth.apiKey=$(kubectl get secret asya-gateway-auth -n $NS \
        -o jsonpath='{.data.a2a-api-key}' | base64 -d) \
  --set ingress.enabled=true \
  --set ingress.host=<your-gateway-host> \
  --wait --timeout=5m
```

#### Option B: pg-kv (PostgreSQL)

For PostgreSQL state, point the `database.*` values at your instance. For a quick
in-cluster instance, create a Secret and StatefulSet first:

<details>
<summary>In-cluster PostgreSQL (click to expand)</summary>

```bash
kubectl create secret generic asya-gateway-db \
  --namespace=$NS \
  --from-literal=password=$(openssl rand -hex 16)

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
          valueFrom:
            secretKeyRef:
              name: asya-gateway-db
              key: password
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
          subPath: pgdata
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: [ReadWriteOnce]
      resources:
        requests:
          storage: 5Gi
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
EOF
```

</details>

```bash
helm install asya-gateway asya/asya-gateway --version $ASYA_VERSION \
  --namespace=$NS \
  --set stateProxy.mesh.backend=pg-kv \
  --set database.host=asya-gateway-postgresql \
  --set database.port=5432 \
  --set database.name=asya_gateway \
  --set database.username=asya \
  --set database.existingSecret=asya-gateway-db \
  --set database.existingSecretKey=password \
  --set transports.pubsub.enabled=true \
  --set "transports.pubsub.config.projectId=${PROJECT}" \
  --set mcp.enabled=true \
  --set a2a.enabled=true \
  --set a2a.auth.apiKey=$(kubectl get secret asya-gateway-auth -n $NS \
        -o jsonpath='{.data.a2a-api-key}' | base64 -d) \
  --set ingress.enabled=true \
  --set ingress.host=<your-gateway-host> \
  --wait --timeout=5m
```

### Gateway security

The gateway exposes four ClusterIP Services from the single pod:

| Service | Port | Reachable from | Auth |
|---|---|---|---|
| `asya-gateway-mesh-api` | 8080 | External clients (via Ingress) | None on mesh-api itself |
| `asya-gateway-mesh-api-int` | 8081 | Actor sidecars only (in-cluster DNS) | None — network isolation |
| `asya-gateway-mcp` | 8082 | MCP clients (via Ingress) | None currently wired |
| `asya-gateway-a2a` | 8083 | A2A clients (via Ingress) | API key / JWT Bearer |

External traffic is exposed through the Ingress (`ingress.enabled=true`), not a
per-Service LoadBalancer. The `asya-gateway-mesh-api-int` Service has no Ingress and
is unreachable from outside the cluster.

**A2A auth** is configured via `a2a.auth.apiKey` (→ `ASYA_A2A_API_KEY`) or
`a2a.auth.jwt.*`. When set, clients must send the API key in the `X-API-Key` header.
MCP auth is not currently wired in the mcp-adapter.

```bash
A2A_KEY=$(kubectl get secret asya-gateway-auth -n $NS \
  -o jsonpath='{.data.a2a-api-key}' | base64 -d)

curl -X POST https://<your-gateway-host>/a2a/ \
  -H "X-API-Key: $A2A_KEY" \
  -H "Content-Type: application/json" \
  -d '...'
```

**For production exposure** (beyond a local demo), terminate TLS at the Ingress
before sharing the gateway URL externally:

- **GCP-managed certificate**: annotate the Ingress with
  `networking.gke.io/managed-certificates` pointing to a `ManagedCertificate` resource.
  Requires a domain name with an A record pointing at the Ingress IP.
- **cert-manager + Ingress**: standard Kubernetes approach, works with Let's Encrypt.

---

## 8. Actor Deployment

The following creates a minimal `hello` actor that reads a name from the payload and
returns a greeting. Use it to verify the full message path: Pub/Sub → sidecar → handler
→ sidecar → x-sink.

```bash
mkdir hello-actor && cd hello-actor
```

**`handler.py`** — the actor handler:

```python
async def handle(payload: dict) -> dict:
    name = payload.get("name", "world")
    return {"greeting": f"Hello, {name}!"}
```

**`Dockerfile`**:

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY handler.py .
```

**`actor.yaml`** — the AsyncActor manifest:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: hello
  namespace: <your-namespace>
spec:
  actor: hello
  scaling:
    enabled: true
    minReplicaCount: 0
    maxReplicaCount: 3
  image: <REGISTRY>/hello-actor:latest
  handler: handler.handle
```

Build, push, and deploy:

```bash
docker build -t ${REGISTRY}/hello-actor:latest .
docker push ${REGISTRY}/hello-actor:latest

kubectl apply -f actor.yaml -n $NS
```

Watch the actor become ready (Crossplane creates the Pub/Sub topic and subscription):

```bash
kubectl get asyncactor hello -n $NS -w
```

Register the `hello` flow with the gateway as an MCP tool and/or A2A agent. Tool and
agent definitions are mounted as ConfigMaps into the mcp-adapter and a2a-adapter and
hot-reloaded — see the [Gateway Setup Guide](guide-gateway.md) for how to compile and
register flows.

Send a test message via the gateway (replace `<your-gateway-host>` with the
`ingress.host` you set above; for a quick local check, `kubectl port-forward
svc/asya-gateway-a2a 8083:8083 -n $NS` and use `localhost:8083`):

```bash
A2A_KEY=$(kubectl get secret asya-gateway-auth -n $NS \
  -o jsonpath='{.data.a2a-api-key}' | base64 -d)

curl -s -X POST https://<your-gateway-host>/a2a/ \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $A2A_KEY" \
  -d '{"jsonrpc":"2.0","id":"1","method":"message/send","params":{
    "message":{"messageId":"test-1","role":"user",
      "parts":[{"kind":"text","text":"world"}]}}}' \
  | python3 -m json.tool
```

---

## 9. Verification

```bash
# Cluster and actor status
kubectl get nodes
kubectl get asyncactors -n $NS

# Pub/Sub topics created by Crossplane
gcloud pubsub topics list --project=$PROJECT | grep asya

# Gateway host (the ingress.host you set) and A2A key.
# External traffic is path-routed by the Ingress to the per-protocol services:
#   /mcp -> asya-gateway-mcp, /a2a/ + /.well-known/agent.json -> asya-gateway-a2a
GATEWAY_HOST=<your-gateway-host>
A2A_KEY=$(kubectl get secret asya-gateway-auth -n $NS \
  -o jsonpath='{.data.a2a-api-key}' | base64 -d)

# A2A agent card (public, no key needed)
curl https://${GATEWAY_HOST}/.well-known/agent.json | python3 -m json.tool

# MCP tools list (MCP auth is not currently wired in the adapter)
SESSION_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
curl -s -X POST https://${GATEWAY_HOST}/mcp \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: ${SESSION_ID}" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' > /dev/null
curl -s -X POST https://${GATEWAY_HOST}/mcp \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: ${SESSION_ID}" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' | python3 -m json.tool

# End-to-end test via A2A (requires A2A key)
curl -s -X POST https://${GATEWAY_HOST}/a2a/ \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $A2A_KEY" \
  -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"messageId":"test-1","role":"user","parts":[{"kind":"text","text":"hello"}]}}}' \
  | python3 -m json.tool
```

> `message/send` blocks until the flow completes — the gateway waits for the x-sink
> actor to POST back the final result. Flows using LLM calls typically take 30–120s.
