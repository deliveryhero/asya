# Research: Avoiding Dockerfiles for Asya Actors

**Date**: 2026-03-05
**Status**: Informational
**Context**: How to eliminate Dockerfiles for some actors while keeping them
optional. Must be modular, composable, non-opinionated.

---

For USER: links:
- https://docs.google.com/document/d/1mFATQa3HSGBVNdXyYmXi8VrqJ_n_y9ADGypxn4INPCg/edit?tab=t.0
- cog: https://cog.run/deploy/
- Tilt: https://docs.tilt.dev/
- paketo: https://paketo.io/docs/
- kpack: https://github.com/buildpacks-community/kpack
- buildpacks: https://buildpacks.io/docs/for-app-developers/concepts/platform/

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

### 2.2 Cog (Replicate) -- Analysis and Reusable Parts

**How it works**: ML-specific builder. `cog.yaml` declares environment
(Python, GPU, CUDA, system packages). Under the hood, Cog **generates a
Dockerfile** (`pkg/dockerfile/standard_generator.go`) and runs `docker build`.
It is syntactic sugar over Dockerfile -- the same escape hatch, not an
alternative to it.

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

**What Cog generates**: A standard Dockerfile with:
- Base image priority: (1) Cog base image `r8.im/cog-base:*` (Replicate's
  registry, pre-includes CUDA+Python+PyTorch), (2) `nvidia/cuda:*-devel-*`
  (GPU), (3) `python:*-slim` (CPU fallback)
- `apt-get install` for system packages
- uv (v0.9.26) for pip dependency installation
- Cog SDK + coglet HTTP server (unnecessary for Asya)
- Multi-stage builds for model weight separation
- `CMD ["python", "-m", "cog.server.http"]`

**Cog always uses `devel` CUDA images**: All 69 entries in
`cuda_compatibility.json` are `devel` variants (`nvidia/cuda:*-cudnn*-devel-*`).
No `runtime` variants. Every GPU image includes the full CUDA compiler toolkit
(headers, nvcc, libraries), inflating image size by gigabytes even for
inference-only workloads.

**Coglet**: Cog bundles a Rust/Axum HTTP server compiled as a Python extension
via PyO3. It manages worker subprocesses, concurrency slots, and IPC over Unix
sockets. Endpoints: `POST /predictions`, health checks, OpenAPI schema, cancel,
shutdown. This is fundamentally incompatible with Asya's sidecar architecture --
two competing server layers managing the same process.

**Hard Docker dependency**: `cog build` creates a Docker client at startup and
fails without a Docker daemon. No way to produce images without Docker. No
daemonless builder support (Kaniko, Buildah).

**CUDA auto-detection -- the killer feature worth reusing**: Cog maintains
compatibility matrices as JSON files (Apache 2.0 licensed):
- `pkg/config/torch_compatibility.json` -- maps PyTorch version → CUDA
  version + torchvision + torchaudio + supported Python versions + pip
  index URL. Covers PyTorch 1.2 through 2.10.
- `pkg/config/tf_compatibility.json` -- maps TensorFlow version → CUDA
  version + cuDNN version + supported Python versions.

```json
// torch_compatibility.json entry example:
{
  "Torch": "2.10.0+cu129",
  "Torchvision": "0.25.0",
  "Torchaudio": "2.10.0",
  "ExtraIndexURL": "https://download.pytorch.org/whl/cu129/",
  "CUDA": "12.9",
  "Pythons": ["3.10", "3.11", "3.12", "3.13", "3.14"]
}
```

This compatibility data is the most valuable part of Cog. It encodes years
of painful "which CUDA works with which PyTorch?" discovery. Asya can reuse
these JSON files (Apache 2.0) to resolve CUDA/cuDNN versions from a user's
requirements.txt -- without depending on Cog itself.

**Why NOT to adopt Cog as a build strategy** (see ADR `adr.no-cog.md`):
1. **It generates Dockerfiles** -- same escape hatch, no lock file possible
2. **Conflicting server** -- coglet is a full Rust HTTP server with subprocess
   isolation and concurrency management. Asya's sidecar already handles this.
   Two competing server layers in one pod.
3. **Hard Docker dependency** -- cannot use Kaniko, Buildah, or Shipwright
   strategies. Breaks daemonless CI pipelines.
4. **Devel-only CUDA images** -- gigabytes of unnecessary compiler tooling
   in every GPU inference image
5. **No reproducibility** -- no lock file, no SBOM, no rebase
6. **Registry coupling** -- default base images on `r8.im` (Replicate's
   registry). Configurable but tightly coupled by default.

**What to reuse from Cog**:
- `torch_compatibility.json` -- CUDA resolution for PyTorch
- `tf_compatibility.json` -- CUDA resolution for TensorFlow
- The resolution logic: parse requirements.txt → find torch/tf version →
  look up compatible CUDA → select base image or Wolfi CUDA packages

**Verdict**: Cog as a tool is a Dockerfile generator -- not a distinct
build strategy. But its compatibility matrices are gold. Asya should reuse
the JSON data for CUDA auto-detection within apko-based or Dockerfile-based
flows, not depend on Cog as a builder.

| Dimension | Rating |
|---|---|
| DS-friendliness | 5/5 (simplest config for ML) |
| GPU/CUDA | 5/5 (auto-detection matrices) |
| System packages | 5/5 (native apt support) |
| Build speed (cached) | 3/5 (standard Docker layers) |
| Security | 3/5 (no rebase, standard Docker) |
| Lockable | 1/5 (generates Dockerfile -- no lock file possible) |

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

**apko YAML spec** (complete top-level fields):
```yaml
# apko.yaml -- full spec reference
contents:
  repositories:                       # APK package repositories
    - https://packages.wolfi.dev/os
    - @local /path/to/local/repo      # local repo with label
  build_repositories: []              # repos for build phase only
  runtime_repositories: []            # repos for runtime metadata only
  keyring:                            # PGP keys for package verification
    - https://packages.wolfi.dev/os/wolfi-signing.rsa.pub
  packages:                           # APK packages to install
    - python-3.12
    - py3.12-pip
    - ffmpeg
  baseimage:                          # EXPERIMENTAL -- see below
    image: ./path/to/oci-layout       # local OCI layout directory ONLY
    apkindex: ./path/to/apkindexes    # APK index of base packages

entrypoint:
  command: /usr/bin/python3           # OCI entrypoint
  # OR shell-fragment: "exec python3 $@"
  # OR type: service-bundle + services: {name: cmd}
cmd: /bin/sh -l                       # OCI CMD
work-dir: /app                        # WORKDIR
stop-signal: SIGTERM

accounts:
  groups:
    - groupname: app
      gid: 1000
  users:
    - username: app
      uid: 1000
  run-as: app                         # non-root by default

environment:
  PATH: /usr/local/bin:/usr/bin:/bin
  PYTHONPATH: /opt/app

paths:                                # filesystem operations
  - path: /opt/app
    type: directory
    uid: 1000
    permissions: 0o755
  - path: /tmp
    type: permissions
    permissions: 0o1777

annotations:                          # OCI annotations
  org.opencontainers.image.source: https://github.com/...

archs:                                # multi-arch support
  - amd64
  - arm64

include: base-config.yaml            # merge from base config (local or remote)

layering:                             # layer splitting (incompatible with baseimage)
  strategy: origin
  budget: 15
```

**Lock file format** (from `apko lock` -- real example):
```json
{
  "version": "v1",
  "config": {
    "name": "./apko.yaml",
    "checksum": "sha256-W5wS8HLGz9qI5ILWqVoV7YS+m3qz2hppgI0FxC1dtMU="
  },
  "contents": {
    "keyring": [],
    "build_repositories": [],
    "runtime_repositories": [],
    "repositories": [
      {
        "name": "dl-cdn.alpinelinux.org/alpine/v3.21/main/x86_64",
        "url": "https://dl-cdn.alpinelinux.org/.../APKINDEX.tar.gz",
        "architecture": "x86_64"
      }
    ],
    "packages": [
      {
        "name": "musl",
        "url": "https://dl-cdn.alpinelinux.org/.../musl-1.2.5-r9.apk",
        "version": "1.2.5-r9",
        "architecture": "x86_64",
        "signature": {
          "range": "bytes=0-666",
          "checksum": "sha1-sM/dPliGLSt7MPSP5juy3qQ9M1M="
        },
        "control": {
          "range": "bytes=667-1188",
          "checksum": "sha1-/L7yOJHsBPgaKLmNu7Uh5YIY0tg="
        },
        "data": {
          "range": "bytes=1189-411322",
          "checksum": "sha256-P47qWTGBhwdIAMt2VqsTEr5Tv/JC4rJVfjbDVuCkroo="
        },
        "checksum": "Q1/L7yOJHsBPgaKLmNu7Uh5YIY0tg="
      }
    ]
  }
}
```

Each package has **three-level checksums** (signature, control, data) with
byte ranges for partial verification. The `config.checksum` is a SHA256 deep
hash of all config YAML files (including `include:` targets). Any config
change invalidates the lock.

**Lock workflow**: `apko lock apko.yaml` → resolves all packages for all
architectures → writes `apko.lock.json`. `apko build --lockfile apko.lock.json`
→ skips resolution, validates checksums → bit-for-bit reproducible image.
No partial updates -- `apko lock` always fully re-resolves.

**Can apko use non-Wolfi base images?** The `baseimage` field is
**experimental** and has severe constraints:
- Image must be a **local OCI layout directory** (pre-downloaded via
  `crane pull ... --format=oci`), NOT a remote registry reference
- Requires an **APK index** of the base image's installed packages -- the
  base must be APK-based (Alpine/Wolfi) for the resolver to work
- When using `baseimage`, only `contents`, `archs`, and `include` are
  allowed -- no `accounts`, `environment`, `entrypoint`, `paths`
- Incompatible with `layering` feature
- Regression in apko 0.26.0 broke this feature entirely (fixed in PR #1633)
- **Cannot use nvidia/cuda or pytorch base images** -- they are Debian-based
  (dpkg/apt), not APK-based. The resolver cannot understand what's installed.

**GPU/CUDA in open-source Wolfi**: **NOT AVAILABLE.** Searched the
`wolfi-dev/os` repository (3800+ package YAMLs) -- zero results for `cuda`,
no `cuda-toolkit.yaml`, no `cudnn.yaml`, no `pytorch.yaml`, no
`tensorflow.yaml`. Only `nvidia-container-toolkit` and `libnvidia-container`
(runtime plumbing, not the CUDA SDK). CUDA/PyTorch packages exist only in
**Chainguard's commercial repositories**.

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

`melange convert python <pkg>` can auto-generate YAML from PyPI metadata but
is experimental and often needs manual editing.

For a project with 20 pip dependencies, you'd need 20 melange YAML files (or
rely on Wolfi's existing catalog of 673+ `py3-*` packages: numpy, scipy,
scikit-learn, pandas, transformers -- but NOT torch, NOT tensorflow core).

**Where melange runs**: Client-side tool with pluggable runners:
- Docker (default, needs `--privileged`)
- Bubblewrap (unprivileged Linux sandbox, good for CI)
- Kubernetes (via `--runner kubernetes` -- creates build pods in cluster)
- Lima (macOS local dev)

Melange is NOT a cluster service -- it's a CLI tool that can optionally
delegate compute to a K8s cluster. Output is APK packages consumed by apko.

**apko cannot COPY files**: The `paths` field creates directories, empty
files, links, and sets permissions -- but cannot copy file content (no
`COPY handler.py /app/` equivalent). Handler code must be packaged as an
APK via melange, or added via a Dockerfile layer on top.

**Practical alternative**: Use Chainguard's pre-built Python base image
(`cgr.dev/chainguard/python`) with standard multi-stage Docker builds and pip.
This gives Wolfi's security benefits without the per-package melange overhead.

**Wolfi advantages over Distroless**:
- glibc (not musl like Alpine) -- pre-compiled Python wheels work natively
- 60-70% smaller than Ubuntu, 6% the size of standard `python:latest`
- Fine-grained package selection (not tied to Debian versions)
- Built-in SBOMs, nightly rebuilds, zero-known-CVE target
- Chainguard Images (`cgr.dev/chainguard/python`) as pre-built alternative

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

| Strategy | DS UX | GPU | Sys Pkgs | Lock File | Rebase | Impl Effort | Lock-in |
|---|---|---|---|---|---|---|---|
| **apko/Wolfi** | 3/5 | 3/5* | 4/5 | **Yes** | No | High | Low |
| **Buildpacks** | 4/5 | 2/5 | 2/5 | Partial | Yes | Medium | Low (CNCF) |
| **Cog** | 5/5 | 5/5 | 5/5 | No (Dockerfile) | No | Medium | Medium |
| **S2I** | 3/5 | 2/5 | 3/5 | No | No | Low | High (RH) |
| **User Dockerfile** | 5/5 | 5/5 | 5/5 | No | No | None | None |
| **Flyte ImageSpec** | 5/5 | 4/5 | 4/5 | No (hash only) | No | Medium | Medium |

*apko GPU: requires Chainguard commercial for CUDA packages, or custom
melange builds. Open-source Wolfi does NOT have CUDA/PyTorch.

---

## 4. Architecture: Two Build Paths

Build inputs (Python version, deps, system packages, GPU) are the **common
interface**. Two fundamentally different paths:

```
build inputs (format TBD)
        |
        +-- strategy: apko       -->  apko.yaml + lock file (lockable, reproducible)
        +-- strategy: buildpack  -->  project.toml + pack build (lockable via buildpack mechanisms)
        +-- strategy: dockerfile -->  user-provided Dockerfile (escape hatch, no lock)
```

**Key distinction**:
- **apko path**: Declarative, lockable (`actor-image.lock`), reproducible.
  Uses Cog's compatibility matrices for CUDA resolution. The path Asya
  optimizes for.
- **Buildpacks path**: Auto-detected, partially lockable (layer caching).
  Good for simple Python actors without GPU.
- **Dockerfile path**: Escape hatch. Full control, no constraints, no lock
  file. Traditional local build + GitOps flow. Asya provides no special
  tooling beyond `docker build`.

**Strategy selection**: Always explicit via `strategy:` field. No magic
auto-detection of which builder to use.

**CUDA resolution** (shared across strategies): Asya reuses Cog's
compatibility matrices (`torch_compatibility.json`, `tf_compatibility.json`)
to resolve PyTorch/TF version → CUDA version. This data feeds into:
- apko: selects CUDA APK packages from Wolfi/Chainguard
- Dockerfile: suggests base image (informational only)

---

## 5. Actor Categories and Recommended Strategies

| Actor Type | Characteristics | Recommended |
|---|---|---|
| **Router actors** | Generated code, no deps | No build (asya-runtime + ConfigMap) |
| **Simple Python** | Pip deps only | Buildpacks (zero config) or apko |
| **ML/GPU actors** | PyTorch/TF, CUDA | apko (lockable, CUDA via compatibility matrices) |
| **Complex actors** | Custom system deps, full control | Dockerfile (escape hatch) |

---

## 6. Golden Paths

Three golden paths. Strategy is always explicit -- no auto-detection:

### Path 1: apko (lockable, reproducible -- primary path)
```yaml
build:
  strategy: apko
  python: "3.12"
  requirements: requirements.txt
  packages: [ffmpeg, numpy]       # Wolfi APK packages
  gpu: true                       # triggers CUDA resolution from compatibility matrices
```

Produces `actor-image.lock` (see `research-seamless-build.md`). Lockable,
reproducible, auditable. Asya resolves CUDA version from PyTorch/TF version
in requirements.txt using Cog's compatibility matrices.

### Path 2: Buildpacks (standard Python, no GPU)
```yaml
build:
  strategy: buildpack
  requirements: requirements.txt   # or pyproject: pyproject.toml, etc.
```

### Path 3: Dockerfile (escape hatch, no lock)
```yaml
build:
  strategy: dockerfile
  dockerfile: Dockerfile
```

No `actor-image.lock` for Dockerfile path. Traditional local build + GitOps
flow. Asya provides no special tooling beyond wrapping `docker build`.

Note: config format and file placement are TBD (see section 1). The examples
above show the **build inputs** each strategy needs, not a final file schema.

---

## 7. Implementation Phases

**Phase 1** (MVP): BYO Dockerfile (escape hatch) + Buildpacks for zero-config
Python actors.
**Phase 2**: apko for lockable, reproducible builds (CPU-only initially).
Port Cog's compatibility matrices for CUDA resolution.
**Phase 3**: apko + CUDA (requires Chainguard commercial or custom melange
builds for CUDA/PyTorch packages).

---

## 8. Open Questions

1. ~~**Should Asya provide base images?**~~ Decision: NO. Asya does not provide
   base images. Users bring their own or rely on strategy defaults (buildpack
   builder images, Cog base images, etc.).

2. **Wolfi as base?** 60-70% smaller, glibc, CVE-free. Worth it?

3. ~~**Cog server stripping**~~: Resolved. No stripping needed. asya-injector
   overwrites the container command, so Cog's bundled server CMD is ignored.
   Extra binary is dead weight in the image (no runtime cost). If Cog proves
   useful, request `--no-server` build mode upstream.

4. ~~**Where do build inputs live?**~~ Partial decision: dependencies are NOT
   auto-detected. The build config explicitly references dependency files:
   ```yaml
   build:
     strategy: buildpack
     requirements: requirements.txt        # or:
     pyproject: pyproject.toml             # or:
     uv_lock: uv.lock                     # etc.
   ```
   Explicit better than implicit -- the user declares which file format they
   use. Remaining open: where the build config itself lives (standalone file,
   central manifest, flow-level annotation).

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
