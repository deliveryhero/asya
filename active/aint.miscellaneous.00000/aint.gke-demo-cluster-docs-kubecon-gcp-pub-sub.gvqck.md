---
title: "GKE demo cluster + docs: KubeCon GCP Pub/Sub deployment"
status: working
priority: 1
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/misc/gvqc.gke-demo-cluster-docs-kubecon-gcp-pub-sub
  - branch:misc/gvqc.gke-demo-cluster-docs-kubecon-gcp-pub-sub
---

## Goal

Stand up a minimal CPU-only GKE cluster in `foodsci-img-gen-dev-1407-1448` running the
KubeCon demo (`examples/demo-kubecon` from `docs-demo` branch) with native GCP Pub/Sub
as transport. Produce a new install guide (`docs/install/gke.md`) modelled on
`docs/install/aws-eks.md`, and critically fix that EKS doc in the same PR.

**Blocked on**: merging `docs-demo` branch first (fixes tests WIP).


## Context

- Project: `foodsci-img-gen-dev-1407-1448`
- Network: `aimc-gmlp-private-network`, subnet `aimc-gmlp-subnet-europe-west1` (`10.12.0.0/24`)
- Region: `europe-west1`
- Transport: GCP Pub/Sub (native, no LocalStack)
- Vertex AI: already enabled in project, region `europe-west1`
- Demo: `examples/demo-kubecon` — text-improver flow (generator -> evaluator loop -> polisher)
- Helm install strategy: `asya-playground` chart for all infrastructure, demo actors on top


## Execution Plan

### Prerequisites (one-time env vars)

```bash
export PROJECT=foodsci-img-gen-dev-1407-1448
export REGION=europe-west1
export CLUSTER=asya-demo
export NETWORK=aimc-gmlp-private-network
export SUBNET=aimc-gmlp-subnet-europe-west1
export NS=asya-demo
export REGISTRY=${REGION}-docker.pkg.dev/${PROJECT}/asya-demo
```


### Phase 1 - GKE Cluster

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
- `--num-nodes=1` per zone; europe-west1 has 3 zones so 3 nodes total (~12 vCPU headroom)
- `--logging=NONE --monitoring=NONE` disables Cloud Logging/Monitoring to cut demo costs
- `--workload-pool` enables GKE Workload Identity (no SA key files stored in cluster)


### Phase 2 - Cloud NAT (egress for Pub/Sub API, GHCR image pulls, Vertex AI)

```bash
gcloud compute routers create asya-demo-router \
  --project=$PROJECT \
  --region=$REGION \
  --network=$NETWORK

gcloud compute routers nats create asya-demo-nat \
  --project=$PROJECT \
  --router=asya-demo-router \
  --region=$REGION \
  --auto-allocate-nat-external-ips \
  --nat-all-subnet-ip-ranges
```


### Phase 3 - Artifact Registry (demo actor image)

```bash
gcloud artifacts repositories create asya-demo \
  --project=$PROJECT \
  --repository-format=docker \
  --location=$REGION \
  --description="KubeCon demo actor image"

gcloud auth configure-docker ${REGION}-docker.pkg.dev
```


### Phase 4 - Workload Identity: GCP service accounts

#### 4a. Crossplane GSA - manages Pub/Sub topics/subscriptions declaratively

```bash
gcloud iam service-accounts create crossplane-gcp \
  --project=$PROJECT \
  --display-name="Crossplane GCP Pub/Sub provider"

gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:crossplane-gcp@${PROJECT}.iam.gserviceaccount.com" \
  --role="roles/pubsub.admin"

# Bind to the KSA Crossplane creates when it installs the GCP provider
gcloud iam service-accounts add-iam-policy-binding \
  crossplane-gcp@${PROJECT}.iam.gserviceaccount.com \
  --project=$PROJECT \
  --role="roles/iam.workloadIdentityUser" \
  --member="serviceAccount:${PROJECT}.svc.id.goog[crossplane-system/crossplane-gcp-provider]"
```

#### 4b. Actor workload GSA - Pub/Sub + Vertex AI

```bash
gcloud iam service-accounts create asya-actor \
  --project=$PROJECT \
  --display-name="Asya demo actors"

for role in roles/pubsub.publisher roles/pubsub.subscriber roles/aiplatform.user; do
  gcloud projects add-iam-policy-binding $PROJECT \
    --member="serviceAccount:asya-actor@${PROJECT}.iam.gserviceaccount.com" \
    --role="$role"
done

# Bind to the KSA used by actor pods (created in Phase 8)
gcloud iam service-accounts add-iam-policy-binding \
  asya-actor@${PROJECT}.iam.gserviceaccount.com \
  --project=$PROJECT \
  --role="roles/iam.workloadIdentityUser" \
  --member="serviceAccount:${PROJECT}.svc.id.goog[${NS}/asya-actor]"
```

#### 4c. KEDA GSA - reads Pub/Sub subscription backlog for autoscaling decisions

KEDA's GCP Pub/Sub scaler does not yet support Workload Identity via TriggerAuthentication;
a JSON key is the current supported path for KEDA.

```bash
gcloud iam service-accounts create keda-gcp \
  --project=$PROJECT \
  --display-name="KEDA GCP Pub/Sub scaler"

gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:keda-gcp@${PROJECT}.iam.gserviceaccount.com" \
  --role="roles/monitoring.viewer"

gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:keda-gcp@${PROJECT}.iam.gserviceaccount.com" \
  --role="roles/pubsub.viewer"

gcloud iam service-accounts keys create /tmp/keda-gcp-sa.json \
  --iam-account=keda-gcp@${PROJECT}.iam.gserviceaccount.com

kubectl create namespace keda --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic gcp-keda-secret \
  --namespace=keda \
  --from-file=credentials.json=/tmp/keda-gcp-sa.json
```


### Phase 5 - Crossplane (prerequisite: must exist before asya-playground)

asya-playground does NOT bundle Crossplane itself; it must be installed first.

```bash
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm repo update

helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system --create-namespace \
  --wait
```


### Phase 6 - asya-playground step 1: install providers, not yet ProviderConfigs

Create `deploy/helm-charts/asya-playground/values-gke-pubsub.yaml` (commit alongside docs):

```yaml
global:
  transport: pubsub
  profile: production

sampleTransport:
  sqsLocalstack:
    enabled: false
  rabbitmq:
    enabled: false

sampleStorage:
  s3Localstack:
    enabled: false
  minio:
    enabled: false

enableAsyaCrew: true
enableAsyaGateway: true

sampleGatewayDb:
  postgresql:
    enabled: true   # lightweight in-cluster Postgres; no Cloud SQL needed for demo

asya-crossplane:
  providerConfigs:
    install: false  # step 1: providers must be Healthy before ProviderConfigs can be applied
  providers:
    aws:
      enabled: false
    gcp:
      enabled: true
      pubsubVersion: "v2.5.0"
  gcpProviderConfig:
    name: default
    projectId: "foodsci-img-gen-dev-1407-1448"
    credentialsSource: InjectedIdentity   # Workload Identity - no key file in cluster
  sidecar:
    gcpProjectId: "foodsci-img-gen-dev-1407-1448"
  functions:
    flavorsEnabled: true
  irsa:
    enabled: false
  keda:
    authProvider: secret
  pubsub:
    keda:
      secretRef:
        name: gcp-keda-secret
        credentialsKey: credentials.json

asya-crew:
  x-sink:
    transport: pubsub
    sidecar:
      serviceAccountName: asya-actor
  x-sump:
    transport: pubsub
    sidecar:
      serviceAccountName: asya-actor
  dlq-worker:
    enabled: false

asya-gateway:
  replicaCount: 1
  service:
    type: LoadBalancer
  externalDatabase:
    host: asya-demo-postgresql
    port: 5432
    database: asya_gateway
    username: asya
    password: asya-db-password
  routes:
    createConfigMap: true
    defaults:
      progress: true
      timeout: 120
    tools:
    - name: text-improver
      description: "Improve text through AI-powered generator-evaluator-polisher loop"
      parameters:
        task:
          type: string
          required: true
          description: "Text improvement task description"
      route: ["start-text-improver"]
```

```bash
helm repo add asya https://asya.sh/charts
helm repo update

kubectl create namespace $NS --dry-run=client -o yaml | kubectl apply -f -

helm install asya-demo deploy/helm-charts/asya-playground/ \
  --namespace=$NS \
  --values=deploy/helm-charts/asya-playground/values-gke-pubsub.yaml \
  --wait
```

Wait for GCP Pub/Sub provider to be healthy:
```bash
kubectl wait provider.pkg.crossplane.io/crossplane-provider-gcp-pubsub \
  --for=condition=Healthy \
  --timeout=300s
```


### Phase 7 - asya-playground step 2: install ProviderConfigs

```bash
helm upgrade asya-demo deploy/helm-charts/asya-playground/ \
  --namespace=$NS \
  --values=deploy/helm-charts/asya-playground/values-gke-pubsub.yaml \
  --set asya-crossplane.providerConfigs.install=true \
  --wait

# Annotate Crossplane's GCP provider KSA for Workload Identity
kubectl annotate serviceaccount crossplane-gcp-provider \
  --namespace=crossplane-system \
  iam.gke.io/gcp-service-account=crossplane-gcp@${PROJECT}.iam.gserviceaccount.com
```


### Phase 8 - Demo actor image: build and push

After `docs-demo` merges into main:

```bash
cd examples/demo-kubecon
docker build -t ${REGISTRY}/asya-demo:latest .
docker push ${REGISTRY}/asya-demo:latest
```

Create and annotate the actor KSA:
```bash
kubectl create serviceaccount asya-actor --namespace=$NS --dry-run=client -o yaml | \
  kubectl apply -f -

kubectl annotate serviceaccount asya-actor \
  --namespace=$NS \
  iam.gke.io/gcp-service-account=asya-actor@${PROJECT}.iam.gserviceaccount.com
```


### Phase 9 - Demo config changes (two files to update in examples/demo-kubecon/)

**`.asya/config.yaml`**: change transport + image:
```yaml
templates:
  namespace: asya-demo
  transport: pubsub    # was: sqs
  router_image: "python:3.13-slim"
  max_replicas: 5

build:
- module: "*"
  image: "europe-west1-docker.pkg.dev/foodsci-img-gen-dev-1407-1448/asya-demo/asya-demo:latest"
```

**`.asya/manifests/flavors/vertex-ai.yaml`**: update region, remove SA key volume:
- Change `VERTEXAI_LOCATION` from `us-central1` to `europe-west1`
- Remove `GOOGLE_APPLICATION_CREDENTIALS` env var (Workload Identity replaces it)
- Remove `volumes` and `volumeMounts` sections (no key file needed)

Then recompile and deploy:
```bash
asya compile src/demo_flows/text_improver.py
asya k apply src/demo_flows/text_improver.py
```


### Phase 10 - Docs

#### New file: `docs/install/gke.md`

Mirror structure of `aws-eks.md` but for GKE + Pub/Sub:
1. Prerequisites (gcloud, kubectl, helm 3, Vertex AI enabled)
2. Networking (existing VPC + subnet, Cloud NAT for egress)
3. Artifact Registry
4. Workload Identity (3 GSAs: crossplane-gcp / asya-actor / keda-gcp)
5. Crossplane install (separate from playground)
6. asya-playground two-step install (values-gke-pubsub.yaml)
7. Demo deployment (build image, asya compile, asya k apply)
8. Verification
9. Cost notes (scale-to-zero via KEDA, --logging=NONE, minimal node count)

#### Fix: `docs/install/aws-eks.md` - critical issues

| # | Issue | Severity |
|---|---|---|
| 1 | Emoji in first line | minor |
| 2 | No mention of `asya-playground` chart - primary install method completely absent | critical |
| 3 | Two-step Crossplane install not documented (providers must be Healthy before ProviderConfigs) | critical |
| 4 | Missing `kubectl wait` for provider health between the two steps | critical |
| 5 | `AsyncActor` spec missing `compositionSelector` field (required since XRD was updated) | critical |
| 6 | Step numbering jumps 4 -> 6 (step 5 missing) | minor |
| 7 | KEDA version `2.15.1` hardcoded; playground requires `>=2.16.0` | minor |
| 8 | Gateway values reference outdated schema (missing `mode:`, no api/mesh split) | major |
| 9 | `kubectl get asyncactor` should be `kubectl get asyncactors` | minor |
| 10 | x-pause / x-resume crew actors not mentioned | minor |


## Verification checklist (demo-day readiness)

- [ ] `kubectl -n $NS get asyncactors` - all actors show SYNCED=True, READY=True
- [ ] `kubectl -n crossplane-system get providers` - all Healthy
- [ ] `gcloud pubsub topics list --project=$PROJECT` - Pub/Sub topics present
- [ ] Gateway LoadBalancer IP reachable: `curl http://<LB_IP>/health`
- [ ] MCP tools visible: `curl http://<LB_IP>/mcp/tools`
- [ ] End-to-end test: send message, watch logs, confirm flow completes in < 60s
