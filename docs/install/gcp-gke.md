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

---

## 6. Credentials

Generate JSON keys and store them as Kubernetes Secrets. JSON keys are used because GKE Workload
Identity for KEDA's `TriggerAuthentication` is not yet supported; key-based auth is used consistently
across all three components for simplicity.

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

## 8. asya-playground (two-step install)

The `asya-playground` chart bundles KEDA, asya-crossplane, asya-crew, and asya-gateway.

The GCP Pub/Sub configuration is in `deploy/helm-charts/asya-playground/values-gke-pubsub.yaml`.

### Step 1 — Install providers (ProviderConfigs off)

Crossplane providers must reach `Healthy` before their CRDs exist and ProviderConfigs can be applied.

```bash
helm repo add asya https://asya.sh/charts
helm repo update asya

helm install asya-demo deploy/helm-charts/asya-playground/ \
  --namespace=$NS \
  --values=deploy/helm-charts/asya-playground/values-gke-pubsub.yaml \
  --set asya-crossplane.providerConfigs.install=false \
  --wait --timeout=10m
```

Wait for the GCP Pub/Sub provider to become healthy:

```bash
kubectl wait provider.pkg.crossplane.io/crossplane-provider-gcp-pubsub \
  --for=condition=Healthy \
  --timeout=300s
```

### Step 2 — Install ProviderConfigs

```bash
helm upgrade asya-demo deploy/helm-charts/asya-playground/ \
  --namespace=$NS \
  --values=deploy/helm-charts/asya-playground/values-gke-pubsub.yaml \
  --set asya-crossplane.providerConfigs.install=true \
  --wait
```

---

## 9. Demo Actors

Build and push the actor image, then deploy the compiled flow:

```bash
cd examples/demo-kubecon

# Build and push
docker build -t ${REGISTRY}/asya-demo:latest .
docker push ${REGISTRY}/asya-demo:latest

# Deploy
asya compile src/demo_flows/text_improver.py --force
asya k apply src/demo_flows/text_improver.py
```

Apply the Vertex AI EnvironmentConfig flavor:

```bash
kubectl apply -f .asya/manifests/flavors/ -n $NS
```

---

## 10. Verification

```bash
# Cluster and providers
kubectl get nodes
kubectl get providers -n crossplane-system

# Actor readiness
kubectl -n $NS get asyncactors

# Pub/Sub topics created by Crossplane
gcloud pubsub topics list --project=$PROJECT | grep asya

# Gateway endpoint
kubectl -n $NS get svc asya-demo-asya-gateway
curl http://<EXTERNAL_IP>/health
curl http://<EXTERNAL_IP>/mcp/tools

# End-to-end test
asya k send start-text-improver '{"task": "Write a limerick about message queues"}'
asya k logs --follow
```

---

## Cost Notes

- KEDA scales actors to 0 when queues are empty — no idle compute cost for actors
- `--logging=NONE --monitoring=NONE` avoids Cloud Logging/Monitoring charges
- e2-standard-4 × 3 nodes ≈ $0.50/hr; delete the cluster after demos
- Pub/Sub first 10 GB/month free; demo traffic well within free tier
- Vertex AI Gemini API pricing applies per token; the evaluator-optimizer loop typically uses < 5000 tokens per run
