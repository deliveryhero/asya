# Research: Seamless Image Build and Deploy Workflows

**Date**: 2026-03-05 (updated 2026-03-06)
**Status**: Informational
**Context**: WHERE and HOW actor images are built, and how builds fit into
two distinct user flows: staging experimentation and production GitOps.

UPD 2026-03-07: NOTE: Asya is a thin command runner for builds, not a build system.

UPD 2026-03-09: NOTE: The Docker Compose deployment path described in this doc
is superseded by the K8s/Docker command split in `adr.k-d-command-split.md`.
Command references below have been updated to reflect the new CLI surface
(`asya k build`, `asya k deploy`, etc.).

**Scope**: This doc covers image build execution and deployment workflows.
It does NOT cover:
- WHAT builds the image (apko, buildpacks, Dockerfile) -- see
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

**The bridge**: Same build config (strategy: apko/buildpack/dockerfile) must
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

# With apko
apko build apko.yaml registry/my-actor:v1 --lockfile actor-image.lock
docker push registry/my-actor:v1

# With Buildpacks
pack build registry/my-actor:v1 --builder paketobuildpacks/builder:base
docker push registry/my-actor:v1
```

**Pros**: Fast iteration, full control, works offline.
**Cons**: Requires Docker installed, inconsistent environments across devs.

**Asya integration**: `asya k build` wraps the strategy-specific CLI. Pushes
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
    name: buildpacks-v3       # or kaniko, buildah, apko (custom)
    kind: ClusterBuildStrategy
  output:
    image: registry/my-actor:latest
    pushSecret: registry-credentials
```

**Custom build strategies** (e.g., apko):
```yaml
apiVersion: shipwright.io/v1beta1
kind: ClusterBuildStrategy
metadata:
  name: apko-build
spec:
  steps:
    - name: apko-build
      image: cgr.dev/chainguard/apko:latest
      command: ["apko", "build", "apko.yaml", "$(params.output-image)", "--lockfile", "actor-image.lock"]
```

**Key feature for DS**: No local Docker needed. DS only needs kubectl access.

**On-demand builds without git commit**: Shipwright supports building from
uncommitted local code via two source upload methods:

**Method 1: Streaming** (`source.type: Local`) -- simplest for DS:
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
# -> creates BuildRun, streams tar to build pod, pod builds + pushes
```

**How streaming works internally**:

1. `shp build upload` creates a new BuildRun, watches for pod `Running`
2. Build pod starts with a **waiter step** (`step-source-local`) -- a
   binary that creates a lock file (`/shp-tmp/waiter.lock`) and polls
   every 100ms. Default timeout: 60s.
3. CLI streams source via `kubectl exec`:
   ```
   local dir -> tar in-memory -> io.Pipe() -> kubectl exec stdin ->
   "tar --no-same-permissions -xvf - -C /workspace/source"
   (inside the waiter container)
   ```
4. CLI signals done via another exec: `waiter done` (deletes lock file).
   Waiter exits, Tekton proceeds to build strategy steps.

**File filtering**: `.git/` always excluded (hardcoded). `.gitignore`
respected. `.dockerignore` NOT respected. No custom exclude patterns.

**Security**: Requires `pods/exec` RBAC permission. Waiter runs non-root
(UID 1000), read-only rootfs, all capabilities dropped. Source lives in
EmptyDir -- ephemeral, destroyed with the pod. No registry credentials
needed for the data transfer itself.

**Iteration model**: Each `shp build upload` creates a **new BuildRun** --
cannot re-upload to an existing one. Can run repeatedly against the same
Build CR for iterative development.

**Method 2: Bundle** (`source.type: OCI`) -- when `kubectl exec` is
restricted:
```bash
shp build create my-actor \
  --source-bundle-image registry/my-actor-source \
  --source-bundle-prune AfterPull

shp build upload my-actor
# -> packages local dir as OCI artifact -> pushes to registry
# -> BuildRun pulls source from registry -> builds -> pushes image
```

**How bundle mode differs**: CLI packages source as an OCI image, pushes
to registry. Build pod pulls it instead of receiving via exec. Uses
`.shpignore` (Shipwright-specific, gitignore syntax) for file filtering.
Requires Docker registry credentials but NOT `pods/exec` RBAC. Source
preserved in registry for audit/rebuild. Can be pruned after pull.

| Aspect | Streaming (Local) | Bundle (OCI) |
|---|---|---|
| Data path | kubectl exec stdin -> pod | CLI -> registry -> pod |
| Registry needed | No | Yes |
| RBAC | pods/exec | registry credentials |
| File filtering | .gitignore | .shpignore |
| Audit trail | None (ephemeral) | Source in registry |

**Asya integration** for on-demand Shipwright builds:
```bash
asya k build my-actor --builder=shipwright
# Under the hood:
# 1. shp build upload (streams local source to cluster)
# 2. Shipwright pod runs buildpacks/apko/kaniko
# 3. Image pushed to registry
# No git commit, no local Docker.

asya k deploy my-actor --context stg
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
      - run: asya k build my-actor --push
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
images given the same inputs. The build strategy (apko/buildpacks/dockerfile)
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
- Build config (apko.yaml / Dockerfile / buildpacks config)
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

### 3.3 Hybrid: Git for Prod, OCI for Staging (Default Showcase)

```
Staging: DS builds image -> pushes -> image automation deploys
Production: PR with source + image digest -> review -> ArgoCD syncs
```

**This is the default showcase pattern.** Asya supports all three natively,
but the hybrid flow is the recommended starting point. It matches the two
user flows:
- Staging: imperative, fast, OCI-driven
- Production: declarative, reviewed, Git-driven

**The lock file model**: `actor-image.lock` -- a content-addressed lock
file for image build inputs.

| Concept | npm/yarn | Asya |
|---|---|---|
| Intent (human) | `package.json` | handler.py, requirements.txt, apko.yaml |
| Lock file | `package-lock.json` | `actor-image.lock` |
| Resolve command | `npm install` | `asya k build` (updates lock) |
| Lock command | `npm install` | `asya actor lock` / `asya flow lock` |
| Verify consistency | `npm ci` | CI checks lock vs image |
| Commit both | Yes | Yes |

**What `actor-image.lock` contains**: A hash of **build inputs only** --
handler code, requirements, build config. NOT the XR (AsyncActor CR),
NOT the actor name, NOT the image digest. It locks what goes INTO the
image, not the image itself.

```yaml
# actor-image.lock (generated by asya actor lock / asya k build)
version: 1
input_hash: sha256:e3b0c44298fc1c14...   # hash of all build inputs below
image: registry/my-actor@sha256:abc123... # resolved image for this input hash
inputs:
  handler.py: sha256:a1b2c3...
  requirements.txt: sha256:d4e5f6...
  apko.yaml: sha256:789abc...
strategy: apko
locked_at: 2026-03-06T14:30:00Z
```

**Key property**: Two builds from source files with the same `input_hash`
SHOULD produce images with the same digest. The lock file is the bridge --
it maps "I reviewed this source" to "deploy this exact image."

**Prior art: apko** (Chainguard) is the only existing tool that implements
an explicit lock file for container image builds:
- `apko lock` resolves all APK packages → `.lock.json` with exact versions
  and cryptographic checksums
- `apko build --lockfile=lock.json` builds from pinned deps
- Produces **bit-for-bit reproducible** images
- Works because apko is declarative (no `RUN` commands, just APK packages)

**Other tools with input hashing** (but no lock file):
- **Flyte ImageSpec**: hashes spec (base image, packages, source) as the
  image tag. Skips build if tag already exists in registry. No lock file.
- **Nix dockerTools**: content-addressed derivations. Same inputs → same
  store hash → same image. `flake.lock` pins inputs but is general-purpose.
- **ko** (Go): Go build ID as content hash. Replaces import paths with
  digests in YAML. No lock file.
- **Bazel rules_oci**: action key from input digests. Hermetic, reproducible.
  `MODULE.bazel.lock` is general-purpose.

**Why apko's approach doesn't fully apply to Asya**: apko achieves
bit-for-bit reproducibility because it is purely declarative (no `RUN`
commands). Dockerfile and buildpack builds execute arbitrary commands, which
execute arbitrary commands (`pip install`, `apt-get`). True bit-for-bit
reproducibility requires pinning every transitive dependency version, which
is what `pip freeze > requirements.txt` or `uv pip compile` does for Python
but not for system packages or base image layers.

**Practical reproducibility for Asya**: Even without bit-for-bit guarantees,
`actor-image.lock` provides:
- **Input drift detection**: if source files changed since last build, the
  lock file is stale → `asya promote` refuses until you rebuild
- **Registry dedup**: if `input_hash` matches an existing tag, skip build
  (Flyte's pattern)
- **Audit trail**: lock file in git records exactly which source produced
  which image, reviewable in PR diffs

**Commands**:
```bash
# Lock a single actor's build inputs
asya actor lock my-actor
# -> computes input_hash from handler.py + requirements.txt + build config
# -> writes/updates actor-image.lock

# Lock all actors in a flow (routers + handlers)
asya flow lock my-flow
# -> runs asya actor lock for each actor in the flow

# Build (also updates lock)
asya k build my-actor
# -> builds image, pushes to registry
# -> updates actor-image.lock with input_hash + image digest
```

**The key question: what goes into the production PR?**

Three promotion strategies (ordered by how much of the lock file pattern
they follow):

#### Strategy A: Lock File Only (no source in PR)

*Analogy: committing only `package-lock.json` without `package.json`.*

PR contains:
```
actors/my-actor/
  actor-image.lock          # input_hash + image digest
  asyncactor.yaml           # image: registry/my-actor@sha256:abc123...
```

- The exact image tested on staging goes to production
- No rebuild -- what you tested = what you deploy
- Source code is NOT in the PR (it's baked into the image)
- Audit trail: lock file records input_hash, image digest is immutable

**Pros**: Fastest promotion, guaranteed identical behavior.
**Cons**: Reviewers can't see source code in the PR diff.

#### Strategy B: Source Only, CI Resolves (no lock file)

*Analogy: committing only `package.json`, letting CI run `npm install`.*

PR contains:
```
actors/my-actor/
  handler.py                # handler code
  requirements.txt          # dependencies
  apko.yaml                  # build config (or Dockerfile, etc.)
  asyncactor.yaml           # image tag TBD -- CI fills in after build
```

- CI rebuilds image from committed source (runs `asya k build`)
- CI updates asyncactor.yaml with the built image digest
- The production image is different from staging (re-resolved)

**Pros**: Full source audit in PR, reviewers see code. Standard GitOps.
**Cons**: Like `npm install` vs `npm ci` -- rebuild may resolve different
versions (base image layers, pip deps). Slower (5-30min). Not identical
to what was tested on staging.

#### Strategy C: Source + Lock File (default)

*Analogy: committing both `package.json` and `package-lock.json`.*

PR contains:
```
actors/my-actor/
  handler.py                # handler code (for review)
  requirements.txt          # dependencies (for review)
  apko.yaml                  # build config (for review)
  actor-image.lock          # input_hash + pinned image digest
  asyncactor.yaml           # image: registry/my-actor@sha256:abc123...
```

**How it works step by step**:

1. DS runs `asya promote my-actor`. The command:
   - Reads `actor-image.lock` (input_hash + image digest)
   - Computes current input_hash from source files in working directory
   - **Compares**: if input_hash differs from lock, `asya promote` refuses:
     "Source changed since last build. Run `asya k build` first."
   - If match: copies source files + lock file + asyncactor.yaml into
     git-tracked dir, creates branch + PR

2. **Reviewer** sees the full PR diff: handler code, dependencies, build
   config, lock file, AND the AsyncActor manifest. They review code normally.

3. **CI runs a safety-net check** (~seconds, not a rebuild):
   - Computes input_hash from source files in the PR
   - Compares against input_hash in `actor-image.lock`
   - Should always pass (since `asya promote` already verified)
   - Fails only in edge cases: someone edited source files after promote,
     manual PR creation bypassing `asya promote`, race conditions

4. **On PR merge**: ArgoCD/Flux deploys the pinned digest from
   asyncactor.yaml. No build -- the image is already in the registry.

**When does CI verification fail?** Almost never in normal workflow,
because `asya promote` catches drift before creating the PR. Edge cases:
- Someone pushes a commit to the PR branch modifying source files
  without rebuilding
- Someone manually creates a PR bypassing `asya promote`
- Race condition: another DS pushes to the same PR branch

CI verification is a safety net, not a regular gate.

**Why not just rebuild in CI (Strategy B)?**
- Rebuilds are not deterministic. Base image layers update, `pip install`
  resolves different patch versions, build environment differs. The
  staging-tested image is the known-good artifact.
- CI rebuild adds 5-30min to the PR cycle.
- For ML actors with large models baked in, rebuilding is expensive and
  wasteful.

**Pros**: Reviewers see source code. Production deploys the exact tested
image. Drift caught early by `asya promote`. Lock file is the single
source of truth for "was this image built from this source?"
**Cons**: Extra file to manage (`actor-image.lock`), but it's auto-generated
by `asya k build`.

#### Recommendation

**Default**: Strategy C (source + lock file). The `actor-image.lock` file
is the bridge between human-readable source (for review) and machine-
deployable image digest (for production). `asya promote` enforces
consistency before creating the PR. CI re-verifies as safety net.
Teams can simplify to A (lock file only) or B (source only, CI rebuilds)
based on their policy.

### 3.4 Comparison

| Aspect | Git SoT | OCI SoT | Hybrid |
|---|---|---|---|
| Deploy speed (staging) | Slow (PR+CI) | Fast (push image) | Fast |
| Deploy speed (prod) | PR merge | Auto-update | PR merge |
| Audit trail | Full (Git) | Partial (OCI metadata) | Full for prod |
| Rollback | `git revert` | Re-tag old image | Both |
| DS friction | High | Low | Low (stg) / Medium (prod) |
| Platform control | Full | Limited | Full for prod |

| Promotion | What's in PR | Rebuild? | Identical to staging? |
|---|---|---|---|
| **A: Lock only** | Lock + manifest | No | Yes (same image) |
| **B: Source only** | Source + config | Yes (CI resolves) | No (rebuilt) |
| **C: Source+Lock** | Source + lock + manifest | No (verify only) | Yes (pinned digest) |

---

## 4. The Two User Flows

### 4.1 Flow A: DS Experimentation on Staging

**Goal**: DS iterates fast on staging without GitOps ceremony.

```
1. DS writes handler code
2. DS runs: asya k build my-actor --push
   (builds locally or triggers on-cluster build, pushes to registry)
3. DS runs: asya k deploy my-actor --context stg
   (creates/updates AsyncActor CR on staging)
4. DS tests against real queues
5. Repeat 1-4 until satisfied
```

**What's stored locally** (state files, gitignored or in working branch):
- Build config (strategy + deps reference)
- Last deployed image tag
- AsyncActor manifest (rendered)

**No git commit required** in this flow. apko, buildpacks, and Docker all
work with uncommitted files.

**On-cluster build variant** (DS without Docker):
```
1. DS writes handler code
2. DS runs: asya k build my-actor --builder=shipwright --push
   (uploads source to cluster, Shipwright builds + pushes)
3. DS runs: asya k deploy my-actor --context stg
4. Repeat
```

### 4.2 Flow B: Production via GitOps

**Goal**: Promote tested staging actor to production via PR.

```
1. DS finishes experimentation on staging (Flow A)
2. DS runs: asya promote my-actor
3. Asya verifies actor-image.lock is fresh, generates PR (Strategy C)
4. Reviewer sees code diff + lock file + knows exact image tested
5. PR merge -> ArgoCD/Flux deploys to production
```

**What `asya promote` does**:

```bash
asya promote my-actor --context prod
# 1. Reads actor-image.lock (input_hash + image digest)
# 2. Computes current input_hash from source files
# 3. If input_hash differs: ERROR "Source changed. Run asya k build first."
# 4. If match: writes git-tracked files:
#    actors/my-actor/handler.py
#    actors/my-actor/requirements.txt
#    actors/my-actor/apko.yaml
#    actors/my-actor/actor-image.lock  (input_hash + image digest)
#    actors/my-actor/asyncactor.yaml   (with pinned image digest)
# 5. Creates branch + PR (or outputs files for manual PR)
```

**Generated asyncactor.yaml** (pinned to tested image):
```yaml
apiVersion: asya.dev/v1alpha1
kind: AsyncActor
metadata:
  name: my-actor
  labels:
    asya.sh/promoted-from: stg
    asya.sh/build-strategy: apko
spec:
  image: registry/my-actor@sha256:abc123...  # exact staging image
  transport: sqs
  handler: my_module.process
```

**CI behavior** (configurable per team):
- **Strategy A teams**: CI skips build, deploys pinned digest directly
- **Strategy B teams**: CI rebuilds from source, ignores pinned digest
- **Strategy C teams** (default): CI optionally verifies reproducibility
  (rebuild + compare), deploys pinned digest

**What reviewers see in the PR**:
```diff
+ actors/my-actor/handler.py          # full handler code
+ actors/my-actor/requirements.txt    # pinned dependencies
+ actors/my-actor/apko.yaml            # build config
+ actors/my-actor/actor-image.lock    # input_hash + image digest
+ actors/my-actor/asyncactor.yaml     # XRD claim with image digest
```

### 4.3 Flow Transition: Staging to Production

**State lifecycle**:
```
Local working dir (ephemeral, uncommitted)
  -> asya k build + asya k deploy (staging, OCI-driven)
  -> asya promote (generates git-tracked files + PR)
  -> PR review + merge (production, Git-driven)
  -> ArgoCD/Flux deploys to prod
```

**The build config is always in files** -- whether uncommitted during
experimentation or committed for production. Same format, same files,
just different lifecycle. `asya promote` is the bridge.

**Dockerfile users skip `asya promote`**: The lock file flow (Strategies
A/B/C, `asya promote`, `actor-image.lock`) only applies to the apko path.
Dockerfile users follow a traditional workflow: commit Dockerfile + source
to git, CI runs `docker build`, ArgoCD deploys. No lock file, no `asya
promote`. Asya does not provide special tooling for the Dockerfile escape
hatch.

**Teams can customize the promotion gate** (apko path only):
- DS teams: `asya promote` auto-creates PR with source + digest
- Platform teams: require `asya promote --rebuild` (Strategy B, CI rebuilds)
- Regulated teams: require `asya promote --verify` (Strategy C, CI verifies
  reproducibility before deploying pinned digest)

---

## 5. Build Execution Architecture

### 5.1 Pluggable Build Execution

Build strategy (WHAT builds) and build execution (WHERE it runs) are
independent axes:

```
            | Local        | Shipwright | CI/CD       | Lock file? |
------------|-------------|------------|-------------|------------|
apko        | apko build  | apko       | apko build  | YES        |
            |             | strategy   |             |            |
------------|-------------|------------|-------------|------------|
Buildpacks  | pack build  | buildpacks | pack build  | Partial    |
            |             | strategy   |             |            |
------------|-------------|------------|-------------|------------|
Dockerfile  | docker      | kaniko     | docker      | NO         |
            | build       | strategy   | build       | (escape)   |
```

**Same strategy, different execution**. The `asya k build` command abstracts
this: `--builder=local` (default), `--builder=shipwright`, or CI picks
the right one.

**Lock file availability**: Only the apko path produces a true
`actor-image.lock`. Dockerfile is the escape hatch -- no locking, no
`asya promote`, traditional local build + GitOps flow.

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

**apko caching**: Lock file ensures identical package resolution. No layer
caching needed -- same inputs always produce the same image.

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
  |     asya k build -> asya k deploy --context stg
  |
  +-- Production: committed to git, CI builds, GitOps deploys
        asya promote -> PR -> CI -> ArgoCD/Flux
        (note: `asya commit` concept is superseded by `asya promote`)
```

### 7.2 `asya k build` Command

```bash
# Build only (default)
asya k build my-actor
# -> reads build config -> runs command locally
# -> image stays on machine, no registry push

# Build + push to registry
asya k build my-actor --push
# -> runs command + pushes image to configured registry

# On-cluster build (future, requires shipwright: config)
# asya k build my-actor --remote
# -> creates Shipwright BuildRun CR, no local command needed
```

### 7.3 `asya k deploy` Command

```bash
# Imperative deploy to staging
asya k deploy my-actor --context stg
# -> creates/updates AsyncActor CR
# -> references latest built image

# Writes manifest for GitOps
asya k deploy my-actor --context prod --dry-run > asyncactor.yaml
# -> generates manifest for git commit
```

### 7.4 `asya commit` Command (SUPERSEDED)

NOTE: This command is superseded by `asya promote`. The `asya commit` concept
of duplicating code into a git-tracked directory was rejected. Use
`asya promote` instead (see section 4.2).

USER: I don't like this command, I don't think it makes sense to duplicate code in the repository. Need to re-think this.

```bash
asya commit my-actor
# -> writes to git-tracked directory:
#    actors/my-actor/handler.py
#    actors/my-actor/requirements.txt
#    actors/my-actor/apko.yaml (or Dockerfile, etc.)
#    actors/my-actor/asyncactor.yaml
```

### 7.5 Modularity: Supporting Both OCI and GitOps Teams

**For OCI-first teams** (staging + simple prod):
- Build and push images imperatively
- ArgoCD Image Updater auto-deploys new tags
- No `asya promote` needed -- OCI registry is the source of truth

**For GitOps teams** (enterprise / regulated):
- All config in Git, CI builds from committed files
- `asya promote` transitions from experimentation to GitOps
- ArgoCD/Flux watches Git, not registry

**For hybrid teams** (recommended):
- OCI-driven staging (fast), Git-driven production (auditable)
- `asya promote` + PR is the promotion gate

---

## 8. Open Questions

1. **Shipwright maturity**: Still CNCF Sandbox. Is it production-ready for
   Asya's use cases? Alternative: Tekton Pipelines directly. Or: skip
   on-cluster builds initially, revisit when demand exists.

2. **ArgoCD Image Updater vs Flux Image Automation**: Which to recommend
   for OCI-driven staging deploys? Both watch registries for new tags.

3. ~~**`asya commit` file structure**~~: Superseded by `asya promote`. What's the conventional directory
   layout for committed actor configs? Per-actor directories? Monorepo
   vs polyrepo?

4. **Image tag strategy**: How to tag staging vs production images?
   `stg-<sha>` / `prod-v1.2`? Semantic versioning? Hash-based (Flyte)?

5. ~~**Source upload for Shipwright**~~: **Resolved** -- Shipwright supports
   streaming (via `kubectl exec`, simplest) and bundle (via OCI registry,
   when exec is restricted). See section 2.2.

6. **SOCI/Stargz adoption**: Is lazy image loading available on major cloud
   K8s providers (EKS, GKE, AKS)? Critical for KEDA scale-to-zero with
   large ML images.

7. **Reproducibility depth**: `actor-image.lock` hashes build inputs
   (handler code, requirements, build config). This catches source drift
   but does NOT guarantee bit-for-bit identical images (pip may resolve
   different transitive deps, base image layers may update). How far to go?
   - Level 1: input hash only (what we propose) -- catches drift
   - Level 2: + pinned pip deps via `uv pip compile` / `pip freeze`
   - Level 3: + pinned base image by digest (not tag)
   - Level 4: apko-style fully declarative (no `RUN` commands) -- bit-for-bit
   Each level adds complexity. Level 1 is the practical starting point.

8. **Lock file scope**: Should `actor-image.lock` also include the
   build strategy version (e.g., buildpacks builder version, apko version)?
   This affects whether the same source + same lock produces the same
   image across different developer machines.

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
