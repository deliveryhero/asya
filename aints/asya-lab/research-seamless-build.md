# Research: Seamless Build and Iteration Workflows

**Date**: 2026-03-05
**Status**: Informational
**Context**: How to eliminate build friction during DS experimentation while
keeping traditional CI/CD for production. Must be modular.

---

## 1. Problem Statement

The DS experimentation loop on K8s staging is too slow:

| Workflow | Latency | Acceptable? |
|---|---|---|
| Local Python function call | <1s | Yes |
| Code change -> file sync to pod | 1-2s | Yes |
| Code change -> docker build -> push -> deploy | 3-10min | No |
| Code change -> commit -> CI/CD -> build -> deploy | 10-30min | No |

**Goal**: Make iteration on K8s staging as fast as local development while
keeping the traditional CI/CD pipeline available for production deploys.

**Design constraints**:
- Asya actors consume from message queues (SQS/RabbitMQ), not HTTP
- Sidecar pattern (Go sidecar + Python runtime in same pod)
- Must work for both simple Python and GPU/ML actors
- Must not force any single tool on teams
- Must offer "golden paths" solving the UX problem

---

## 2. Tool Analysis

### 2.1 Skaffold (Google, Active Open Source)

**What it does**: Automates build-deploy loop for K8s. Watches files, syncs
or rebuilds, deploys.

**File sync for Python** (the fast path):
```yaml
# skaffold.yaml
apiVersion: skaffold/v4beta11
kind: Config
build:
  artifacts:
    - image: my-python-actor
      docker:
        dockerfile: Dockerfile
      sync:
        manual:
          - src: "src/**/*.py"
            dest: /app
```

Code change -> copy to container -> 1-2s. No rebuild.

**When rebuilds are needed**: `requirements.txt` changes trigger full rebuild.
Optimization via BuildKit cache mounts reduces this to ~30s.

**Dev mode**: `skaffold dev` watches files, auto-syncs/rebuilds, cleans up
on Ctrl+C. Profiles for different environments.

**Python buildpacks auto-sync**: NOT available yet (works for Go, Java,
Node.js). Workaround: manual sync mode.

**Can Asya generate skaffold.yaml?**: Yes, from build inputs (format TBD).

**Verdict**: Good inner-loop tool for code changes. Doesn't solve the "DS
scared of Docker" problem (still needs a Dockerfile for initial build).

| Dimension | Rating |
|---|---|
| Iteration speed (code) | 5/5 (1-2s with sync) |
| Iteration speed (deps) | 3/5 (30-60s rebuild) |
| DS-friendliness | 3/5 (needs Dockerfile + skaffold.yaml) |
| Message queue support | 2/5 (no queue-specific features) |
| Production-ready | 3/5 (dev tool, not deployment) |

### 2.2 Shipwright (CNCF Sandbox)

**What it does**: On-cluster container builds. Build CRD triggers builds
inside K8s pods.

**How it works**:
```
Code push -> Build CR -> BuildRun CR -> Tekton pod -> Image -> Registry
```

**Build CRD**:
```yaml
apiVersion: shipwright.io/v1beta1
kind: Build
metadata:
  name: python-actor-build
spec:
  source:
    type: Git
    git:
      url: https://github.com/org/actor
  strategy:
    name: buildpacks-v3        # or kaniko, buildah, custom
    kind: ClusterBuildStrategy
  output:
    image: registry/actor:latest
    pushSecret: registry-credentials
```

**Custom build strategies**: ClusterBuildStrategy CRDs define build steps.
Can use buildpacks, Kaniko, Buildah, or custom tools (Cog).

**Cog as Shipwright strategy** (requires custom strategy):
```yaml
apiVersion: shipwright.io/v1beta1
kind: ClusterBuildStrategy
metadata:
  name: cog-build
spec:
  steps:
    - name: cog-build
      image: replicate/cog:latest
      command: ["cog", "build", "-t", "$(params.output-image)"]
```

**GitOps integration**: Build triggers on git push, ArgoCD/Flux watches
registry for new images.

**Build caching**: Persistent volume cache, registry cache. First build
3-5min, cached 30-60s.

**Maturity (2026)**: CNCF Sandbox, used in OpenShift, growing community.

**Verdict**: Solves "where to build" for teams that don't want local Docker.
But doesn't solve iteration speed (each build is still minutes).

| Dimension | Rating |
|---|---|
| DS-friendliness | 4/5 (no local Docker needed) |
| Build speed | 3/5 (30-60s cached, 3-5min cold) |
| GitOps integration | 5/5 (native K8s CRDs) |
| Maturity | 3/5 (CNCF Sandbox) |

### 2.3 Tilt (Docker-owned, Apache 2.0)

**What it does**: K8s development tool with Python-based config (Starlark),
live updates, web UI.

**Python live update**:
```python
# Tiltfile
docker_build('my-actor', '.',
  live_update=[
    sync('./src', '/app/src'),                           # 1s
    run('pip install -r requirements.txt',               # 10s
        trigger='requirements.txt'),
    fall_back_on(['Dockerfile']),                         # 60s
  ]
)
k8s_yaml('k8s-manifest.yaml')  # whatever Asya generates
```

**Decision tree**:
1. Python file changed -> sync only (~1s)
2. requirements.txt changed -> sync + run pip (~10s)
3. Dockerfile changed -> full rebuild (~60s)

**vs Skaffold**: Tilt has Python config (more expressive), built-in web UI,
better dependency change handling (run pip in container vs full rebuild).
Skaffold has YAML config (simpler), Google Cloud integration.

**Status (2026)**: Acquired by Docker (2022), remains open source (Apache 2.0),
actively maintained.

**Verdict**: Best developer experience for multi-service K8s apps. Python
config is natural for DS. Dependency changes handled without full rebuild.

| Dimension | Rating |
|---|---|
| Iteration speed (code) | 5/5 (1s sync) |
| Iteration speed (deps) | 4/5 (10s in-container pip) |
| DS-friendliness | 4/5 (Python config) |
| Multi-actor pipelines | 5/5 (resource_deps, grouping) |

### 2.4 mirrord (Process-Level Interception)

**What it does**: Runs local process as if it's inside the K8s cluster.
Intercepts network, filesystem, environment from a remote pod.

**How it works**: LD_PRELOAD-based interception. Hooks libc calls so the
local Python process sees the remote pod's environment.

```bash
mirrord exec --target pod/my-actor -- python handler.py
```

The local Python process:
- Sees remote env vars (ASYA_TRANSPORT, ASYA_ACTOR_NAME, etc.)
- Can access remote services (RabbitMQ, SQS, databases)
- Receives traffic destined for the remote pod

**Queue support**: mirrord supports "queue splitting" -- multiple developers
can share a staging queue, each filtering for their messages. This is critical
for Asya's message-queue architecture.

**vs Telepresence**: Telepresence intercepts at network level (VPN),
mirrord at process level (LD_PRELOAD). mirrord is lighter, no cluster-side
components needed. Telepresence v2 became proprietary (Ambassador Labs).

**vs Gefyra**: Gefyra uses Wireguard VPN, requires cluster-side components.
Heavier but more reliable for complex scenarios.

**Critical finding**: Telepresence does NOT work well for message queues
(designed for HTTP/gRPC interception). mirrord's queue splitting IS designed
for this pattern.

**Verdict**: Game-changer for Asya. Zero build, zero Docker, code runs
locally with remote cluster context. Queue splitting fits Asya's architecture
perfectly.

| Dimension | Rating |
|---|---|
| Iteration speed | 5/5 (0s -- runs local code) |
| DS-friendliness | 5/5 (just run Python) |
| Message queue support | 4/5 (queue splitting) |
| Production safety | 3/5 (dev-only, intercepts traffic) |
| Cluster-side setup | 5/5 (no components needed) |

### 2.5 The "No-Build" Patterns

Several patterns avoid building images entirely:

**A. Code-as-ConfigMap** (Asya already does this for routers):
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: actor-code
data:
  handler.py: |
    def process(payload):
        return {"result": ...}
```
Mount into pod, use generic `asya-runtime` base image.

Limitation: ConfigMaps have 1MB size limit. Only for small handlers.

**B. Code-as-PVC** (Persistent Volume):
Store code on shared storage, mount into pods. Works for larger codebases.
But: no dependency isolation, shared state problems.

**C. Code download at startup** (Ray/KServe pattern):
Pod starts with generic base image, downloads code from Git/S3 at startup:
```yaml
initContainers:
  - name: code-fetcher
    image: alpine/git
    command: ["git", "clone", "--depth=1", "https://github.com/org/actor"]
    volumeMounts:
      - name: code
        mountPath: /code
```

Works for experimentation. Unreliable for production (startup dependency
on external services, no version pinning).

**D. Storage initializer** (KServe pattern):
Download model/code from S3 at startup. Production-proven for ML models.
Could extend to user code:
```yaml
spec:
  storageUri: s3://bucket/actor-code/v1.2.3/
```

**Verdict**: ConfigMap pattern works for routers (already proven). Code
download works for experimentation but not production. Storage initializer
is production-proven for models but adds startup latency.

### 2.6 Build Caching Strategies

**Optimal Dockerfile for rapid iteration**:
```dockerfile
FROM python:3.11-slim
WORKDIR /app

# Layer 1: Rare changes (framework deps)
COPY requirements-base.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements-base.txt

# Layer 2: Occasional changes (actor deps)
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Layer 3: Frequent changes (code)
COPY handler.py .
ENV ASYA_HANDLER=handler.process
```

**Result**: Code-only changes rebuild in ~3s (cache hit on layers 1-2).
Dependency changes rebuild layer 2 in ~30s (cache hit on layer 1).

**Registry-based caching** (`--cache-from`):
```bash
docker build --cache-from registry/actor:cache \
  --cache-to registry/actor:cache \
  -t registry/actor:latest .
```

**Kaniko caching** (for in-cluster builds): Kaniko warmer pre-populates
cache. Persistent volume caching across builds.

### 2.7 Image Streaming (SOCI/Stargz)

**Problem**: Large ML images (5GB+) are slow to pull on cold start.

**SOCI (Seekable OCI by AWS)**: Lazy-loads image layers. Container starts
before full image is downloaded. Reduces startup time by 30-70% for large
images.

**Stargz (Google/containerd)**: Similar lazy loading via eStargz format.

**Relevance**: Critical for KEDA autoscaling (scale-to-zero -> cold start).
Not directly related to build workflow, but affects the deploy step.

---

## 3. Patterns from Other Frameworks

### 3.1 How They Ship Code to K8s

| Framework | Pattern | Docker Knowledge? | GitOps? |
|---|---|---|---|
| **Ray Serve** | Code reference + runtime_env (download from Git) | None | Medium |
| **KServe** | Pre-built runtimes + storage initializer | None (built-in) / Yes (custom) | High |
| **Seldon** | Pre-built servers / S2I / custom image | None / Low / Yes | High |
| **BentoML** | Bento artifact -> containerize -> deploy | Low (bentoml containerize) | High |
| **Flyte** | ImageSpec in Python -> auto-build | None | High |
| **Modal** | Python Image API -> cloud build | None | N/A (serverless) |
| **Dagster** | User builds image, Dagster launches | Yes | Medium |
| **Prefect** | Git-based or Docker-based workers | Low (Git) / Yes (Docker) | Medium |
| **Temporal** | User builds worker image | Yes | Medium |
| **Metaflow** | Decorator-based, conda pack | Low | Medium |

### 3.2 Key Insights

**Zero-Docker achievers**: Modal, Flyte (ImageSpec), KServe (built-in
runtimes), Ray Serve. All solve it differently:
- Modal/Flyte: Python API defines image, framework builds
- KServe/Seldon: Pre-built runtimes, user provides only model/code artifact
- Ray: Downloads code at startup (no build at all)

**Common pattern**: Separate code from environment. Ship code as artifact
(Git, S3, OCI), environment as pre-built image. Combine at deploy time.

**What doesn't work for Asya**:
- Runtime pip install (Ray pattern) -- unreliable for production queue consumers
- Pre-built runtimes with fixed deps (KServe pattern) -- too restrictive for
  diverse actor workloads
- Proprietary cloud builds (Modal) -- vendor lock-in

**What works for Asya**:
- Declarative image spec (Flyte/Modal API) -- inspiration for UX
- Storage initializer (KServe) -- download code at startup, proven for ML
- Code-as-ConfigMap (already used for routers)
- Local interception (mirrord) -- zero build for experimentation

---

## 4. Proposed Architecture: Levels of Sophistication

### Level 0: Zero Build (Local Interception)

**For**: DS experimenting with handler logic. No Docker, no K8s knowledge.

```bash
asya dev handler.py --context=k8s-stg
# Under the hood: mirrord intercepts staging pod,
# runs local Python with remote env/queues
```

DS writes Python, saves file, code runs against real staging queues.
No image build at all.

**Requires**: mirrord installed, kubectl access to staging.

### Level 1: ConfigMap Deploy (No Build)

**For**: Small handler changes, quick iteration on staging.

```bash
asya actor deploy text-analyzer --mode=configmap
# Uploads handler code as ConfigMap
# Uses generic asya-runtime base image
# Restarts pod to pick up new code
```

No Docker build. Code is in ConfigMap (1MB limit). Dependencies must
be in the base image.

**Requires**: Pre-built `asya-runtime` base image with common deps.

### Level 2: Code Sync (Skaffold/Tilt)

**For**: Active development with frequent code changes, occasional dep changes.

```bash
asya dev --mode=sync --context=k8s-stg
# Under the hood: Skaffold/Tilt watches files,
# syncs code changes (1s), rebuilds on dep changes (30s)
```

**Requires**: Dockerfile (auto-generated from build: config), Skaffold or
Tilt installed.

### Level 3: On-Cluster Build (Shipwright)

**For**: Teams that don't want local Docker. Code pushed to Git, built in
cluster.

```bash
asya actor deploy text-analyzer --context=k8s-stg
# Under the hood: Creates Shipwright BuildRun CR,
# builds image in cluster, deploys AsyncActor
```

**Requires**: Shipwright installed in cluster, registry access.

### Level 4: CI/CD Build (Production)

**For**: Production deployments via GitOps.

```bash
git push  # triggers CI pipeline
# CI: asya build render -> docker build -> push to registry
# ArgoCD: detects new image, syncs AsyncActor CRD
```

**Requires**: CI pipeline, container registry, ArgoCD/FluxCD.

---

## 5. Comparison Matrix

| Level | Speed | DS-Friendly | Queue Support | Production | Cluster Deps |
|---|---|---|---|---|---|
| **L0: mirrord** | 0s | 5/5 | 4/5 (split) | No | None |
| **L1: ConfigMap** | 5s | 4/5 | 5/5 | No (1MB limit) | None |
| **L2: Sync** | 1-30s | 3/5 | 3/5 | No | None |
| **L3: Shipwright** | 30s-5min | 4/5 | 5/5 | Staging | Shipwright |
| **L4: CI/CD** | 10-30min | 2/5 | 5/5 | Yes | CI + registry |

---

## 6. Golden Paths

### Golden Path A: DS Experimentation (recommended default)

```
L0 (mirrord) for handler logic
  -> L1 (ConfigMap) for quick staging tests
  -> L4 (CI/CD) when ready for production
```

DS never touches Docker. The transition from L0->L1->L4 is:
1. Write handler locally, test with mirrord against staging queues
2. Deploy to staging via ConfigMap for integration testing
3. Commit code, CI builds proper image, PR for production

### Golden Path B: Active Development

```
L2 (Skaffold sync) for code iteration
  -> L3 (Shipwright) or L4 (CI/CD) for production
```

For developers comfortable with K8s who want fast iteration with full
dependency control.

### Golden Path C: Platform Engineering

```
L4 (CI/CD) for everything
```

Full control, Dockerfiles in git, standard GitOps. No special tools.

---

## 7. Integration with Asya CLI

All levels should be accessible through `asya` commands:

```bash
# Level 0: Local interception
asya dev handler.py --context=k8s-stg

# Level 1: ConfigMap deploy
asya actor deploy text-analyzer --mode=configmap

# Level 2: Code sync (auto-generates Skaffold/Tilt config)
asya dev --mode=sync

# Level 3: On-cluster build
asya actor deploy text-analyzer --builder=shipwright

# Level 4: Render for CI
asya build render text-analyzer  # generates Dockerfile
```

The `asya dev` command is the DS-facing entry point. It picks the best level
based on context and available tools.

---

## 8. Open Questions

1. **mirrord licensing**: mirrord OSS is Apache 2.0 but the company offers
   a commercial product. Need to verify the OSS version supports queue
   splitting for SQS/RabbitMQ.

2. **ConfigMap code deployment**: How to handle dependencies? Options:
   - Pre-built `asya-runtime:3.11-ml` with common ML deps
   - Init container that pip installs from requirements.txt
   - User provides a "requirements layer" as a separate image

3. **Skaffold vs Tilt**: Should Asya recommend one or support both?
   Tilt's Python config is more natural for DS. Skaffold has wider adoption.

4. **Shipwright maturity**: Still CNCF Sandbox. Is it production-ready for
   Asya's use cases? Alternative: Tekton Pipelines directly.

5. **Code streaming for queue consumers**: mirrord queue splitting is
   documented for HTTP but less tested for SQS/RabbitMQ. Need PoC.

6. **SOCI/Stargz adoption**: Is lazy image loading available on major cloud
   K8s providers (EKS, GKE, AKS)?

---

## 9. Implementation Phases

**Phase 1** (MVP): Generate Dockerfile from build inputs (format TBD).
`asya actor deploy` does `docker build + push + kubectl apply`.
Simple, works everywhere.

**Phase 2**: `asya dev handler.py` with mirrord integration for zero-build
experimentation on staging.

**Phase 3**: ConfigMap-based deployment for quick iteration without Docker.

**Phase 4**: Skaffold/Tilt integration for code sync mode.

**Phase 5**: Shipwright integration for on-cluster builds.

---

## Sources

- [Skaffold](https://skaffold.dev/) (Apache 2.0)
- [Shipwright](https://shipwright.io/) (CNCF Sandbox)
- [Tilt](https://tilt.dev/) (Apache 2.0, Docker-owned)
- [mirrord](https://mirrord.dev/) (Apache 2.0)
- [Telepresence](https://www.telepresence.io/) (proprietary since v2)
- [Gefyra](https://gefyra.dev/)
- [DevSpace](https://devspace.sh/)
- [SOCI by AWS](https://github.com/awslabs/soci-snapshotter)
- [KServe](https://kserve.github.io/)
- [Ray Serve](https://docs.ray.io/en/latest/serve/)
- [Flyte ImageSpec](https://docs.flyte.org/en/latest/user_guide/customizing_dependencies/imagespec.html)
- [Modal](https://modal.com/docs/guide/custom-container)
- [BentoML](https://docs.bentoml.com/)
- [K8s Local Dev Tools Comparison](https://kubernetes.io/blog/2023/09/12/local-k8s-development-tools/)
