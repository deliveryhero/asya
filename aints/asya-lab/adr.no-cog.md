# ADR: Cog as a supported build path for GPU actors

**Status**: Superseded (was: Rejected)
**Date**: 2026-03-06, revised 2026-03-08
**Context**: Build strategy research for Asya actors (research-no-dockerfile.md)

## Decision

Cog is a **supported build path** for GPU/ML actors alongside Dockerfile and
apko. DS writes `cog.yaml`, Asya runs `cog build` as an opaque command via
`command`. Cog's CUDA/framework compatibility matrices are also
extracted for standalone use (`asya resolve cuda`).

## Why the original rejection was revised

The original ADR rejected Cog entirely due to architectural conflicts. Two
design decisions since then changed the calculus:

1. **Opaque build commands**: Asya treats all build commands as a single shell
   string (`command`). Cog is just another command — Asya doesn't need to
   understand cog.yaml, just run `cog build -t ${..image}`. To push the image,
   use `asya k build --push` which appends a registry push.
2. **Lock file deferred to v2**: The reproducibility gap (no lock file) is
   shared by ALL build paths in v1. This is no longer a Cog-specific concern.

## What Cog provides

- **CUDA auto-resolution**: DS declares PyTorch/TensorFlow version in
  `cog.yaml`, Cog resolves the correct CUDA + cuDNN base image automatically.
  This is the single biggest DS pain point for GPU workloads.
- **DS-friendly config**: `cog.yaml` is simpler than writing a CUDA-aware
  Dockerfile from scratch.
- **Working out of the box**: `cog build` produces a runnable Docker image
  with correct GPU dependencies. No manual `nvidia/cuda` base image selection.

## Known trade-offs (accepted)

### 1. Dead coglet server

Cog bundles coglet (Rust/Axum HTTP server compiled as Python extension via
PyO3). Asya's injector overwrites the container CMD to run `asya_runtime.py`,
so coglet is never started — it's dead weight in the image. This adds disk
space but has no runtime impact.

### 2. Devel-only CUDA images

All entries in Cog's `cuda_compatibility.json` are `devel` variants
(`nvidia/cuda:*-cudnn*-devel-ubuntu*`). Images include the full CUDA compiler
toolkit (nvcc, headers, static libraries). For inference-only workloads this
adds gigabytes of unnecessary tooling.

**Mitigation**: Acceptable for DS experimentation on staging. For production,
teams can switch to a custom Dockerfile with `runtime` CUDA variants or apko
(when GPU support lands).

### 3. Hard Docker dependency

`cog build` requires a Docker daemon. This prevents use with daemonless CI
builders (Kaniko, Buildah) and on-cluster builds (Shipwright).

**Mitigation**: Cog works as a local `command` string. Remote/CI builds use
their own pipelines or Shipwright (configured via the `shipwright:` field).

### 4. No reproducibility guarantees

No lock file, no SBOM, standard Docker layer caching only. Same as Dockerfile
path in v1 — both deferred to v2 `build.intent` design.

## Usage in config.yaml

```yaml
build:
  - module: gpu_models
    path: "${var.project_root}/src/gpu-models"
    image: "${var.image_registry}/gpu-models:${arg:tag}"
    command: "cog build -t ${..image}"
```

DS writes `cog.yaml` in the `path:` directory alongside their Python code.
Cog handles CUDA resolution; Asya handles routing the built image to K8s.

## Three build paths (updated)

| Path | CUDA? | Lock file (v1)? | Best for |
|------|-------|-----------------|----------|
| **Cog** | Auto-resolved | No | GPU/ML actors, DS experimentation |
| **Dockerfile** | Manual | No | Full control, existing CI pipelines |
| **apko** (Wolfi) | Not yet | Yes (`actor-image.lock`) | Lockable, reproducible, non-GPU |

## What we still reuse standalone

Cog's compatibility matrices (Apache 2.0) are extracted for `asya resolve cuda`:

- `torch_compatibility.json` (138 entries): PyTorch → CUDA + pip index
- `tf_compatibility.json` (17 entries): TensorFlow → CUDA + cuDNN
- `cuda_compatibility.json` (69 entries): CUDA + cuDNN → base image tag

These power CUDA resolution for teams writing Dockerfiles manually — they
don't need Cog installed to get the right CUDA version.

## Consequences

- Cog is documented as the **recommended path for GPU actors** during
  DS experimentation
- DS can `cog build` locally, Asya deploys the image to K8s
- Coglet dead weight is accepted (no runtime impact, disk only)
- For production GPU images, teams may transition to optimized Dockerfiles
  with `runtime` CUDA variants — this is a `command:` string change, no
  schema change
- `asya init --strategy cog` scaffolds the right `cog.yaml` + `command:`
  strings
