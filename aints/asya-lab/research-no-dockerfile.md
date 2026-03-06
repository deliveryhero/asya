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

**Build intent** (format TBD): Regardless of where or how it's expressed --
standalone file, section in a central manifest, Python code, or flow-level
annotation -- the build system needs certain inputs to produce a container image:

- Python version
- Python dependencies (requirements file, pyproject.toml, uv.lock, etc.)
- System packages (apt/apk)
- GPU/CUDA requirements
- Base image preference (optional)

How these inputs are captured (file format, placement, syntax) is an open
design question. The research below evaluates tools by how well they can
consume these inputs regardless of how they're expressed.

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

**Mapping build inputs to Buildpacks**:
- Python version -> `BP_CPYTHON_VERSION` env var
- Dependencies -> auto-detected from requirements.txt/pyproject.toml
- System packages -> requires custom run image (limitation)
- GPU/CUDA -> requires custom run image (limitation)

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

**Mapping build inputs to Cog**:
- Python version -> `python_version:`
- Dependencies -> `python_requirements:`
- System packages -> `system_packages:`
- GPU -> `gpu: true` (auto-detects CUDA from torch/tf version)

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
| Maintenance burden | 3/5 (need to manage Cog integration, strip server. But cog is client-level only, no server installations) |

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
| DS-friendliness | 2/5 |
| GPU/CUDA | 2/5 (manual base image) |
| Community | 2/5 (declining outside OpenShift) |

### 2.4 Minimal Base Images: Distroless + Wolfi/apko

Two related approaches to minimal, secure container images. Same lineage --
Google Distroless was created by Dan Lorenc and Matt Moore; they later founded
Chainguard and created Wolfi as the evolution.

#### Google Distroless

**How it works**: Pre-built minimal runtime images based on Debian. No shell,
no package manager, no debugging tools. Used as `FROM` in multi-stage builds.

```dockerfile
# Multi-stage: build deps in full image, copy to distroless
FROM python:3.11-slim-bookworm AS builder
RUN python3 -m venv /venv
COPY requirements.txt .
RUN /venv/bin/pip install -r requirements.txt

FROM gcr.io/distroless/python3-debian12
COPY --from=builder /venv /venv
COPY app.py .
ENV PYTHONPATH=/venv/lib/python3.11/site-packages
CMD ["/venv/bin/python", "app.py"]
```

**Python versions**: Tied to Debian releases (Python 3.11.2 in Debian 12).
Cannot select Python version independently.

**Image size**: ~50 MB for Python3 image. With virtualenv: ~130 MB (still
smaller than python:3.11-slim at 130 MB, and much smaller than full python).

**GPU/CUDA**: NOT available. No way to install CUDA libraries without package
manager. Major limitation for ML.

**No shell** (by design): Distroless images have no shell, no package manager,
no debugging tools. This is the security benefit -- minimal attack surface.
`:debug` tags include BusyBox shell but are not for production. For debugging
production pods on K8s, use ephemeral debug containers:
```bash
kubectl debug -it <pod-name> --image=busybox --target=<container-name>
```
This attaches a debug container to the pod's process namespace without
modifying the distroless image.

**Maintenance**: Actively maintained (last update Feb 2026). Automated CI/CD
tracks Debian security updates.

#### Wolfi/apko + melange (Chainguard)

**How it works**: Declarative YAML -> minimal OCI image. Based on Wolfi
OS (glibc, built from source, CVE-free). More flexible than Distroless --
you build custom images rather than using pre-built ones.

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

**Pip packages and melange**: apko itself cannot install pip packages. The
intended path is melange -- Chainguard's APK package builder. However, melange
requires **one YAML file per Python package** (not per project). It does NOT
consume `requirements.txt` or `pyproject.toml` directly:

```yaml
# melange.yaml for a single pip package (py3-pluggy example)
package:
  name: py3-pluggy
  version: 1.5.0
pipeline:
  - uses: git-checkout
    with:
      repository: https://github.com/pytest-dev/pluggy
      tag: ${{package.version}}
  - uses: py/pip-build-install
```

For a project with 20 pip dependencies, you'd need 20 melange YAML files (or
rely on Wolfi's existing catalog). Wolfi has numpy, scipy, and some scientific
packages, but many ML libraries (torch, transformers, pandas) are NOT yet
packaged. No integration with uv or poetry.

**Where melange runs**: Client-side tool with pluggable runners:
- Docker (default, needs `--privileged`)
- Bubblewrap (unprivileged Linux sandbox, good for CI)
- Kubernetes (via `--runner kubernetes` -- creates build pods in cluster)
- Lima (macOS local dev)

Melange is NOT a cluster service -- it's a CLI tool that can optionally
delegate compute to a K8s cluster. Output is APK packages consumed by apko.

**Practical alternative**: Use Chainguard's pre-built Python base image
(`cgr.dev/chainguard/python`) with standard multi-stage Docker builds and pip.
This gives Wolfi's security benefits without the per-package melange overhead.

**Wolfi advantages over Distroless**:
- glibc (not musl like Alpine) -- pre-compiled Python wheels work natively
- 60-70% smaller than Ubuntu, 6% the size of standard `python:latest`
- Fine-grained package selection (not tied to Debian versions)
- Built-in SBOMs, nightly rebuilds, zero-known-CVE target
- Chainguard Images (`cgr.dev/chainguard/python`) as pre-built alternative

**GPU/CUDA**: NOT available (same limitation as Distroless).

#### Comparison

| Aspect | Google Distroless | Wolfi/apko |
|---|---|---|
| Base OS | Debian | Wolfi (custom, glibc) |
| Python versions | Tied to Debian | Any (fine-grained) |
| Customization | Multi-stage only | YAML declarative |
| Build tool | Bazel (complex) | apko (simpler) |
| Pre-built images | gcr.io/distroless/* | cgr.dev/chainguard/* |
| Size | ~50 MB (python3) | Smaller (custom) |
| SBOMs | No | Built-in |

**Verdict (both)**: Excellent for secure base images. Neither is practical for
DS-facing builds (no pip, no shell, no GPU). Best role: **base image layer**
for other strategies (generated Dockerfile, Cog, or Asya-provided base images).

| Dimension | Rating |
|---|---|
| DS-friendliness | 1/5 (too complex for DS, not intended for them) |
| Image size | 5/5 (smallest possible) |
| Security | 5/5 (CVE-free, minimal attack surface) |
| Python ecosystem | 2/5 (no direct pip, multi-stage required) |
| GPU/CUDA | 1/5 (not supported) |

### 2.5 Patterns from Other Frameworks

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
| **User Dockerfile** | 5/5 | 5/5 | 5/5 | No | No | None | None |
| **Flyte ImageSpec** | 5/5 | 4/5 | 4/5 | In code | No | Medium | Medium |

---

## 4. Architecture: Pluggable Build Strategies

Build inputs (Python version, deps, system packages, GPU) are the **common
interface**. Strategies are pluggable backends that consume these inputs:

```
build inputs (format TBD)
        |
        +-- strategy: buildpack  -->  project.toml + pack build
        +-- strategy: cog        -->  cog.yaml + cog build
        +-- strategy: dockerfile -->  user-provided Dockerfile + docker build
```

**Strategy selection**: Always explicit via `strategy:` field. No magic
auto-detection of which builder to use. Can be set per-actor or as a
context-level default.

**No rendering needed for some strategies**: Buildpacks auto-detect from
requirements.txt. Cog needs cog.yaml. Dockerfile is user-provided.

---

## 5. Actor Categories and Recommended Strategies

| Actor Type | Characteristics | Recommended |
|---|---|---|
| **Router actors** | Generated code, no deps | No build (asya-runtime + ConfigMap) |
| **Simple Python** | Pip deps only | Buildpacks (zero config) |
| **ML/GPU actors** | PyTorch/TF, CUDA | Cog (auto CUDA) |
| **Complex actors** | Custom system deps, full control | User-provided Dockerfile |

---

## 6. Golden Paths

Three golden paths (ordered by DS-friendliness). Strategy is always explicit
-- no magic auto-detection of which builder to use:

### Path 1: Buildpacks (zero config for standard Python)
```yaml
build:
  strategy: buildpack
  # everything else auto-detected from requirements.txt / pyproject.toml
```

### Path 2: Cog (ML/GPU actors)
```yaml
build:
  strategy: cog
  gpu: true
  requirements: requirements.txt
  packages: [ffmpeg]
```

### Path 3: Dockerfile (full control)
```yaml
build:
  strategy: dockerfile
  dockerfile: Dockerfile
```

Note: config format and file placement are TBD (see section 1). The examples
above show the **build inputs** each strategy needs, not a final file schema.

---

## 7. Implementation Phases

**Phase 1** (MVP): Buildpacks for zero-config Python actors + BYO Dockerfile.
**Phase 2**: Cog for GPU/ML actors.
**Phase 3**: Custom Asya buildpack (if demand warrants).

---

## 8. Open Questions

1. ~~**Should Asya provide base images?**~~ Decision: NO. Asya does not provide
   base images. Users bring their own or rely on strategy defaults (buildpack
   builder images, Cog base images, etc.).

2. **Wolfi as base?** 60-70% smaller, glibc, CVE-free. Worth it?

3. **Cog server stripping**: Is `cog debug` + modification reliable long-term?

4. **Where do build inputs live?** Next to handler code? In a central manifest?
   Embedded in flow definitions? Derived from project files (requirements.txt)?
   This affects every strategy's integration point.

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
