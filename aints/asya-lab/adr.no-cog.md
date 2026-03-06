# ADR: Do not adopt Cog as a build strategy

**Status**: Accepted
**Date**: 2026-03-06
**Context**: Build strategy research for Asya actors (research-no-dockerfile.md)

## Decision

Asya will NOT use Cog (Replicate) as a build strategy. Cog's CUDA/framework
compatibility matrices will be extracted and reused standalone.

## Context

Cog (`github.com/replicate/cog`, Apache 2.0) is an ML-specific container
builder. It provides an excellent DS UX: declare Python version, GPU, and
dependencies in `cog.yaml`, and Cog handles CUDA version selection
automatically. Initial research rated it 5/5 for DS-friendliness and GPU
support. However, deeper analysis revealed fundamental architectural
conflicts with Asya.

## Why Not

### 1. Cog is a Dockerfile generator, not an alternative

Cog's `pkg/dockerfile/standard_generator.go` generates a standard Dockerfile
and runs `docker build`. It is syntactic sugar over Dockerfile -- the same
escape hatch path, not a distinct build strategy. Adopting Cog would mean
adopting a dependency that produces the exact artifact we already support
(Dockerfile + docker build), with no new capability beyond the compatibility
matrices.

### 2. Conflicting server architecture

Cog bundles **coglet** -- a Rust/Axum HTTP server compiled as a Python
extension via PyO3. Coglet manages:
- Worker subprocesses with IPC over Unix sockets
- Concurrency slots (PermitPool)
- REST API: `POST /predictions`, health checks, cancel, shutdown
- OpenAPI schema generation

Asya's sidecar architecture already handles all network I/O. The sidecar
communicates with the runtime over a Unix socket (`POST /invoke`). Running
coglet inside an Asya actor pod would create two competing server layers
with redundant process management, conflicting CMD directives, and
overlapping concerns.

Asya's injector webhook overwrites the container CMD to run
`asya_runtime.py`. Coglet's CMD (`python -m cog.server.http`) is silently
ignored. The coglet binary remains as dead weight.

### 3. Hard Docker dependency

`cog build` creates a Docker client at startup and fails without a Docker
daemon. This prevents:
- Integration with daemonless CI builders (Kaniko, Buildah)
- On-cluster builds via Shipwright (which uses Kaniko/Buildah strategies)
- Lightweight developer environments without Docker

### 4. Devel-only CUDA images

All 69 entries in Cog's `cuda_compatibility.json` are `devel` variants
(`nvidia/cuda:*-cudnn*-devel-ubuntu*`). No `runtime` variants are offered.
Every GPU image includes the full CUDA compiler toolkit (nvcc, headers,
static libraries) -- gigabytes of unnecessary tooling for inference-only
workloads.

### 5. No reproducibility guarantees

- No lock file
- No SBOM generation
- No rebase capability
- Standard Docker layer caching only
- No mechanism for bit-for-bit reproducible builds

This conflicts with Asya's `actor-image.lock` design goal.

### 6. Default registry coupling

Default base images are hosted on `r8.im` (Replicate's registry) with tag
format `cuda{major.minor}-python{major.minor}-torch{version}`. While
configurable via `COG_REGISTRY_HOST`, the naming scheme and pre-baked
package selection are tightly coupled to Replicate's infrastructure.

## What We Reuse

Cog's compatibility matrices (Apache 2.0) are the most valuable extractable
asset:

- `pkg/config/torch_compatibility.json` (138 entries): maps PyTorch version
  -> CUDA version, torchvision, torchaudio, Python versions, pip index URL.
  Covers PyTorch 1.2.0 through 2.10.0.
- `pkg/config/tf_compatibility.json` (17 entries): maps TensorFlow version
  -> CUDA version, cuDNN version, Python versions.
- `pkg/config/cuda_compatibility.json` (69 entries): maps CUDA + cuDNN
  versions to nvidia/cuda base image tags.

These JSON files encode years of "which CUDA works with which PyTorch?"
discovery. Asya will extract and maintain a copy of this data to power
CUDA auto-resolution in the apko-based and Dockerfile-based build paths --
without taking a runtime dependency on Cog.

## Alternatives Considered

### Use Cog, strip the server

Accept coglet as dead weight, use Cog for CUDA auto-detection and Dockerfile
generation. Rejected because: (a) we already support Dockerfile as escape
hatch, (b) no lock file possible, (c) hard Docker dependency blocks
Shipwright integration.

### Use Cog for prototyping, apko for production

Allow DS to use `cog build` for fast experimentation, then transition to
apko for production builds. Rejected because: (a) two different build paths
creates confusion, (b) Cog's Dockerfile output is not convertible to apko
YAML, (c) the compatibility matrices can power both paths without Cog.

## Consequences

- Asya must maintain its own copy of the compatibility matrices and update
  them when new PyTorch/TensorFlow/CUDA versions are released
- DS using Cog externally can still use Dockerfile escape hatch -- Cog
  produces a Dockerfile, which Asya supports
- CUDA resolution logic will be implemented in the `asya` CLI, reading
  from the extracted JSON files
