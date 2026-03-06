# Research: Seamless Image Build and Deploy Workflows

**Date**: 2026-03-05 (updated 2026-03-06)
**Status**: Informational
**Context**: WHERE and HOW actor images are built, and how builds fit into
two distinct user flows: staging experimentation and production GitOps.

**Scope**: This doc covers image build execution and deployment workflows.
It does NOT cover:
- WHAT builds the image (buildpacks, Cog, Dockerfile) -- see
  `research-no-dockerfile.md`
- Local testing without builds (HTTP, mirrord, Skaffold/Tilt) -- see
  `.aint/aints/local-testing/notes-for-rfc.md`

---

## 1. Problem Statement

Building and deploying actor images has two friction points:

1. **WHERE to build**: DS don't want to install Docker locally. Platform
   engineers want reproducible CI builds. Both need to produce the same image.

2. **HOW to deploy**: DS want fast imperative deploys to staging ("just deploy
   my code"). Platform engineers want declarative GitOps for production.

**The bridge**: Same build config (strategy: buildpack/cog/dockerfile) must
work both locally and in-cluster. Same artifacts must transition from
imperative staging to declarative production via git commit.

**Design constraints**:
- Asya does NOT provide base images (decided)
- Build strategy is always explicit (decided, see `research-no-dockerfile.md`)
- Must be modular -- support OCI-as-source-of-truth AND standard GitOps
- Must offer clear golden paths for DS and platform engineers

---

## 2. WHERE Images Are Built

### 2.1 Local Build (Docker / Podman)

**How it works**: User runs build locally. Standard Docker/Podman CLI.

```bash
# With Dockerfile
docker build -t registry/my-actor:v1 .
docker push registry/my-actor:v1

# With Cog
cog build -t registry/my-actor:v1
docker push registry/my-actor:v1

# With Buildpacks
pack build registry/my-actor:v1 --builder paketobuildpacks/builder:base
docker push registry/my-actor:v1
```

**Pros**: Fast iteration, full control, works offline.
**Cons**: Requires Docker installed, inconsistent environments across devs.

**Asya integration**: `asya build` wraps the strategy-specific CLI. Pushes
to configured registry.

### 2.2 On-Cluster Build (Shipwright)

**How it works**: Build runs inside K8s. No local Docker needed.
Shipwright creates Build/BuildRun CRDs that spawn Tekton pods.

```
Source (Git/upload) -> Build CR -> BuildRun CR -> Pod -> Image -> Registry
```

**Build CRD**:
```yaml
apiVersion: shipwright.io/v1beta1
kind: Build
metadata:
  name: my-actor-build
spec:
  source:
    type: Git
    git:
      url: https://github.com/org/actors
  strategy:
    name: buildpacks-v3       # or kaniko, buildah, cog (custom)
    kind: ClusterBuildStrategy
  output:
    image: registry/my-actor:latest
    pushSecret: registry-credentials
```

**Custom build strategies** (e.g., Cog):
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

**Key feature for DS**: No local Docker needed. DS only needs kubectl access.

**On-demand builds without git commit**: Shipwright supports building from
uncommitted local code via two source upload methods:

**Method 1: Streaming** (via `kubectl exec`) -- simplest for DS:
```yaml
# One-time Build CR setup
apiVersion: shipwright.io/v1beta1
kind: Build
metadata:
  name: my-actor
spec:
  source:
    type: Local           # no Git URL needed
  strategy:
    name: buildpacks-v3
  output:
    image: registry/my-actor:latest
    pushSecret: registry-credentials
```
```bash
# Every iteration -- no git commit needed:
shp build upload my-actor
# -> streams tar of working directory to build pod via kubectl exec
# -> pod builds image -> pushes to registry
```
Build pod waits for the CLI to stream source (configurable timeout).
No intermediate storage, no git push, no source bundle registry.

**Method 2: Bundle** (via OCI registry) -- when `kubectl exec` is restricted:
```bash
shp build create my-actor \
  --source-bundle-image registry/my-actor-source \
  --source-bundle-prune AfterPull

shp build upload my-actor
# -> packages local dir as OCI artifact -> pushes to registry
# -> BuildRun pulls source from registry -> builds -> pushes image
```
Works when security policies block `kubectl exec`. Source preserved in
registry for audit/rebuild. Can be pruned after pull.

**Asya integration** for on-demand Shipwright builds:
```bash
asya build my-actor --builder=shipwright
# Under the hood:
# 1. shp build upload (streams local source to cluster)
# 2. Shipwright pod runs buildpacks/cog/kaniko
# 3. Image pushed to registry
# No git commit, no local Docker.

asya deploy my-actor --context=k8s-stg
# -> creates/updates AsyncActor CR referencing built image
```

**Build caching**: Persistent volume cache, registry cache. Cold build
3-5min, cached 30-60s.

**Maturity (2026)**: CNCF Sandbox. Used in OpenShift Builds. Growing
community. `shp` CLI at v0.19.0. Alternative: Tekton Pipelines directly
(more manual, no source upload UX).

### 2.3 CI/CD Build (GitHub Actions / GitLab CI / etc.)

**How it works**: Standard CI pipeline triggered by git push/PR.

```yaml
# .github/workflows/build.yml
on: push
jobs:
  build:
    steps:
      - uses: actions/checkout@v4
      - run: asya build my-actor --push
```

**Pros**: Reproducible, auditable, integrates with existing CI.
**Cons**: Slowest path (10-30min including queue, checkout, build, push).

### 2.4 Comparison

| Dimension | Local | On-Cluster (Shipwright) | CI/CD |
|---|---|---|---|
| Docker required locally | Yes | No | No |
| Git commit required | No | No (source upload) | Yes |
| Build speed (cached) | 5-30s | 30-60s | 1-5min |
| Build speed (cold) | 1-5min | 3-5min | 5-30min |
| Reproducibility | Low (dev env) | High (pod spec) | High (CI env) |
| GitOps integration | Manual push | Build CR watches Git | Native |
| DS-friendliness | 3/5 | 4/5 | 2/5 |
| Strategy support | All | All (custom strategies) | All |

**Key insight**: Local and on-cluster builds should produce **identical**
images given the same inputs. The build strategy (buildpacks/cog/dockerfile)
is the same -- only the execution environment changes.

---

## 3. Source of Truth: Git vs OCI Registry

The critical design question: where is the canonical definition of what
gets deployed?

### 3.1 Git as Source of Truth (Standard GitOps)

```
Git repo (code + build config + K8s manifests)
  -> CI builds image -> pushes to registry
  -> ArgoCD/Flux watches Git -> syncs K8s state
```

**What's in Git**:
- Handler code (`handler.py`)
- Build config (cog.yaml / Dockerfile / buildpacks config)
- AsyncActor manifests (XRD claims)
- Flow definitions (if using flow DSL)

**What's in registry**: Built images only (output artifact).

**Who uses this**: Platform engineers, regulated environments, teams with
existing GitOps workflows.

**Pros**: Full audit trail, PR review for all changes, rollback via git
revert, separation of concerns.

**Cons**: Slow feedback loop for DS (commit -> PR -> CI -> deploy).

### 3.2 OCI Registry as Source of Truth

```
DS builds image (local or on-cluster)
  -> pushes to registry with metadata
  -> ArgoCD Image Updater / Flux Image Automation watches registry
  -> auto-updates K8s manifests when new image tag appears
```

**What's in OCI image** (via labels/annotations):
- Handler code (baked in)
- Build metadata (strategy, git SHA, build time)
- AsyncActor config (as OCI annotations or embedded manifest)

**What's in Git**: Base manifests with image tag placeholder. Updated
automatically by image automation.

**Who uses this**: DS teams wanting fast iteration, ML teams shipping
model+code together.

**Pros**: Fast -- push image, done. No PR required for staging. Image IS
the deployable artifact (reproducible).

**Cons**: Less visibility (no PR review), harder to audit, image sprawl.

### 3.3 Hybrid: Git for Prod, OCI for Staging

```
Staging: DS pushes image -> image automation deploys
Production: PR to update image tag -> ArgoCD syncs
```

**This is the recommended pattern.** It matches the two user flows:
- Staging: imperative, fast, OCI-driven
- Production: declarative, reviewed, Git-driven

**Implementation**:
- Staging namespace: ArgoCD Image Updater watches registry, auto-deploys
  new tags matching pattern (e.g., `stg-*`)
- Production namespace: ArgoCD watches Git, deploys only what's in manifests
- Promotion: DS commits the tested image tag to Git via PR

### 3.4 Comparison

| Aspect | Git SoT | OCI SoT | Hybrid |
|---|---|---|---|
| Deploy speed (staging) | Slow (PR+CI) | Fast (push image) | Fast |
| Deploy speed (prod) | PR merge | Auto-update | PR merge |
| Audit trail | Full (Git) | Partial (OCI metadata) | Full for prod |
| Rollback | `git revert` | Re-tag old image | Both |
| DS friction | High | Low | Low (stg) / Medium (prod) |
| Platform control | Full | Limited | Full for prod |

---

## 4. The Two User Flows

### 4.1 Flow A: DS Experimentation on Staging

**Goal**: DS iterates fast on staging without GitOps ceremony.

```
1. DS writes handler code
2. DS runs: asya build my-actor --push
   (builds locally or triggers on-cluster build, pushes to registry)
3. DS runs: asya deploy my-actor --context=k8s-stg
   (creates/updates AsyncActor CR on staging)
4. DS tests against real queues
5. Repeat 1-4 until satisfied
```

**What's stored locally** (state files, gitignored or in working branch):
- Build config (strategy + deps reference)
- Last deployed image tag
- AsyncActor manifest (rendered)

**No git commit required** in this flow. Cog, buildpacks, and Docker all
work with uncommitted files.

**On-cluster build variant** (DS without Docker):
```
1. DS writes handler code
2. DS runs: asya build my-actor --builder=shipwright --push
   (uploads source to cluster, Shipwright builds + pushes)
3. DS runs: asya deploy my-actor --context=k8s-stg
4. Repeat
```

### 4.2 Flow B: Production via GitOps

**Goal**: Promote tested staging artifacts to production via PR.

```
1. DS finishes experimentation on staging (Flow A)
2. DS runs: asya commit my-actor
   (writes build config + manifest to git-tracked files)
3. DS creates PR with:
   - Build config (cog.yaml / Dockerfile / buildpacks config)
   - AsyncActor manifest (XRD claim)
   - Handler code
4. CI builds image from committed config
5. PR review + merge
6. ArgoCD/Flux deploys to production
```

**What gets committed**:
```
actors/my-actor/
  handler.py              # handler code
  requirements.txt        # dependencies
  cog.yaml                # build config (or Dockerfile, etc.)
  asyncactor.yaml         # AsyncActor XRD claim
```

**Key principle**: The committed files are the source of truth for production.
CI rebuilds the image from these files (not from the staging image). This
ensures reproducibility and auditability.

**Alternative**: Teams that trust staging images can promote by tag:
```
1. DS tags staging image as production: asya promote my-actor stg-abc123 -> prod-v1.2
2. PR updates only the image tag in manifests (no rebuild)
```

### 4.3 Flow Transition: Staging to Production

The transition point is `asya commit` (or equivalent). This command:

1. Reads current local state (build config, manifest, image tag)
2. Writes git-tracked files in a conventional structure
3. DS creates PR from these files

**State lifecycle**:
```
Local state (ephemeral, .asya/ or working dir)
  -> asya commit -> Git-tracked files (permanent)
  -> PR merge -> ArgoCD/Flux deploys to prod
```

**The build config is always in files** -- whether gitignored during
experimentation or committed for production. Same format, same files,
just different lifecycle.

---

## 5. Build Execution Architecture

### 5.1 Pluggable Build Execution

Build strategy (WHAT builds) and build execution (WHERE it runs) are
independent axes:

```
            | Local Docker | Shipwright | CI/CD |
------------|-------------|------------|-------|
Buildpacks  | pack build  | buildpacks | pack  |
            |             | strategy   | build |
------------|-------------|------------|-------|
Cog         | cog build   | cog custom | cog   |
            |             | strategy   | build |
------------|-------------|------------|-------|
Dockerfile  | docker      | kaniko     | docker|
            | build       | strategy   | build |
```

**Same strategy, different execution**. The `asya build` command abstracts
this: `--builder=local` (default), `--builder=shipwright`, or CI picks
the right one.

### 5.2 Build Caching

Regardless of where the build runs, caching is critical for fast iteration:

**Docker layer caching** (local and CI):
```bash
docker build --cache-from registry/actor:cache \
  --cache-to registry/actor:cache \
  -t registry/actor:latest .
```

**Kaniko caching** (for on-cluster Shipwright builds):
- Kaniko warmer pre-populates cache
- Persistent volume caching across builds

**Buildpacks caching**: Built-in layer caching. Rebase for OS-only updates.

**Cog caching**: Standard Docker layer caching. Code-only changes rebuild
in ~3-5s (deps layers cached).

### 5.3 Image Streaming (SOCI/Stargz)

Large ML images (5GB+) are slow to pull on cold start. Relevant for KEDA
scale-to-zero:

- **SOCI (AWS)**: Lazy-loads image layers. Container starts before full
  download. 30-70% startup reduction.
- **Stargz (Google/containerd)**: Similar lazy loading via eStargz format.

Not directly a build concern, but affects the deploy step performance.

---

## 6. Patterns from Other Frameworks

### 6.1 How They Handle Build + Deploy

| Framework | Build WHERE | Source of Truth | Staging Flow | Prod Flow |
|---|---|---|---|---|
| **BentoML** | Local (bento build) | OCI (Bento artifact) | Push bento | CI + deploy |
| **Flyte** | Local (ImageSpec) | Git (Python code) | Register task | CI + register |
| **Modal** | Cloud (serverless) | Python code | Deploy | Same |
| **KServe** | Pre-built / CI | Git (InferenceService) | kubectl apply | GitOps |
| **Seldon** | CI / S2I | Git (SeldonDeployment) | kubectl apply | GitOps |
| **Ray Serve** | None (runtime) | Git (serve config) | ray serve | GitOps |

### 6.2 Key Insights

**BentoML pattern** (closest to Asya's needs):
- `bentoml build` creates a "Bento" (code + deps + model as OCI artifact)
- `bentoml containerize` wraps it in a Docker image
- `bentoml deploy` pushes to BentoCloud or K8s
- Staging: imperative `bentoml deploy`
- Production: CI builds Bento, pushes, GitOps deploys

**Flyte ImageSpec**: Build triggered automatically when image hash changes.
Checks registry first (hash-based dedup). No manual build step.

**Common pattern**: Build locally or in CI, push OCI artifact, deploy via
GitOps or imperative command. The difference is whether OCI or Git is the
source of truth for what's deployed.

---

## 7. Proposed Architecture

### 7.1 Core Principle: Same Config, Different Lifecycle

```
Build config (strategy + deps + code)
  |
  +-- Experimentation: local files, gitignored, imperative deploys
  |     asya build -> asya deploy --context=k8s-stg
  |
  +-- Production: committed to git, CI builds, GitOps deploys
        asya commit -> PR -> CI -> ArgoCD/Flux
```

### 7.2 `asya build` Command

```bash
# Local build (default)
asya build my-actor
# -> reads build config -> runs strategy (cog/buildpacks/docker) locally
# -> pushes to configured registry

# On-cluster build
asya build my-actor --builder=shipwright
# -> uploads source to cluster
# -> creates Shipwright BuildRun CR
# -> waits for build -> image in registry
```

### 7.3 `asya deploy` Command

```bash
# Imperative deploy to staging
asya deploy my-actor --context=k8s-stg
# -> creates/updates AsyncActor CR
# -> references latest built image

# Writes manifest for GitOps
asya deploy my-actor --context=k8s-prod --dry-run > asyncactor.yaml
# -> generates manifest for git commit
```

### 7.4 `asya commit` Command

```bash
asya commit my-actor
# -> writes to git-tracked directory:
#    actors/my-actor/handler.py
#    actors/my-actor/requirements.txt
#    actors/my-actor/cog.yaml (or Dockerfile, etc.)
#    actors/my-actor/asyncactor.yaml
```

### 7.5 Modularity: Supporting Both OCI and GitOps Teams

**For OCI-first teams** (staging + simple prod):
- Build and push images imperatively
- ArgoCD Image Updater auto-deploys new tags
- No `asya commit` needed -- OCI registry is the source of truth

**For GitOps teams** (enterprise / regulated):
- All config in Git, CI builds from committed files
- `asya commit` transitions from experimentation to GitOps
- ArgoCD/Flux watches Git, not registry

**For hybrid teams** (recommended):
- OCI-driven staging (fast), Git-driven production (auditable)
- `asya commit` + PR is the promotion gate

---

## 8. Open Questions

1. **Shipwright maturity**: Still CNCF Sandbox. Is it production-ready for
   Asya's use cases? Alternative: Tekton Pipelines directly. Or: skip
   on-cluster builds initially, revisit when demand exists.

2. **ArgoCD Image Updater vs Flux Image Automation**: Which to recommend
   for OCI-driven staging deploys? Both watch registries for new tags.

3. **`asya commit` file structure**: What's the conventional directory
   layout for committed actor configs? Per-actor directories? Monorepo
   vs polyrepo?

4. **Image tag strategy**: How to tag staging vs production images?
   `stg-<sha>` / `prod-v1.2`? Semantic versioning? Hash-based (Flyte)?

5. **Source upload for Shipwright**: How does DS upload local (uncommitted)
   code to Shipwright? Git push to temp branch? Source bundle upload?
   Shipwright supports both but UX differs.

6. **SOCI/Stargz adoption**: Is lazy image loading available on major cloud
   K8s providers (EKS, GKE, AKS)? Critical for KEDA scale-to-zero with
   large ML images.

---

## Sources

- [Shipwright](https://shipwright.io/) (CNCF Sandbox)
- [ArgoCD Image Updater](https://argocd-image-updater.readthedocs.io/)
- [Flux Image Automation](https://fluxcd.io/flux/guides/image-update/)
- [SOCI by AWS](https://github.com/awslabs/soci-snapshotter)
- [BentoML](https://docs.bentoml.com/)
- [Flyte ImageSpec](https://docs.flyte.org/en/latest/user_guide/customizing_dependencies/imagespec.html)
- [KServe](https://kserve.github.io/)
- [Kaniko](https://github.com/GoogleContainerTools/kaniko)
