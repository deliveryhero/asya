---
title: Explore cloud-native image building for DS experimentation workflow
status: open
priority: 2 # medium
type: task
---

## Problem Statement

Data scientists experimenting with actors and flows face a significant gap between:

1. **Experimentation Phase** (imperative, fast)
   - Rapid iteration on model versions
   - Quick image builds from local code
   - Image re-use across experiments
   - No CI overhead during exploration

2. **Production Phase** (declarative, reproducible)
   - Optimized Dockerfiles with multi-stage builds
   - Proper CI pipelines building from git commits
   - Security scanning and vulnerability checks
   - GitOps-managed deployments

This is the same fundamental tension identified in the GitOps dev flow RFC (`.worktrees/rfc0/docs/rfc/thoughts-gitops-dev-flow.md`), but focused specifically on the **image building** aspect rather than deployment.

## What to Explore

### Cloud-Native Build Tools (CNCF First)

1. **Kaniko** - Build container images in Kubernetes without Docker daemon
   - In-cluster builds from Dockerfiles
   - No privileged containers required
   - Git context support

2. **Cloud Native Buildpacks** (CNCF Incubating)
   - Auto-detect language/framework
   - No Dockerfile required for common stacks
   - Reproducible builds
   - Layer caching and rebase capabilities

3. **ko** - For Go applications (fast, no Docker)

4. **Jib** - For Java applications (no Docker daemon needed)

5. **BuildKit** - Next-gen Docker builder
   - Remote caching
   - Parallel build stages
   - OCI-compliant output

### AI-Native Image Considerations

Special attention needed for ML/AI workloads:
- Large model weights (multi-GB)
- CUDA/GPU driver compatibility
- Python dependency resolution (pip/conda)
- Model versioning vs code versioning
- Pre-trained weight injection vs runtime download

### Existing Platforms to Study

- Google Cloud Build
- AWS CodeBuild
- Tekton Pipelines
- Shipwright (CNCF Sandbox)
- Dagger (programmable CI)

## Deliverables

### 1. User Journey Documentation

Define clear paths for:

**Path A: From Scratch (New DS User)**
1. User has Python script + requirements.txt
2. User wants to test as actor in Asya
3. How do they get from code → running actor?
4. What tooling bridges this gap?

**Path B: Established Flow (CI-Enabled)**
1. User has git repo with proper CI
2. Images built from commits
3. GitOps deploys to staging/prod
4. How do they still experiment rapidly?

### 2. Tool Comparison Matrix

| Tool | Dockerfile Required? | GPU Support | Caching | K8s Native | Python/ML Friendly |
|------|---------------------|-------------|---------|------------|-------------------|
| Kaniko | Yes | ? | Limited | Yes | Yes |
| Buildpacks | No | ? | Excellent | Via kpack | Medium |
| ... | ... | ... | ... | ... | ... |

### 3. Prototype Integration

How could this integrate with Asya:
- `asya build` CLI command?
- Automatic image building in `asya run --from-source`?
- Integration with asya-stagedoor?

## Connection to Existing Work

This complements the "Imperative-to-GitOps Promotion Workflow" from the RFC by addressing the **image creation** step that happens before deployment. The RFC's export/sanitizer handles K8s manifests, but the image building gap needs separate treatment.


---
_Migrated from beads `asya-0a1`_
