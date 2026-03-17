# KubeCon Demo: Evaluator-Optimizer on Asya

Text generation flow: **generator** writes a draft, **evaluator** scores it,
loop until quality threshold is met, then **polisher** finalizes.

This demo runs on GKE with Pub/Sub transport and Vertex AI.

## Prerequisites

- Python 3.13+, [uv](https://docs.astral.sh/uv/)
- GCP project with Vertex AI API and Pub/Sub API enabled
- GKE cluster with Asya installed (see [docs/install/gcp-gke.md](../../docs/install/gcp-gke.md))
- Artifact Registry repository for actor images

## Setup

From the `examples/demo-kubecon/` directory:

```bash
uv sync
uv pip install git+https://github.com/deliveryhero/asya.git#subdirectory=src/asya-lab
uv run asya --version
```

## Step 1: Run flow locally

The flow is a pure Python async function. `generator`, `evaluator`, and
`polisher` are unresolved names — in production, Asya resolves them to actor
queues. Locally, we bind them to the real handler functions:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/tmp/asya-demo-sa.json
export VERTEXAI_PROJECT=<your-gcp-project>
export VERTEXAI_LOCATION=us-central1

uv run python -c '
import asyncio
from demo_flows.text_improver import text_improver
state = {"task": "Write a haiku about message queues"}
asyncio.run(text_improver(state))
'
```

The flow runs as a single process — sequential calls, no queues, no actors.
Same code, same results.

## Step 2: Compile to actor graph

```bash
uv run asya compile src/demo_flows/text_improver.py --plot
```

Output paths are configured in `.asya/config.yaml`:
- `src/demo_actors/compiled/text_improver/` — router Python code + `flow.svg`
- `.asya/manifests/text-improver/base/` — AsyncActor CRDs + router ConfigMap

Open `src/demo_actors/compiled/text_improver/flow.svg` to see the generated actor
graph with loop-back edges.

## Step 3: Deploy to GKE

### 3a. Set variables

```bash
export GCP_PROJECT=<your-gcp-project>
export REGION=<gcp-region>          # e.g. europe-west1
export REPO=<artifact-registry-repo> # e.g. asya-demo
export REGISTRY=${REGION}-docker.pkg.dev/${GCP_PROJECT}/${REPO}
```

### 3b. Load actor credentials

```bash
# Create SA key for Vertex AI (if not already done):
gcloud iam service-accounts create asya-demo \
  --display-name="Asya Demo" --project=$GCP_PROJECT
gcloud projects add-iam-policy-binding $GCP_PROJECT \
  --member="serviceAccount:asya-demo@${GCP_PROJECT}.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"
gcloud iam service-accounts keys create /tmp/asya-demo-sa.json \
  --iam-account=asya-demo@${GCP_PROJECT}.iam.gserviceaccount.com

# Store credentials in Kubernetes:
kubectl create namespace asya-demo --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic asya-actor-creds \
  --namespace=asya-demo \
  --from-file=sa-key.json=/tmp/asya-demo-sa.json \
  --from-literal=project-id=${GCP_PROJECT} \
  --from-literal=location=us-central1 \
  --dry-run=client -o yaml | kubectl apply -f -
```

### 3c. Apply platform config (flavors)

```bash
kubectl apply -f .asya/manifests/flavors/ -n asya-demo
```

This applies the `vertex-ai` flavor (mounts credentials, sets `VERTEXAI_PROJECT`
and `VERTEXAI_LOCATION` from the `asya-actor-creds` secret) and the `llm-resilient`
flavor (retry/timeout settings).

### 3d. Build and push actor image

```bash
# Edit .asya/config.yaml: set image to your Artifact Registry path
# image: "${REGISTRY}/asya-demo:latest"

docker build -t ${REGISTRY}/asya-demo:latest .
docker push ${REGISTRY}/asya-demo:latest
```

### 3e. Deploy actors

```bash
kubectl apply -k .asya/manifests/text-improver/base/ -n asya-demo
kubectl -n asya-demo get asyncactors
```

Crossplane reconciles each `AsyncActor` into a Deployment + Pub/Sub topic +
subscription. Wait for `SYNCED=True` and `READY=True`:

```bash
kubectl -n asya-demo get asyncactors -w
```

## Step 4: Invoke via gateway

```bash
# Get the gateway URL and API key:
export GATEWAY_URL=http://$(kubectl -n asya-demo get svc asya-gateway-api \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
export API_KEY=$(kubectl -n asya-demo get secret asya-gateway-auth \
  -o jsonpath='{.data.a2a-api-key}' | base64 -d)

# Verify the gateway is healthy:
curl ${GATEWAY_URL}/health
```

### Send a message via A2A

`message/send` blocks until the flow completes (the gateway waits for the
x-sink actor to POST back the final result). Flows using LLM calls typically
take 30-120s.

```bash
curl -s -X POST ${GATEWAY_URL}/a2a/text-improver \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{
    "jsonrpc": "2.0", "method": "message/send", "id": 1,
    "params": {
      "message": {
        "messageId": "demo-1",
        "role": "user",
        "parts": [{"kind": "text", "text": "Write a limerick about message queues"}]
      }
    }
  }' | python3 -m json.tool
```

## Project structure

```
examples/demo-kubecon/
├── Dockerfile                              # actor image (Python + demo handlers)
├── pyproject.toml
├── uv.lock
├── .asya/
│   ├── config.yaml                         # build entry, compiler paths, template vars
│   ├── compiler/templates/                 # AsyncActor + ConfigMap + kustomization templates
│   │   ├── actor.yaml
│   │   ├── router.yaml
│   │   ├── configmap_routers.yaml
│   │   └── kustomization.yaml
│   └── manifests/
│       ├── flavors/                        # platform config (GCP credentials, LLM retry)
│       │   ├── vertex-ai.yaml
│       │   └── llm-resilient.yaml
│       └── text-improver/                  # generated by asya compile
│           └── base/                       # fully regenerated on each compile
└── src/
    ├── demo_flows/
    │   └── text_improver.py                # the flow (compiles to actor graph)
    └── demo_actors/
        ├── generator.py                    # Vertex AI: generate/revise draft
        ├── evaluator.py                    # Vertex AI: score + feedback
        ├── polisher.py                     # Vertex AI: final polish
        └── compiled/                       # generated by asya compile
            └── text_improver/
                ├── routers.py
                ├── flow.dot
                └── flow.svg
```
