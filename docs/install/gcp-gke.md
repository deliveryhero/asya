# GKE Installation

Production or demo deployment of Asya on Google Kubernetes Engine with native GCP Pub/Sub transport.

## Prerequisites

- `gcloud` CLI configured and authenticated (`gcloud auth login`)
- `kubectl` 1.24+
- `helm` 3.14+
- `docker` (for building actor images)
- GKE cluster 1.30+ with Workload Identity enabled
- GCP APIs enabled: `container.googleapis.com`, `pubsub.googleapis.com`, `artifactregistry.googleapis.com`

To enable APIs:

```bash
gcloud services enable container.googleapis.com pubsub.googleapis.com \
  artifactregistry.googleapis.com --project=$PROJECT
```

## Reference Cluster

The `asya-demo` cluster in `foodsci-img-gen-dev-1407-1448` (europe-west1) was created with this guide and serves as the KubeCon demo environment. Use it as a reference for troubleshooting.

---

## 1. Environment Variables

Set these once before running any commands in this guide:

```bash
export PROJECT=foodsci-img-gen-dev-1407-1448
export REGION=europe-west1
export CLUSTER=asya-demo
export NETWORK=aimc-gmlp-private-network
export SUBNET=aimc-gmlp-subnet-europe-west1
export NS=asya-demo
export REGISTRY=${REGION}-docker.pkg.dev/${PROJECT}/asya-demo
```

---

## 2. Networking

### VPC and Subnet

Asya requires a VPC with at least one subnet per region. For `foodsci-img-gen-dev-1407-1448`, the shared VPC `aimc-gmlp-private-network` is used with regional subnets pre-provisioned by the platform team:

```
aimc-gmlp-private-network  (CUSTOM, REGIONAL routing)
  └─ aimc-gmlp-subnet-europe-west1  10.12.0.0/24
```

For a new project, create the VPC and subnet:

```bash
gcloud compute networks create $NETWORK \
  --project=$PROJECT \
  --subnet-mode=custom

gcloud compute networks subnets create $SUBNET \
  --project=$PROJECT \
  --network=$NETWORK \
  --region=$REGION \
  --range=10.12.0.0/24
```

### Cloud NAT (egress)

GKE nodes need egress to reach GCP APIs (Pub/Sub, Vertex AI), pull images from GHCR/Docker Hub, and download Helm chart dependencies.

**Check for an existing NAT before creating one** — in `foodsci-img-gen-dev-1407-1448` the platform team already provisions a NAT (`aimc-gmlp-nat-europe-west1`) on router `aimc-gmlp-router-europe-west1` that covers `aimc-gmlp-subnet-europe-west1`. Creating a second router+NAT on the same network/region with `ALL_SUBNETWORKS_ALL_IP_RANGES` will fail with a conflict error.

```bash
# Check for existing NAT coverage before creating
gcloud compute routers list --project=$PROJECT --filter="region:$REGION"
gcloud compute routers nats list \
  --router=<existing-router-name> \
  --router-region=$REGION \
  --project=$PROJECT
```

If no NAT exists for your subnet, create one:

```bash
gcloud compute routers create asya-router \
  --project=$PROJECT \
  --region=$REGION \
  --network=$NETWORK

gcloud compute routers nats create asya-nat \
  --project=$PROJECT \
  --router=asya-router \
  --router-region=$REGION \
  --auto-allocate-nat-external-ips \
  --nat-custom-subnet-ip-ranges=$SUBNET
```

> Using `--nat-custom-subnet-ip-ranges` instead of `--nat-all-subnet-ip-ranges` avoids conflicts
> with existing NATs on the same router.

### Current NAT config in `foodsci-img-gen-dev-1407-1448` (europe-west1)

```
Router:  aimc-gmlp-router-europe-west1
NAT:     aimc-gmlp-nat-europe-west1
  natIpAllocateOption: MANUAL_ONLY
  sourceSubnetworkIpRangesToNat: LIST_OF_SUBNETWORKS
  subnetworks:
  - aimc-gmlp-subnet-europe-west1 → ALL_IP_RANGES
```

No additional NAT configuration is needed for `asya-demo` — the existing NAT covers the cluster subnet.

---

## 3. GKE Cluster

```bash
gcloud container clusters create $CLUSTER \
  --project=$PROJECT \
  --region=$REGION \
  --num-nodes=1 \
  --machine-type=e2-standard-4 \
  --disk-size=50 \
  --disk-type=pd-standard \
  --network=$NETWORK \
  --subnetwork=$SUBNET \
  --workload-pool=${PROJECT}.svc.id.goog \
  --enable-ip-alias \
  --no-enable-master-authorized-networks \
  --release-channel=regular \
  --logging=NONE \
  --monitoring=NONE

gcloud container clusters get-credentials $CLUSTER \
  --project=$PROJECT \
  --region=$REGION
```

Notes:
- `--num-nodes=1` per zone; `europe-west1` has 3 zones, giving 3 nodes total (~12 vCPU, ~48 GB RAM)
- `--workload-pool` enables GKE Workload Identity (required for Crossplane GCP provider)
- `--logging=NONE --monitoring=NONE` removes Cloud Logging/Monitoring; fine for demos, reconsider for production
- The entity running `create` must have `roles/container.admin` on the project; it is automatically
  granted `cluster-admin` inside the new cluster

### Grant kubectl access to a service account

If your `kubectl` runs as a GCP service account (e.g. a Compute Engine default SA), it needs
`roles/container.admin` at the project level to create ClusterRoles:

```bash
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:<YOUR_SA>@developer.gserviceaccount.com" \
  --role="roles/container.admin" --condition=None
```

---

## 4. Artifact Registry

```bash
gcloud artifacts repositories create asya-demo \
  --project=$PROJECT \
  --repository-format=docker \
  --location=$REGION \
  --description="Asya actor images"

# Authenticate Docker to push
gcloud auth configure-docker ${REGION}-docker.pkg.dev
```

---

## 5. GCP Service Accounts

Three GCP service accounts are needed. All use `asya-demo-` prefix to group them by cluster/environment.

| SA | Purpose | Roles |
|---|---|---|
| `asya-demo-crossplane` | Crossplane creates/deletes Pub/Sub topics and subscriptions | `roles/pubsub.admin` |
| `asya-demo-actor` | Actor sidecars publish/consume Pub/Sub; handlers call Vertex AI | `roles/pubsub.publisher`, `roles/pubsub.subscriber`, `roles/aiplatform.user` |
| `asya-demo-keda` | KEDA reads subscription backlog to drive autoscaling | `roles/monitoring.viewer`, `roles/pubsub.viewer` |

```bash
# Create SAs
for sa in asya-demo-crossplane asya-demo-actor asya-demo-keda; do
  gcloud iam service-accounts create $sa \
    --project=$PROJECT \
    --display-name="Asya demo: $sa"
done

# Crossplane
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:asya-demo-crossplane@${PROJECT}.iam.gserviceaccount.com" \
  --role="roles/pubsub.admin" --condition=None

# Actors
for role in roles/pubsub.publisher roles/pubsub.subscriber roles/aiplatform.user; do
  gcloud projects add-iam-policy-binding $PROJECT \
    --member="serviceAccount:asya-demo-actor@${PROJECT}.iam.gserviceaccount.com" \
    --role="$role" --condition=None
done

# KEDA
for role in roles/monitoring.viewer roles/pubsub.viewer; do
  gcloud projects add-iam-policy-binding $PROJECT \
    --member="serviceAccount:asya-demo-keda@${PROJECT}.iam.gserviceaccount.com" \
    --role="$role" --condition=None
done
```

> `--condition=None` is required when the project IAM policy already contains conditional bindings
> (common in enterprise GCP organizations). Omitting it causes a non-interactive mode error.

### Actor Workload Identity (GKE)

Actor pods authenticate to Pub/Sub and Vertex AI via **GKE Workload Identity** — no JSON key is
mounted into the sidecar. The `asya-crossplane` chart injects `sidecar.gcpCredsSecret` via
`envFrom: secretRef`, but the secret key `sa-key.json` contains a dot which Kubernetes silently
drops as an invalid env var name. WI is therefore required for sidecar Pub/Sub access.

Bind the `default` Kubernetes Service Account in the actor namespace to `asya-demo-actor`:

```bash
# Annotate the default KSA — no elevated permissions required
kubectl annotate serviceaccount default \
  -n $NS \
  iam.gke.io/gcp-service-account=asya-demo-actor@${PROJECT}.iam.gserviceaccount.com

# Grant Workload Identity User — requires setIamPolicy (run from personal account)
gcloud iam service-accounts add-iam-policy-binding \
  asya-demo-actor@${PROJECT}.iam.gserviceaccount.com \
  --role=roles/iam.workloadIdentityUser \
  --member="serviceAccount:${PROJECT}.svc.id.goog[${NS}/default]" \
  --condition=None \
  --project=$PROJECT
```

IAM changes propagate in ~60 seconds. Restart actor pods after this step.

---

## 6. Credentials

Three authentication methods are used:

- **Crossplane**: JSON key secret — Crossplane provider runs outside the actor pod context
- **KEDA**: JSON key secret — KEDA's GCP Pub/Sub `TriggerAuthentication` does not yet support Workload Identity
- **Actor sidecars**: GKE Workload Identity (see Section 5) — no JSON key in the sidecar
- **Actor handlers (Vertex AI)**: JSON key via EnvironmentConfig volume mount (gateway + `asya-actor-creds` secret)

Only `asya-demo-crossplane` and `asya-demo-keda` need JSON keys stored in Kubernetes Secrets.
The `asya-actor-creds` secret is still created for the gateway's Pub/Sub publisher and the Vertex AI
EnvironmentConfig mount — it is not injected into the sidecar.

```bash
# Create namespaces first
kubectl create namespace $NS
kubectl create namespace crossplane-system
kubectl create namespace keda

# Generate keys
for sa in asya-demo-crossplane asya-demo-actor asya-demo-keda; do
  gcloud iam service-accounts keys create /tmp/${sa}-key.json \
    --iam-account=${sa}@${PROJECT}.iam.gserviceaccount.com \
    --project=$PROJECT
done

# Crossplane provider credentials
kubectl create secret generic gcp-creds \
  --namespace=crossplane-system \
  --from-file=credentials.json=/tmp/asya-demo-crossplane-key.json

# Actor credentials (Pub/Sub sidecar + Vertex AI handler)
kubectl create secret generic asya-actor-creds \
  --namespace=$NS \
  --from-file=sa-key.json=/tmp/asya-demo-actor-key.json

# KEDA scaler credentials
kubectl create secret generic gcp-keda-secret \
  --namespace=keda \
  --from-file=credentials.json=/tmp/asya-demo-keda-key.json
```

> Delete key files from `/tmp/` after storing in Kubernetes: `rm /tmp/asya-demo-*-key.json`

---

## 7. Crossplane

`asya-playground` does not bundle Crossplane. Install it first and wait for it to be healthy before
proceeding.

```bash
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm repo update crossplane-stable

helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system \
  --wait --timeout=5m
```

---

## 8. Asya components (two-step install)

Install KEDA, then asya-crossplane, asya-crew, and asya-gateway from the local chart directories.
The `asya-playground` umbrella chart can also be used once `asya.sh/charts` is published; until
then, install each chart individually as shown below.

The GCP Pub/Sub values are captured in `deploy/helm-charts/asya-playground/values-gke-pubsub.yaml`
as a reference for the per-chart flags used here.

### KEDA

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm repo update kedacore

helm install keda kedacore/keda \
  --namespace keda \
  --wait --timeout=5m
```

### asya-crossplane — Step 1: providers only (no ProviderConfigs)

Crossplane providers must reach `Healthy` before their CRDs exist and ProviderConfigs can be applied.

```bash
helm install asya-crossplane deploy/helm-charts/asya-crossplane/ \
  --namespace=$NS \
  --set providerConfigs.install=false \
  --set providers.aws.enabled=false \
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
  --set irsa.enabled=false \
  --set keda.authProvider=secret \
  --set pubsub.keda.secretRef.name=gcp-keda-secret \
  --set pubsub.keda.secretRef.credentialsKey=credentials.json \
  --wait --timeout=10m
```

Wait for the GCP Pub/Sub provider to be healthy:

```bash
kubectl wait provider.pkg.crossplane.io/crossplane-provider-gcp-pubsub \
  --for=condition=Healthy --timeout=300s
```

### asya-crossplane — Step 2: install ProviderConfigs

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
  --set image.tag=0.5.5 \
  --set "x-sink.transport=pubsub" \
  --set "x-sink.compositionSelector.matchLabels.asya\.sh/transport=pubsub" \
  --set "x-sump.transport=pubsub" \
  --set "x-sump.compositionSelector.matchLabels.asya\.sh/transport=pubsub" \
  --set "dlq-worker.enabled=false" \
  --wait --timeout=5m
```

### asya-gateway

The gateway requires exactly one transport enabled and an external PostgreSQL instance.
Deploy a minimal PostgreSQL first (or use `externalDatabase.host=""` for in-memory / no persistence):

```bash
kubectl apply -n $NS -f - <<EOF
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
  --set image.tag=0.5.5 \
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
  --set "flowsConfig.flows[0].name=text-improver" \
  --set "flowsConfig.flows[0].entrypoint=start-text-improver" \
  --set "flowsConfig.flows[0].description=Improve text through AI-powered generator-evaluator-polisher loop" \
  --set "flowsConfig.flows[0].mcp.progress=true" \
  --set "flowsConfig.flows[0].a2a.tags[0]=text" \
  --wait --timeout=5m
```

> The `image.tag` must match a published release. The gateway Helm chart defaults to `latest`
> which may be a stale image without Pub/Sub support. Pin to a specific release tag.
> Check available tags: `docker manifest inspect ghcr.io/deliveryhero/asya-gateway:<tag>`

### Fix function-asya-flavors version

The `asya-crossplane` chart pins `function-asya-flavors` to version `0.5.3` which may not be
published. If actors remain in `ReconcileError` after installation, patch the function to the
latest available version:

```bash
# Check what's available (returns "manifest unknown" if not published)
docker manifest inspect ghcr.io/deliveryhero/function-asya-flavors:0.5.5

# Patch to latest published version
kubectl patch function.pkg.crossplane.io function-asya-flavors \
  --type=merge \
  -p '{"spec":{"package":"ghcr.io/deliveryhero/function-asya-flavors:0.5.5"}}'

kubectl wait function.pkg.crossplane.io/function-asya-flavors \
  --for=condition=Healthy --timeout=120s
```

---

## 9. Demo Actors

Build and push the actor image, then deploy the compiled flow:

```bash
cd examples/demo-kubecon

# Build and push
docker build -t ${REGISTRY}/asya-demo:latest .
docker push ${REGISTRY}/asya-demo:latest

# Recompile manifests for pubsub transport (if not already done)
asya compile src/demo_flows/text_improver.py --force
```

Apply the compiled manifests and flavors:

```bash
# Apply Vertex AI EnvironmentConfig flavor first
kubectl apply -f .asya/manifests/flavors/ -n $NS

# Apply compiled AsyncActor manifests via kustomize
kubectl apply -k .asya/manifests/text-improver/base/ -n $NS
```

> `asya k apply` is a CLI shorthand that internally runs `kubectl apply -k`. Use the kubectl
> command directly if the `asya` CLI is not configured for this cluster.

After deploying, restart actor pods to pick up WI credentials if not already done:

```bash
kubectl rollout restart deployment -n $NS \
  start-text-improver generator evaluator polisher \
  router-text-improver-line-20-loop-back-0 router-text-improver-line-21-seq \
  router-text-improver-line-26-if router-text-improver-line-29-if \
  end-text-improver x-sink x-sump
```

---

## 10. Verification

```bash
# Cluster and providers
kubectl get nodes
kubectl get asyncactors -n $NS

# Pub/Sub topics created by Crossplane
gcloud pubsub topics list --project=$PROJECT | grep asya

# Gateway external IP
GATEWAY_IP=$(kubectl -n $NS get svc asya-gateway-api -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "Gateway: http://${GATEWAY_IP}"

# Health check
curl http://${GATEWAY_IP}/health

# A2A agent card (shows registered flows)
curl http://${GATEWAY_IP}/.well-known/agent.json | python3 -m json.tool

# MCP tools list
SESSION_ID="mcp-session-$(python3 -c 'import uuid; print(uuid.uuid4())')"
curl -s -X POST http://${GATEWAY_IP}/mcp \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: ${SESSION_ID}" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' > /dev/null
curl -s -X POST http://${GATEWAY_IP}/mcp \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: ${SESSION_ID}" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' | python3 -m json.tool

# End-to-end test via A2A — POST to /a2a/{flow-name}
curl -s -X POST http://${GATEWAY_IP}/a2a/text-improver \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"messageId":"test-1","role":"user","parts":[{"kind":"text","text":"Write a limerick about message queues"}]}}}' | python3 -m json.tool
```

> The A2A `message/send` call blocks until the flow completes. The text-improver flow runs
> a generator → evaluator loop → polisher via Vertex AI Gemini and typically takes 30-120s.

---

## Cost Notes

- KEDA scales actors to 0 when queues are empty — no idle compute cost for actors
- `--logging=NONE --monitoring=NONE` avoids Cloud Logging/Monitoring charges
- e2-standard-4 × 3 nodes ≈ $0.50/hr; delete the cluster after demos
- Pub/Sub first 10 GB/month free; demo traffic well within free tier
- Vertex AI Gemini API pricing applies per token; the evaluator-optimizer loop typically uses < 5000 tokens per run
