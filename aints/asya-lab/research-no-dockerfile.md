# Research: Avoiding Dockerfiles for Asya Actors

**Date**: 2026-03-05
**Status**: Informational
**Context**: How to eliminate Dockerfiles for some actors while keeping them
optional. Must be modular, composable, non-opinionated.

---

## 1. Problem Statement

Asya actors are Python handler functions deployed in containers on K8s. Today,
each actor needs a Dockerfile. Data scientists find Dockerfiles intimidating
(OS packages, CUDA versions, layer optimization, security patching). Platform
engineers want Dockerfiles for auditability.

**Goal**: Provide Dockerfile-less paths for DS while keeping Dockerfile-based
paths for platform engineers. The system must be modular -- no lock-in to any
single builder tool.

**Design constraint**: Asya defines a `build:` config in actor.yaml that
describes build intent in DS-friendly terms:

```yaml
build:
  python: "3.11"
  requirements: requirements.txt
  packages: [ffmpeg]
  gpu: true
```

This intent can be translated to different build artifacts depending on the
selected strategy.

---

## 2. Tool Analysis

### 2.1 Cloud Native Buildpacks (CNCF)

**How it works**: Auto-detects language from source files (requirements.txt,
pyproject.toml, uv.lock), builds OCI image without Dockerfile.

**Python detection precedence**:
1. `requirements.txt` -> pip
2. `poetry.lock` + `pyproject.toml` -> Poetry
3. `uv.lock` -> uv (fast)
4. `pyproject.toml` alone -> defaults to uv

**Customization via project.toml**:
```toml
[_]
schema-version = "0.2"

[[io.buildpacks.build.env]]
name = "BP_CPYTHON_VERSION"
value = "3.11"
```

**GPU/CUDA**: NOT auto-detected. Requires custom run image override:
```bash
pack build my-actor \
  --builder gcr.io/buildpacks/builder:v1 \
  --run-image nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04
```

**System packages**: No native support. Workarounds: custom run image or
Paketo apt buildpack with `apt.yml`.

**Rebase**: Killer feature -- swap OS layers without rebuilding app. Security
patches in milliseconds. No other tool offers this.

**Translation from actor.yaml `build:`**:
- `python:` -> `BP_CPYTHON_VERSION` env var
- `requirements:` -> auto-detected from file
- `packages:` -> requires custom run image (limitation)
- `gpu:` -> requires custom run image (limitation)

**Verdict**: Excellent for standard Python actors (no GPU, no system packages).
Poor for ML/GPU workloads. Rebase capability is unique and valuable for
security.

| Dimension | Rating |
|---|---|
| DS-friendliness | 4/5 (zero config for simple cases) |
| GPU/CUDA | 2/5 (manual run image) |
| System packages | 2/5 (custom run image or apt buildpack) |
| Build speed (cached) | 4/5 (20-40s with uv) |
| Security | 5/5 (rebase, SBOM) |
| Maintenance burden | 3/5 (need to maintain custom run images for GPU) |

### 2.2 Cog (Replicate)

**How it works**: ML-specific builder. `cog.yaml` declares environment
(Python, GPU, CUDA, system packages). Auto-detects CUDA version from
PyTorch/TensorFlow versions.

**cog.yaml schema** (key fields):
```yaml
build:
  gpu: true
  cuda: "12.1"          # optional, auto-detected from torch version
  python_version: "3.11"
  python_requirements: requirements.txt
  system_packages: [ffmpeg, libsndfile1]
predict: "handler.py:Predictor"
```

**CUDA auto-detection**: Reads torch/tensorflow version from requirements,
consults internal compatibility matrix (`pkg/config/cuda_base_images.json`),
selects matching NVIDIA base image and cuDNN. Supports CUDA 11.0-12.x.

**Standalone usage**: YES. Apache 2.0 license. No Replicate dependency.
```bash
cog build -t my-actor:latest    # builds Docker image locally
docker push registry/my-actor   # push to any registry
```

**Stripping the inference server**: Cog bundles an HTTP server (Rust/Axum).
Asya doesn't need it (sidecar pattern). Options:
1. `cog debug > Dockerfile` -- generates Dockerfile, modify to remove server
2. Override entrypoint in K8s spec: `command: ["python", "asya_runtime.py"]`
3. Use Cog purely for build environment setup

**Translation from actor.yaml `build:`**:
- `python:` -> `python_version:`
- `requirements:` -> `python_requirements:`
- `packages:` -> `system_packages:`
- `gpu:` -> `gpu: true` (auto-detects CUDA)

**Verdict**: Best DS experience for GPU/ML actors. Auto CUDA detection is
the killer feature. Bundled inference server is a concern but can be worked
around.

| Dimension | Rating |
|---|---|
| DS-friendliness | 5/5 (simplest config for ML) |
| GPU/CUDA | 5/5 (auto-detection) |
| System packages | 5/5 (native apt support) |
| Build speed (cached) | 3/5 (standard Docker layers) |
| Security | 3/5 (no rebase, standard Docker) |
| Maintenance burden | 2/5 (need to manage Cog integration, strip server) |

### 2.3 Source-to-Image (S2I)

**How it works**: Red Hat tool that injects source code into a "builder image"
with pre-installed middleware. No Dockerfile needed.

```bash
s2i build https://github.com/org/actor \
  centos/python-38-centos7 \
  my-actor-image
```

**Custom builder image**: Asya could provide `asya/s2i-python:3.11` with
runtime pre-installed. User provides handler code only.

**Status (2026)**: Still maintained (RHEL 9 lifecycle), but declining community
outside OpenShift. Shipwright supports S2I as a build strategy.

**Verdict**: Viable but declining. Buildpacks are the spiritual successor.
Not recommended as primary strategy.

| Dimension | Rating |
|---|---|
| DS-friendliness | 3/5 |
| GPU/CUDA | 2/5 (manual base image) |
| Community | 2/5 (declining outside OpenShift) |

### 2.4 apko + melange (Chainguard)

**How it works**: Declarative YAML -> single-layer OCI image. Based on Wolfi
OS (glibc, minimal, CVE-free).

```yaml
# apko.yaml
contents:
  repositories:
    - https://packages.wolfi.dev/os
  packages:
    - python-3.11
    - py3.11-pip
    - ffmpeg
```

**Pip packages**: NOT directly supported. Must use melange to build APK
packages, or use multi-stage approach.

**Wolfi advantages**: glibc (not musl like Alpine), 60-70% smaller than
Ubuntu, pre-compiled Python wheels work natively.

**Verdict**: Excellent for secure base images. Not practical for DS-facing
builds (no pip support). Best as base image for other strategies.

| Dimension | Rating |
|---|---|
| DS-friendliness | 1/5 (too complex) |
| Image size | 5/5 (smallest possible) |
| Security | 5/5 (CVE-free, minimal) |
| Python ecosystem | 2/5 (no direct pip) |

### 2.5 Programmatic Dockerfile Generation

**How it works**: Framework generates a Dockerfile internally from build
config. User never sees it. The generated Dockerfile is an intermediate
artifact.

**Is this "cheating"?**: No. Heroku, Railway (14M+ builds), Cog all do this
internally. Proven pattern.

**Asya implementation**: `asya build render` translates `build:` config into
a Dockerfile from `asya-runtime` base images:

```dockerfile
# Auto-generated from actor.yaml build: config
FROM asya-runtime:3.11-gpu
RUN apt-get update && apt-get install -y ffmpeg libsndfile1
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt
COPY src/ /app/
ENV ASYA_HANDLER=my_actors.text_analyzer.analyze
```

**Verdict**: Most practical first implementation. Framework-generated
Dockerfiles are a proven pattern. Can serve as fallback for all cases.

| Dimension | Rating |
|---|---|
| DS-friendliness | 4/5 (user never sees Dockerfile) |
| GPU/CUDA | 4/5 (base image selection) |
| Flexibility | 5/5 (full Docker capabilities) |
| Implementation effort | 5/5 (simplest to build) |
| Build speed | 4/5 (BuildKit cache mounts) |

### 2.6 Patterns from Other Frameworks

**Flyte ImageSpec** -- define image in Python code:
```python
from flytekit import task, ImageSpec

image = ImageSpec(
    python_version="3.11",
    packages=["torch", "transformers"],
    apt_packages=["git"],
    cuda="12.1",
)

@task(container_image=image)
def train_model(data):
    return model
```
Computes deterministic hash, checks registry, builds only if missing.
Gold standard for DS experience.

**Modal Image API** -- Python-native, serverless:
```python
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install("torch", "transformers")
)
```
Aspirational UX but proprietary cloud (vendor lock-in).

**KServe**: Pre-built model servers for common frameworks (sklearn, pytorch,
xgboost). User provides model in S3, zero Docker knowledge. Storage
initializer downloads at startup.

**Ray Serve**: Code reference + runtime_env. Downloads code from Git at
startup, installs deps. Zero Docker but unreliable for production (runtime
pip install).

---

## 3. Comparison Matrix

| Strategy | DS UX | GPU | Sys Pkgs | Zero Config? | Rebase | Impl Effort | Lock-in |
|---|---|---|---|---|---|---|---|
| **Buildpacks** | 4/5 | 2/5 | 2/5 | Yes | Yes | Medium | Low (CNCF) |
| **Cog** | 5/5 | 5/5 | 5/5 | No (cog.yaml) | No | Medium | Medium |
| **S2I** | 3/5 | 2/5 | 3/5 | No | No | Low | High (RH) |
| **apko/Wolfi** | 1/5 | 2/5 | 4/5 | No | No | High | Low |
| **Generated Dockerfile** | 4/5 | 4/5 | 5/5 | No | No | Low | None |
| **Flyte ImageSpec** | 5/5 | 4/5 | 4/5 | In code | No | Medium | Medium |

---

## 4. Architecture: Pluggable Build Strategies

The `build:` config in actor.yaml is the **common interface**. Strategies are
pluggable backends that consume this interface:

```
actor.yaml build: config
        |
        +-- strategy: buildpack  -->  project.toml + pack build
        +-- strategy: cog        -->  cog.yaml + cog build
        +-- strategy: dockerfile -->  Dockerfile (generated) + docker build
        +-- strategy: custom     -->  user-provided Dockerfile
```

**Strategy selection**:
- Explicit: `build: { strategy: cog }`
- Context-level default in asya.yaml
- Auto-detected: `gpu: true` -> suggest Cog; standard -> suggest buildpacks

**No rendering needed for some strategies**: Buildpacks auto-detect from
requirements.txt. Cog needs cog.yaml. Dockerfile strategy generates a file.
The "render" step is strategy-specific, not universal.

---

## 5. Actor Categories and Recommended Strategies

| Actor Type | Characteristics | Recommended |
|---|---|---|
| **Router actors** | Generated code, no deps | No build (asya-runtime + ConfigMap) |
| **Simple Python** | Pip deps only | Buildpacks (zero config) |
| **ML/GPU actors** | PyTorch/TF, CUDA | Cog (auto CUDA) |
| **Complex actors** | Custom system deps | Generated Dockerfile |
| **Platform-managed** | Full control | User-provided Dockerfile |

---

## 6. Golden Paths

Three golden paths (ordered by DS-friendliness), plus escape hatch:

### Path 1: Zero Config (Buildpacks)
For actors with only Python dependencies:
```yaml
name: text-analyzer
handler: my_actors.text_analyzer.analyze
# no build: section needed -- auto-detected from requirements.txt
```

### Path 2: ML-Optimized (Cog)
For actors needing GPU/CUDA:
```yaml
name: image-classifier
handler: my_actors.classifier.predict
build:
  gpu: true
  requirements: requirements.txt
  packages: [ffmpeg]
```

### Path 3: Explicit (Generated Dockerfile)
For actors needing fine-grained control:
```yaml
name: audio-processor
handler: my_actors.audio.process
build:
  base: python:3.11-slim
  python: "3.11"
  requirements: requirements.txt
  packages: [ffmpeg, libsndfile1-dev]
```

### Escape Hatch: BYO Dockerfile
```yaml
name: custom-actor
handler: my_actors.custom.process
build:
  dockerfile: Dockerfile
```

---

## 7. Implementation Phases

**Phase 1** (MVP): Generated Dockerfile strategy. Simplest, covers all cases.
**Phase 2**: Buildpacks for zero-config Python actors.
**Phase 3**: Cog for GPU/ML actors.
**Phase 4**: Custom Asya buildpack (if demand warrants).

---

## 8. Open Questions

1. **Should Asya provide base images?** `asya-runtime:3.11`, `asya-runtime:3.11-gpu`
   would simplify all strategies but is a maintenance commitment.

2. **Wolfi as base?** 60-70% smaller, glibc, CVE-free. Worth it?

3. **Cog server stripping**: Is `cog debug` + modification reliable long-term?

4. **Where does build: config live for flow-owned actors?** In the flow file?
   In compiled manifest? In actor.yaml under deploy/?

---

## Sources

- [Cloud Native Buildpacks](https://buildpacks.io/)
- [Paketo Python](https://paketo.io/docs/howto/python/)
- [Cog by Replicate](https://github.com/replicate/cog) (Apache 2.0)
- [Cog YAML Spec](https://cog.run/yaml/)
- [S2I](https://github.com/source-to-image/s2i)
- [apko](https://github.com/chainguard-dev/apko)
- [Wolfi OS](https://github.com/wolfi-dev)
- [Flyte ImageSpec](https://docs.flyte.org/en/latest/user_guide/customizing_dependencies/imagespec.html)
- [Modal Image API](https://modal.com/docs/guide/custom-container)
- [Buildpacks Rebase](https://www.cncf.io/blog/2024/01/11/reduce-reuse-rebase-sustainable-containers-with-buildpacks/)
