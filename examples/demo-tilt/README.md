# Demo: Multi-Team Actors with Tilt

Multi-team project: **team-a** owns sentiment + summarizer actors,
**team-b** owns a translator actor. A shared library (`libs/common`)
provides utilities across teams. Tilt manages the image build lifecycle
with `include()` for sub-project aggregation.

This demo evaluates Tilt as the build tool for Asya actor repos.

## Prerequisites

- Python 3.13+, [uv](https://docs.astral.sh/uv/)
- GKE cluster with Asya installed (see [docs/install/gcp-gke.md](../../docs/install/gcp-gke.md))
- Artifact Registry repository for actor images
- [Tilt](https://docs.tilt.dev/install.html) v0.33+

```bash
# Install tilt (linux)
curl -fsSL https://raw.githubusercontent.com/tilt-dev/tilt/master/scripts/install.sh | bash
tilt version
```

## Setup

From the `examples/demo-tilt/` directory:

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

## Step 3: Deploy to GKE with asya

```bash
# Create namespace
kubectl create namespace demo-tilt --dry-run=client -o yaml | kubectl apply -f -

# Deploy compiled flow manifests
uv run asya k apply pipeline -v
```

`asya k apply` uses kustomize build piped to `kubectl apply --server-side`.

```bash
# Verify actors are reconciled
uv run asya k status pipeline
```

## Step 4: Dev loop with Tilt

Tilt reads the config tree:
- `Tiltfile` (root) `include()` team-a, team-b
- `team-a/Tiltfile` -- builds tilt-sentiment-actors + tilt-summarizer
- `team-b/Tiltfile` -- builds tilt-translator

```bash
# Start Tilt (builds, deploys, watches for changes)
tilt up
```

Tilt opens a browser dashboard at `http://localhost:10350` showing:
- All resources grouped by team label (`team-a`, `team-b`)
- Build status, logs, and pod health for each actor
- Live file sync status

### What to observe

1. Edit `team-a/actors/sentiment/sentiment_actors/handler.py` -- does Tilt
   use `live_update` (file sync) or trigger a full rebuild?
2. Edit `libs/common/common/utils.py` -- does Tilt rebuild sentiment?
3. How fast does the change reach the running pod?

The `live_update` rules in each Tiltfile control sync behavior:
- Sentiment: syncs `sentiment_actors/` to `/app/sentiment_actors/`
- Summarizer: syncs `summarizer/` to `/app/summarizer/`
- Translator: syncs `translator/` to `/app/translator/`

## Step 5: Build only (CI mode)

For CI or one-shot image builds without the dev loop:

```bash
tilt ci
```

`tilt ci` builds and deploys everything, then exits (non-interactive).
Exit code 0 if all resources become ready, non-zero otherwise.

## Step 6: Pod debugging

```bash
# Logs for a deployed flow
uv run asya k logs pipeline

# Exec into pod
kubectl -n demo-tilt exec -it deploy/sentiment -- python3 -c "
from sentiment_actors.handler import analyze
print(analyze({'text': 'great excellent wonderful'}))
"

# Env vars
kubectl -n demo-tilt exec deploy/sentiment -- env | sort
```

## Step 7: Config parsability (asya integration point)

Tilt uses Starlark (Python-like DSL). Unlike Skaffold YAML, it
cannot be parsed with `yaml.safe_load()` -- it requires either:
- The `tilt` binary (`tilt dump config`)
- A Starlark interpreter (e.g. `starlark-go` or `pystarlark`)
- Manual regex/AST parsing (fragile)

```bash
# With tilt binary: dump the evaluated config
tilt dump config

# Compare: skaffold YAML is trivially parsable
uv run python -c "import yaml; print(yaml.safe_load(open('Tiltfile').read()))"
# ^ This will NOT work -- Starlark is not YAML
```

## Cleanup

```bash
uv run asya k delete pipeline
# If tilt up is running, Ctrl+C stops it and cleans up
tilt down
kubectl delete namespace demo-tilt
```

## Project structure

```
examples/demo-tilt/
+-- Tiltfile                               # root config: include() team-a, team-b
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
|   +-- Tiltfile                           # team-a build config (2 resources)
|   +-- .asya/config.yaml                  # team-a overrides
|   +-- actors/
|   |   +-- sentiment/                     # depends on libs/common (root context)
|   |   |   +-- Dockerfile
|   |   |   +-- sentiment_actors/handler.py
|   |   +-- summarizer/                    # self-contained (local context)
|   |       +-- Dockerfile
|   |       +-- summarizer/handler.py
|   +-- k8s/                               # deployment manifests (used by tilt up)
+-- team-b/
    +-- Tiltfile                           # team-b build config (1 resource)
    +-- .asya/config.yaml
    +-- actors/translator/
    |   +-- Dockerfile
    |   +-- translator/handler.py
    +-- k8s/                               # deployment manifests (used by tilt up)
```

## Scenarios checklist

- [ ] S1: `asya compile` + `asya k apply` deploys compiled flow
- [ ] S2: comment out `include('./team-b/Tiltfile')` -- only team-a builds
- [ ] S3: `tilt up` + edit handler -- observe live_update vs full rebuild
- [ ] S4: editing `libs/common/` triggers rebuild of sentiment image
- [ ] S5: `kubectl exec` into pod, inspect env and run handler
- [ ] S6: how to reference a pre-built image (not built by tilt)?
