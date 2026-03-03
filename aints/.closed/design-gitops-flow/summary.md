---
title: Design GitOps Flow for Asya Projects
priority: 2 # medium
state: yeeted
reason: superseeded by more granular design (see [[1jow]], [[1iu5]], [[1jpc]], [[1juv]], [[1juw]], [[1jux]], [[1juy]] and future ones)
dependencies: [1jow]
---

Design the end-to-end GitOps workflow for Asya projects: how data scientists and
ML engineers structure their repos, develop actors locally, and promote work from
experimentation through staging to production via declarative, auditable Git
commits.

This epic codifies the design decisions from the Client UX brainstorm (1jow) into
a concrete project layout, compilation pipeline, and CD integration strategy.


## Problem Statement

Data scientists building actor pipelines need a workflow that supports two
fundamentally different modes of operation:

1. **Experimentation** -- fast, imperative, tolerant of mess. A DS iterates on a
   model handler, deploys it to a staging cluster with a single command, and
   checks results. No PRs, no reviews, no pipeline gates.

2. **Production** -- declarative, reproducible, auditable. Changes land in Git,
   pass CI, get reviewed, and are applied to the cluster by ArgoCD or FluxCD.
   No imperative mutations to the production cluster.

The framework must support both modes cleanly without requiring a "readonly mode"
toggle or separate tooling. The same `asya` CLI and the same project structure
serve both; the difference is whether the DS runs `asya flow deploy` against a
cluster or generates manifest files for a Git commit.


## Design Decisions

### 1. Project Structure

One repository = one cluster. Multiple environments (staging, production) are
represented as contexts, not separate repos. Many teams and users collaborate in
the same repo.

```
my-asya-project/
├── asya.yaml                  # Project config with contexts
├── .asya/                     # Gitignored local state (caches, compiled output)
├── src/                       # Python packages (pip-installable)
│   ├── text_processing/       # Package: text processing handlers
│   │   ├── pyproject.toml
│   │   ├── text_processing/
│   │   │   ├── __init__.py
│   │   │   ├── summarizer.py
│   │   │   └── classifier.py
│   │   └── tests/
│   └── order_flow/            # Package: order processing flow
│       ├── pyproject.toml
│       ├── order_flow/
│       │   ├── __init__.py
│       │   └── flow.py        # Flow DSL definition
│       └── tests/
└── deploy/                    # Deployment config (never generated into src/)
    ├── actors/                # Individual actor configs
    │   ├── summarizer/
    │   │   ├── actor.yaml     # Deployment config (name, transport, flavors)
    │   │   └── .env           # Business-logic env vars
    │   └── classifier/
    │       ├── actor.yaml
    │       └── .env
    └── flows/                 # Compiled flow output
        └── order-processing/
            ├── manifest.yaml  # IR: compiled flow spec (business-only, not a K8s CRD)
            └── .env
```

Key principles:
- `src/` contains only Python code. Packages are pip-installable and can
  cross-reference each other.
- `deploy/` contains only deployment configuration. Actor configs, env files,
  and compiled manifests live here.
- Generated files (compilation output) go to a configured `compilePath` per
  context. They are separated from user code like generated linter output --
  never manually edited.
- `.asya/` is gitignored. It holds local state: caches, temporary compiled
  output for the current context, resolved configs.


### 2. Contexts

Contexts work like `kubectl` contexts: named configurations that select a target
environment. Defined in `asya.yaml`, overridable by the `ASYA_CONTEXT` env var.

```yaml
# asya.yaml
project: my-asya-project

contexts:
  k8s-stg:
    transport: sqs
    namespace: staging
    compilePath: deploy/flows/   # Compiled manifests land here
    dotenv:
      - deploy/actors/${actor}/.env
      - deploy/common/.env.stg

  k8s-prod:
    transport: sqs
    namespace: production
    compilePath: deploy/flows/
    dotenv:
      - deploy/actors/${actor}/.env
      - deploy/common/.env.prod

  docker:
    transport: rabbitmq
    compilePath: .asya/compiled/  # Local dev: gitignored output
    dotenv:
      - deploy/actors/${actor}/.env
      - deploy/common/.env.local

defaultContext: k8s-stg
```

Context resolution order:
1. `ASYA_CONTEXT` env var (highest priority)
2. `--context` CLI flag
3. `defaultContext` in `asya.yaml`


### 3. Compilation and the Manifest IR

`asya compile` transforms flow definitions and actor configs into a manifest IR
(intermediate representation). The manifest is the single artifact that bridges
user code and deployment tooling.

```
src/order_flow/flow.py    ──► asya compile ──► deploy/flows/order-processing/manifest.yaml
deploy/actors/*/actor.yaml ─┘                  (+ routers.py ConfigMap content)
```

**Manifest design principles:**
- NOT a Kubernetes CRD. It is a minimal, business-only spec that describes what
  the flow does, not how Kubernetes should run it.
- Flavors stay as references (e.g., `flavor: gpu-large`), resolved by Crossplane
  at deploy time, not at compile time.
- For flows: one `manifest.yaml` per flow, not N individual CRD files.
- For individual actors: `actor.yaml` in `deploy/actors/` is already the config;
  no separate manifest needed.

```yaml
# deploy/flows/order-processing/manifest.yaml (example IR)
flow: order-processing
entrypoint: validate-order
transport: sqs

actors:
  - name: validate-order
    handler: order_flow.flow.validate_order
    role: processor
  - name: payment-processor
    handler: order_flow.flow.process_payment
    role: processor
    flavor: gpu-small
  - name: start-order-processing
    handler: __generated__.routers.start_order_processing
    role: router
    role: entrypoint

routers:
  configMap: order-processing-routers
  source: |
    # Generated by asya compile -- do not edit
    ...

expose:
  tool: process-order
  description: "Submit an order for processing"
  parameters:
    type: object
    properties:
      order_id: { type: string }
```

**What `asya compile` does NOT do:**
- Does not build Docker images (that is CI's job)
- Does not resolve flavors to concrete resource specs
- Does not contact the Kubernetes API
- Does not set image references (CI pipeline sets those)


### 4. Lab-to-Prod Transition

The same CLI serves both experimentation and production. The difference is the
output target, not the tool.

**Experimentation (staging):**
```bash
# Imperative: compile and deploy in one step
asya flow deploy --context=k8s-stg

# What happens:
# 1. Compiles flow DSL to manifest IR
# 2. Renders manifest to K8s resources (AsyncActor CRDs + ConfigMaps)
# 3. Applies directly to the staging cluster via kubectl
```

**Production (GitOps):**
```bash
# Step 1: Compile (DS does this locally or in CI)
asya compile --context=k8s-prod

# Step 2: Render to K8s manifests (optional, for plain-manifest GitOps)
asya render --context=k8s-prod --output-dir deploy/rendered/

# Step 3: Commit and push
git add deploy/
git commit -m "deploy: update order-processing flow"
git push

# Step 4: CD tool (ArgoCD/FluxCD) detects change, applies to cluster
```

**No readonly mode.** The framework does not enforce production protection.
Instead, rely on Kubernetes RBAC: the DS's kubeconfig for prod has limited
permissions (or no direct access at all). The CD tool's service account has
the necessary permissions. This is standard Kubernetes security practice.


### 5. Environment Variables

Clear separation between framework and business concerns:

| Prefix | Owner | Examples |
|--------|-------|---------|
| `ASYA_*` | Framework (infra) | `ASYA_TRANSPORT`, `ASYA_ACTOR_NAME`, `ASYA_MSG_ROOT` |
| Everything else | Business logic | `MODEL_PATH`, `API_KEY`, `BATCH_SIZE` |

**Handler code** uses standard `os.environ.get()`. The framework has no opinions
about business env vars -- it does not wrap, proxy, or namespace them.

**.env files** are loaded via standard `load_dotenv`. Resolution order is
configurable in `asya.yaml` per context via the `dotenv` section:

```yaml
dotenv:
  - deploy/actors/${actor}/.env       # Actor-specific (highest priority)
  - deploy/common/.env.${context}     # Context-specific
  - deploy/common/.env                # Shared defaults (lowest priority)
```

Secrets (API keys, credentials) are NOT stored in `.env` files. They are
injected via Kubernetes Secrets, mounted as env vars or files by the injector
or Crossplane composition.


### 6. Actor Identity

**Code IS the actor card.** A Python function's import path, docstring, and type
hints are the canonical description of what the actor does. There is no separate
"actor registry" or metadata service.

```python
# src/text_processing/text_processing/summarizer.py

async def summarize(payload: dict) -> dict:
    """Summarize input text using extractive summarization.

    Accepts a text field and returns a summary with confidence score.
    """
    ...
```

The import path `text_processing.summarizer.summarize` uniquely identifies this
handler. The docstring and type hints are extractable by the CLI for tool
registration and documentation.

**actor.yaml** in `deploy/` is deployment config only:

```yaml
# deploy/actors/summarizer/actor.yaml
name: text-summarizer
handler: text_processing.summarizer.summarize
transport: sqs
flavor: cpu-medium
```

**One handler, multiple actors.** The same handler function can be deployed as
multiple actors with different names, flavors, and scaling configs. The actor
name is a deployment concern, not an identity concern. This aligns with the
1:M constraint from ADR `1iqd` (labels vs CRD).


### 7. CD Tool Integration

The framework provides a Helm chart (`asya-flow`) that CD tools consume. The
manifest IR is the values source.

**ArgoCD integration:**
```yaml
# ArgoCD Application
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: order-processing
spec:
  source:
    repoURL: https://asya.sh/charts
    chart: asya-flow
    targetRevision: "0.1.0"
    helm:
      valueFiles:
        - deploy/flows/order-processing/manifest.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: production
```

**FluxCD integration:**
```yaml
# FluxCD HelmRelease
apiVersion: helm.toolkit.fluxcd.io/v2beta1
kind: HelmRelease
metadata:
  name: order-processing
spec:
  chart:
    spec:
      chart: asya-flow
      sourceRef:
        kind: HelmRepository
        name: asya
  valuesFrom:
    - kind: ConfigMap
      name: order-processing-values
```

**Plain CRD mode** (no Helm chart dependency):
```bash
# Render manifest to plain K8s CRDs
asya render --context=k8s-prod --output-dir deploy/rendered/

# Output: individual AsyncActor CRDs + ConfigMaps
# Apply via ArgoCD directory source, FluxCD Kustomization, or plain kubectl
```

**Extensibility:** The `asya render` command outputs standard Kubernetes YAML.
Any tool that applies YAML to a cluster (Kustomize, Terraform kubernetes
provider, Pulumi, plain scripts) can consume the output.


### 8. CI/CD Separation

Clear boundary between CI (build) and CD (deploy):

```
CI Pipeline                          CD Pipeline
──────────                          ──────────
1. git push triggers CI             1. ArgoCD/FluxCD detects manifest change
2. Run tests (pytest)               2. Resolves Helm chart + values
3. Build Docker image               3. Applies to cluster
4. Push image to registry           4. Crossplane resolves flavors
5. Update image ref in manifest     5. Actors start with correct images
6. asya compile (if flow changed)
7. Commit updated manifests
```

**Image building is out of scope** for the `asya` CLI and this epic. The
Dockerfile, build pipeline, and registry configuration are CI concerns handled
by the team's existing tooling (GitHub Actions, GitLab CI, Jenkins, etc.). See
epic 1iu5 for exploration of seamless experimentation image building.

**What `asya compile` produces** is deterministic and reproducible: given the
same source files and context, it always produces the same manifest output.
Image references are injected by CI after the image is built and pushed.


## Scope Boundaries

**In scope:**
- Project directory layout conventions
- `asya.yaml` context configuration schema
- Manifest IR format and compilation pipeline
- CD tool integration patterns (ArgoCD, FluxCD, plain CRDs)
- Environment variable conventions and `.env` resolution
- Actor identity model (code as actor card)

**Out of scope (handled by other epics):**
- CLI implementation details -- epic 1jpc
- Image building workflow -- epic 1iu5
- Local Docker Compose testing -- epic 1iu4
- Flow DSL compilation internals -- existing `asya flow compile`
- AsyncFlow CRD vs labels decision -- ADR in epic 1iqd (decided: labels)
- Kubernetes RBAC configuration -- ops concern, not framework concern


## Related Epics

- **1jow** -- Client UX Design (parent; design decisions flow from here)
- **1jpc** -- CLI and SDK (implements the commands described here)
- **1iqd** -- Flow Workflow Design (ADR: labels vs CRD, decided labels)
- **1iu5** -- Seamless Experimentation Image Building (CI-side complement)
- **1iu4** -- Local Testing Workflow with Docker Compose
