# Demo: Multi-Team Actors with Skaffold

Multi-team project: **team-a** owns sentiment + summarizer actors,
**team-b** owns a translator actor. A shared library (`libs/common`)
provides utilities across teams. Skaffold manages the image build
lifecycle with multi-config (`requires:`).

This demo evaluates Skaffold as the build tool for Asya actor repos.

## Prerequisites

- Python 3.13+, [uv](https://docs.astral.sh/uv/)
- GKE cluster with Asya installed (see [docs/install/gcp-gke.md](../../docs/install/gcp-gke.md))
- Artifact Registry repository for actor images
- [Skaffold](https://skaffold.dev/docs/install/) v2+

```bash
# Install skaffold (linux)
curl -Lo skaffold https://storage.googleapis.com/skaffold/releases/latest/skaffold-linux-amd64
chmod +x skaffold && sudo mv skaffold /usr/local/bin/
skaffold version
```

## Setup

From the `examples/demo-skaffold/` directory:

```bash
uv sync
uv run asya --version

export GCP_PROJECT=<your-gcp-project>
export REGION=<gcp-region>               # e.g. europe-west1
export REPO=<artifact-registry-repo>     # e.g. asya-demo
export REGISTRY=${REGION}-docker.pkg.dev/${GCP_PROJECT}/${REPO}
```

## Step 1: Run flow locally

The flow is a pure Python function. Locally, handlers are just function
calls -- no queues, no actors:

```bash
uv run python -c '
from sentiment_actors.handler import analyze
from summarizer.handler import summarize
from translator.handler import translate

payload = {"text": "This is a great and wonderful example of excellent writing"}
payload = analyze(payload)
payload = summarize(payload)
payload = translate(payload)
print(payload)
'
```

## Step 2: Compile to actor graph

```bash
uv run asya compile flows/pipeline.py --plot
```

Output paths are configured in `.asya/config.yaml`:
- `compiled/pipeline/` -- router Python code + `flow.svg`
- `.asya/manifests/pipeline/base/` -- AsyncActor CRDs + router ConfigMap

Open `compiled/pipeline/flow.svg` to see the generated actor graph.

## Step 3: Build images with Skaffold

Skaffold reads the multi-config tree:
- `skaffold.yaml` (root) `requires:` team-a, team-b
- `team-a/skaffold.yaml` -- builds skaffold-sentiment-actors + skaffold-summarizer
- `team-b/skaffold.yaml` -- builds skaffold-translator

```bash
# Build all artifacts and push to Artifact Registry
skaffold build --default-repo=${REGISTRY}
```

`--default-repo` prefixes all image names (e.g. `skaffold-sentiment-actors`
becomes `${REGISTRY}/skaffold-sentiment-actors`).

### Build only one team

```bash
skaffold build -m team-a --default-repo=${REGISTRY}
skaffold build -m team-b --default-repo=${REGISTRY}
```

## Step 4: Deploy to GKE

```bash
# Create namespace
kubectl create namespace demo-skaffold --dry-run=client -o yaml | kubectl apply -f -

# Deploy compiled flow manifests
uv run asya k apply pipeline -v
```

`asya k apply` uses kustomize build piped to `kubectl apply --server-side`.
It applies the AsyncActor CRDs from `.asya/manifests/pipeline/`.

```bash
# Verify actors are reconciled
uv run asya k status pipeline
```

## Step 5: Dev loop (live reload)

Skaffold watches for file changes and rebuilds affected images:

```bash
skaffold dev --default-repo=${REGISTRY}
```

Edit a handler file (e.g. `team-a/actors/sentiment/sentiment_actors/handler.py`)
and observe:
- Does Skaffold detect the change?
- Does it rebuild only the affected image or all images?
- How fast is the rebuild-redeploy cycle?

Try editing `libs/common/common/utils.py` -- does Skaffold rebuild the
sentiment image (which depends on the shared lib)?

Press `Ctrl+C` to stop the dev loop.

## Step 6: Pod debugging

```bash
# Logs for a deployed flow
uv run asya k logs pipeline

# Exec into pod
kubectl -n demo-skaffold exec -it deploy/sentiment -- python3 -c "
from sentiment_actors.handler import analyze
print(analyze({'text': 'great excellent wonderful'}))
"

# Env vars
kubectl -n demo-skaffold exec deploy/sentiment -- env | sort
```

## Step 7: Config parsability (asya integration point)

Skaffold YAML is the source of truth for handler-to-image mapping.
Asya reads it natively -- no skaffold binary needed for compilation:

```bash
uv run python -c "
import yaml, json
with open('skaffold.yaml') as f:
    root = yaml.safe_load(f)
for req in root.get('requires', []):
    with open(f\"{req['path']}/skaffold.yaml\") as f:
        team = yaml.safe_load(f)
    for a in team['build']['artifacts']:
        print(f\"{a['image']} <- context={a['context']}\")
"
# skaffold-sentiment-actors <- context=..
# skaffold-summarizer <- context=actors/summarizer
# skaffold-translator <- context=actors/translator
```

## Cleanup

```bash
uv run asya k delete pipeline
kubectl delete namespace demo-skaffold
```

## Project structure

```
examples/demo-skaffold/
+-- skaffold.yaml                          # root config: requires team-a, team-b
+-- pyproject.toml                         # uv workspace (path deps for local run)
+-- .asya/
|   +-- config.yaml                        # build entries, compiler paths, templates
|   +-- compiler/templates/                # AsyncActor + ConfigMap + kustomize templates
|   +-- manifests/pipeline/                # generated by asya compile
+-- flows/
|   +-- pipeline.py                        # analyze -> summarize -> translate
+-- compiled/pipeline/                     # generated routers + flow.svg
+-- libs/common/                           # shared library (S4 scenario)
|   +-- pyproject.toml
|   +-- common/utils.py
+-- team-a/
|   +-- skaffold.yaml                      # team-a build config (2 artifacts)
|   +-- .asya/config.yaml                  # team-a overrides
|   +-- actors/
|   |   +-- sentiment/                     # depends on libs/common (root context)
|   |   |   +-- Dockerfile
|   |   |   +-- sentiment_actors/handler.py
|   |   +-- summarizer/                    # self-contained (local context)
|   |       +-- Dockerfile
|   |       +-- summarizer/handler.py
|   +-- k8s/                               # standalone deployment manifests
+-- team-b/
    +-- skaffold.yaml                      # team-b build config (1 artifact)
    +-- .asya/config.yaml
    +-- actors/translator/
    |   +-- Dockerfile
    |   +-- translator/handler.py
    +-- k8s/
```

## Scenarios checklist

- [ ] S1: `skaffold build` builds all images, `asya k apply` deploys
- [ ] S2: `skaffold build -m team-a` builds only team-a
- [ ] S3: `skaffold dev` detects handler edits and rebuilds
- [ ] S4: editing `libs/common/` triggers rebuild of dependent images
- [ ] S5: `kubectl exec` into pod, inspect env and run handler
- [ ] S6: how to reference a pre-built image (not built by skaffold)?
