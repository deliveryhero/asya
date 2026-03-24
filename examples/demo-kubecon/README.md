# KubeCon Demo: Text Improver

Evaluator-optimizer content pipeline on Asya Actor Mesh.

5 actors, while-loop with quality threshold, mixed function signatures
(4 adapter-style + 1 standard dict->dict). No LLM calls — deterministic
stubs with simulated latency.

## Prerequisites

- GKE cluster with Asya v0.5.12+ (asya-crossplane, asya-crew, asya-gateway)
- `skaffold`, `kubectl`, `uv` installed
- GCP auth and Artifact Registry access

```bash
export GCP_PROJECT=foodsci-img-gen-dev-1407-1448
export REGION=europe-west1
export KCTX=gke_${GCP_PROJECT}_${REGION}_asya-demo

cd examples/demo-kubecon
alias asya="uv run --project ../../src/asya-lab asya"
```

## Step 1: Compile

```bash
asya compile text-improver -f src/flow_text_improver.py
```

Generates 5 actor manifests, 7 routers, 4 adapter ConfigMaps.

## Step 2: Build and push

```bash
asya build text-improver
```

Builds Docker image from `src/Dockerfile`, pushes to registry, updates
kustomize image tags in `compiled/text-improver/manifests/common/`.

## Step 3: Expose via gateway

```bash
asya patch text-improver --gateway --context dev \
  -- \
  expose=true \
  description="Text improver: evaluator-optimizer content pipeline" \
  mcp=true a2a=true
```

## Step 4: Deploy

```bash
asya k apply text-improver --context dev
```

Applies actors + ConfigMaps + gateway flow registration.

## Step 5: Port-forward and test

```bash
kubectl -n asya-demo port-forward svc/asya-gateway-api 18080:80
asya k send text-improver "Write a haiku about Kubernetes" --context dev
```

Expected: `[+] Task ...: completed`

## Step 6: View logs

```bash
asya k logs text-improver --tail 5 --context dev
asya k logs text-improver -f --context dev
```

## Step 7: Load test

```bash
kubectl apply -f k8s/load-test-job.yaml
kubectl -n asya-demo logs -f job/text-improver-load-test
```

Watch KEDA scale-up in Grafana.

## Step 8: Clean up

```bash
asya k delete text-improver --context dev
kubectl delete job text-improver-load-test -n asya-demo
```

## Flow

```
research -> [while: generate -> evaluate -> break if score >= 85] -> polish -> format_output
```

| Actor | Signature | Style |
|-------|-----------|-------|
| research | `(topic: str) -> str` | Adapter |
| generate | `(topic: str, context: str, feedback: str) -> str` | Adapter |
| evaluate | `(payload: dict) -> dict` | Standard |
| polish | `(draft: str) -> str` | Adapter |
| format_output | `(draft: str, score: int, iterations: int) -> dict` | Adapter |

## Project structure

```
src/
  Dockerfile
  skaffold.yaml
  flow_text_improver.py       # flow definition
  actors/
    research.py               # str -> str
    generate.py               # (str,str,str) -> str + FAIL_RATE
    evaluate.py               # dict -> dict
    polish.py                 # str -> str
    format_output.py          # (str,int,int) -> dict
compiled/text-improver/       # compiler output
k8s/load-test-job.yaml        # Pub/Sub load test
.asya/config.yaml
```
