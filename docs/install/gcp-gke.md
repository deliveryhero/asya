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

**KEDA TriggerAuthentication — JSON key (`keda/gcp-keda-secret`)**

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

# KEDA scaler credentials (keda namespace)
kubectl create secret generic gcp-keda-secret \
  --namespace=keda \
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

### asya-crossplane — step 2: ProviderConfigs

```bash
helm upgrade asya-crossplane deploy/helm-charts/asya-crossplane/ \
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

helm install asya-crew deploy/helm-charts/asya-crew/ \
  --namespace=$NS \
  --set image.tag=$ASYA_VERSION \
  --set "x-sink.transport=pubsub" \
  --set "x-sink.compositionSelector.matchLabels.asya\.sh/transport=pubsub" \
  --set "x-sump.transport=pubsub" \
  --set "x-sump.compositionSelector.matchLabels.asya\.sh/transport=pubsub" \
  --set "dlq-worker.enabled=true" \
  --set "dlq-worker.config.transport=pubsub" \
  --set "dlq-worker.config.queueURL=${DLQ_SUBSCRIPTION}" \
  --set "dlq-worker.config.gcsBucket=${DLQ_GCS_BUCKET}" \
  --wait --timeout=5m
```

> The dlq-worker pod runs under the `default` KSA, which is already annotated with the
> `asya-actor` Workload Identity binding (Section 4). No additional credentials are needed.

### asya-gateway

The gateway requires PostgreSQL for task state. For production use Cloud SQL, AlloyDB,
or another managed service. For a quick in-cluster instance:

<details>
<summary>In-cluster PostgreSQL (click to expand)</summary>

```bash
kubectl create secret generic asya-gateway-postgresql \
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
              name: asya-gateway-postgresql
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

Then install the gateway, referencing the secret directly:

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
  --set externalDatabase.existingSecret=asya-gateway-postgresql \
  --set externalDatabase.existingSecretKey=password \
  --set "volumes[0].name=gcp-creds" \
  --set "volumes[0].secret.secretName=asya-actor-creds" \
  --set "volumeMounts[0].name=gcp-creds" \
  --set "volumeMounts[0].mountPath=/secrets/gcp" \
  --set "volumeMounts[0].readOnly=true" \
  --set "env[0].name=GOOGLE_APPLICATION_CREDENTIALS" \
  --set "env[0].value=/secrets/gcp/sa-key.json" \
  --set "env[1].name=ASYA_A2A_API_KEY" \
  --set "env[1].valueFrom.secretKeyRef.name=asya-gateway-auth" \
  --set "env[1].valueFrom.secretKeyRef.key=a2a-api-key" \
  --set "env[2].name=ASYA_MCP_API_KEY" \
  --set "env[2].valueFrom.secretKeyRef.name=asya-gateway-auth" \
  --set "env[2].valueFrom.secretKeyRef.key=mcp-api-key" \
  --set service.type=LoadBalancer \
  --wait --timeout=5m
```

### Gateway security

`asya-gateway` is deployed as two separate Deployments from the same binary:

| Deployment | Service | Reachable from | Auth |
|---|---|---|---|
| `asya-gateway-api` | LoadBalancer (port 80) | External clients, LLMs, AI agents | API key / JWT Bearer |
| `asya-gateway-mesh` | ClusterIP | Actor sidecars only (in-cluster DNS) | None — network isolation |

**Protected routes** (`asya-gateway-api`): all `/a2a/*` and `/mcp/*` routes require
authentication when `ASYA_A2A_API_KEY` / `ASYA_MCP_API_KEY` are set.

**Always public**: `/.well-known/agent.json` (A2A spec requirement) and `/health`
(K8s probes).

Clients must send the API key in the `X-API-Key` header for A2A, or
`Authorization: Bearer <key>` for MCP:

```bash
A2A_KEY=$(kubectl get secret asya-gateway-auth -n $NS \
  -o jsonpath='{.data.a2a-api-key}' | base64 -d)

curl -X POST http://${GATEWAY_IP}/a2a/hello \
  -H "X-API-Key: $A2A_KEY" \
  -H "Content-Type: application/json" \
  -d '...'
```

**For production exposure** (beyond a local demo), configure HTTPS before sharing
the gateway URL externally:

- **GCP-managed certificate**: annotate the Service or Ingress with
  `networking.gke.io/managed-certificates` pointing to a `ManagedCertificate` resource.
  Requires a domain name with an A record pointing at the LoadBalancer IP.
- **cert-manager + Ingress**: standard Kubernetes approach, works with Let's Encrypt.
- The MCP OAuth 2.1 flow (already implemented in the gateway) formally requires HTTPS
  — HTTP is acceptable for API key auth but not for OAuth redirect URIs.

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
def handle(payload: dict) -> dict:
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
  transport: pubsub
  compositionSelector:
    matchLabels:
      asya.sh/transport: pubsub

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

Register the `hello` flow with the gateway. The gateway hot-reloads its
`flows.yaml` ConfigMap — patching it is all that's needed:

```bash
kubectl patch configmap asya-gateway-flows -n $NS --type merge -p '
data:
  flows.yaml: |
    flows:
    - name: hello
      entrypoint: hello
      description: A simple hello world actor
      mcp:
        progress: true
'
```

Send a test message via the gateway:

```bash
GATEWAY_IP=$(kubectl -n $NS get svc asya-gateway-api \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
A2A_KEY=$(kubectl get secret asya-gateway-auth -n $NS \
  -o jsonpath='{.data.a2a-api-key}' | base64 -d)

curl -s -X POST http://${GATEWAY_IP}/a2a/hello \
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

# Gateway IP and API keys
GATEWAY_IP=$(kubectl -n $NS get svc asya-gateway-api \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
A2A_KEY=$(kubectl get secret asya-gateway-auth -n $NS \
  -o jsonpath='{.data.a2a-api-key}' | base64 -d)
MCP_KEY=$(kubectl get secret asya-gateway-auth -n $NS \
  -o jsonpath='{.data.mcp-api-key}' | base64 -d)

# Health (public, no key needed)
curl http://${GATEWAY_IP}/health

# A2A agent card (public, no key needed)
curl http://${GATEWAY_IP}/.well-known/agent.json | python3 -m json.tool

# MCP tools list (requires MCP key)
SESSION_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
curl -s -X POST http://${GATEWAY_IP}/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $MCP_KEY" \
  -H "Mcp-Session-Id: ${SESSION_ID}" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' > /dev/null
curl -s -X POST http://${GATEWAY_IP}/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $MCP_KEY" \
  -H "Mcp-Session-Id: ${SESSION_ID}" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' | python3 -m json.tool

# End-to-end test via A2A (requires A2A key)
curl -s -X POST http://${GATEWAY_IP}/a2a/hello \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $A2A_KEY" \
  -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"messageId":"test-1","role":"user","parts":[{"kind":"text","text":"hello"}]}}}' \
  | python3 -m json.tool
```

> `message/send` blocks until the flow completes — the gateway waits for the x-sink
> actor to POST back the final result. Flows using LLM calls typically take 30–120s.
