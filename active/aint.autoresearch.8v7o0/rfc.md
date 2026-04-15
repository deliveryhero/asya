# RFC: Autoresearch — Distributed ML Experimentation on Asya

**Status:** Draft
**Date:** 2026-04-15
**Authors:** Artem Yushkovskiy, Claude

## 1. Executive Summary

Asya today runs AI workloads. This RFC extends it to **implement** them: a
human (or their coding agent) formulates hypotheses, and Asya flows execute
training, evaluation, and analysis autonomously — iterating until a target is
met, a budget is exhausted, or human input is needed.

The core pattern: a **generic autoresearch flow** (deployed once per namespace)
receives an experiment specification, fans out N parallel experiments, collects
results, and decides what to try next. Training actors are workers, evaluation
is an immutable "environment," and the orchestrator-brain is an LLM-powered
decision-maker with constrained routing.

This framing maps to **Bayesian optimization with LLM as acquisition function**:
the LLM uses world knowledge + experiment history (memory state proxy) to
propose the most promising next experiments. The evaluation flow is the
objective function. The action space and reward are defined per experiment.

## 2. Problem

Today's ML experimentation is manual: the researcher trains models in notebooks,
checks metrics, adjusts hyperparameters, and repeats. This is:

- **Sequential**: one experiment at a time, idle GPU while thinking
- **Untracked**: decisions and reasoning lost between sessions
- **Not production-ready**: notebook code must be rewritten for deployment
- **Not parallelizable**: can't easily run 10 variants and compare

Asya's queue-based mesh with per-actor scaling, fault isolation, and stateless
handlers solves the infrastructure problem. What's missing is the **state
management** (memory, git, datasets, metrics) and **orchestration logic**
(the experimentation loop itself).

## 3. Design Principles

1. **FS-like state proxy interface** (Design Principle 001): all state proxies
   expose filesystem operations. Actor handlers use `open()`, `os.listdir()`,
   etc. Zero SDK imports. Testable locally with plain files.

2. **Actors are workers, flows are topologies**: actors execute business logic
   (train, evaluate, decide). Flows define execution graphs. The orchestrator-brain
   is a flow handler (constrained routing), not a free-routing actor.

3. **Evaluation is immutable**: the evaluation flow is the "environment" in RL
   terms. The orchestrator cannot modify, skip, or bypass it. Enforced by
   compiled flow topology + route allowlists.

4. **State separation**: payload = RAM (per-message), state proxy = SSD
   (persists across messages and flows), git = persistent versioned storage
   (code, experiments, manifests).

## 4. Architecture

### 4.1 Layers

**Layer 0 — Storage backends** (existing)
- S3: datasets, model checkpoints, metrics, memory
- Git (`aint-sync` branch): experiment tracking
- Git (feature branches): code

**Layer 1 — State proxies**

| Proxy | Backend | Mount | Purpose |
|---|---|---|---|
| S3 (existing) | S3 | /data, /checkpoints, /metrics | Large blobs, metrics |
| Git (new) | Git repo | /code, /aint | Code + experiment tracking |
| Memory (new) | S3 | /memory | Accumulated reasoning history |
| Dataset (new) | S3 + Rust lib | /dataset | Versioned dataset access |

The **git state proxy** is the foundational new proxy. It mounts any git branch
as a filesystem. Write = commit + push. Read = serve from local clone.

The **git-aint state proxy** is a specialization: same backend, but write
triggers `git aint sync` (which regenerates `auto_state.md`) instead of plain
`git commit + push`. Implemented by configuring a pre-commit git hook that
runs `git aint auto-state` before commit.

The **memory state proxy** is S3 with a write-triggered hook that rebuilds
the `MEMORY.md` index (deterministic: scan files, read frontmatter, write
one-line entries). LLM-powered summarization runs separately via a cron
"dreaming" flow.

The **dataset state proxy** wraps a Rust content-hash library (`asya-dataset`)
that provides snapshot/diff/dedup on top of S3. Actor sees transparent
versioned files. See `design-dataset-state-proxy.md`.

**Layer 2 — Actors and flows**

- Worker actors: training, evaluation, data generation (stateless, S3 mounts)
- Orchestrator-brain: LLM-powered decision-maker (git + memory + S3 mounts)
- Results-collector: fan-in aggregation
- x-deploy: crew actor for deploying actors/flows from git
- Memory-curator: cron flow for memory compaction/summarization

**Layer 3 — Workbench**

Minimal devcontainer (VS Code) with PVC for code, kubectl access, Claude Code.
Not Asya-specific — just a persistent dev environment. S3 mounted via EKS
Mountpoint for S3 CSI (for dataset exploration).

### 4.2 Generic Autoresearch Flow

```python
@flow
def autoresearch(p):
    while True:
        decision = orchestrator_brain(p)
        if decision["action"] == "stop":
            break
        results = [
            eval_model(train_model(exp))
            for exp in decision["experiments"]
        ]
        p = results_collector(results)
    return p
```

Compiles to a fixed-topology flow with:
- orchestrator-brain: returns action (stop or list of experiments)
- train-model: receives hyperparams, trains, writes checkpoint + metrics
- eval-model: reads checkpoint, evaluates against fixed test set, returns metrics
- results-collector: aggregates N results into a summary

Route allowlists are auto-generated by the compiler:
- orchestrator-brain: can route to train-model only (or stop)
- train-model: can route to eval-model only
- eval-model: can route to results-collector only
- results-collector: can route to orchestrator-brain only

### 4.3 Experiment Specification

Defined as an aint markdown file:

```yaml
---
title: Train ResNet on ImageNet-subset
status: open
priority: 1
tags: [experiment]
---

## Objective
Achieve accuracy > 0.95 on ImageNet-subset test set.

## Action Space
- learning_rate: [0.0001, 0.001, 0.01, 0.1]
- batch_size: [16, 32, 64, 128, 256]
- architecture: [resnet18, resnet50, efficientnet_b0]
- optimizer: [adam, sgd_momentum]

## Environment (Evaluation)
- handler: src/experiments/eval_imagenet.py
- dataset: s3://datasets/imagenet-subset/test/
- metric: top1_accuracy
- immutable: true

## Budget
- max_iterations: 20
- max_parallel: 5
- max_wall_time: 4h

## Dataset
- path: s3://datasets/imagenet-subset/
- snapshot: v002
```

### 4.4 RL-Structured Loop

| RL Concept | Autoresearch Equivalent |
|---|---|
| State | experiment history (memory) + current metrics + budget remaining |
| Action | hyperparams, architecture, data cleaning strategy |
| Environment | eval flow (immutable, computes reward from scratch) |
| Reward | evaluation metric vs target threshold |
| Policy | LLM reasoning (zero-shot, not trained) |
| Experience replay | memory state proxy (accumulated observations) |
| Episode | one full experiment run (multiple iterations) |
| Budget | max iterations, max parallel, max compute |

The LLM is the acquisition function in Bayesian optimization terms: it uses
world knowledge + experiment history to propose the most promising next
experiments. Unlike classical BO (which fits a GP posterior), the LLM reasons
about the experiment landscape using its training knowledge.

#### Two Levels of Orchestration

**Level 1 — LLM as acquisition function (v0)**:
The orchestrator-brain calls the LLM directly: "given these results, propose
next experiments." The LLM proposes concrete parameter combinations. Simple,
works out of the box, but the LLM doesn't learn a reusable search strategy.

**Level 2 — LLM generates the acquisition function (LLAMBO-inspired)**:
Instead of proposing experiments directly, the LLM writes a *search strategy
as Python code* — e.g., "scan learning rates logarithmically, then fine-tune
around the best with linear search." That strategy generates N experiments,
results come back, the LLM refines the strategy code itself.

This is inspired by LLAMBO (Ghorbanpour et al., NeurIPS 2024 Workshop on ML
and Physical Sciences): "LLM Enhanced Bayesian Optimization for Scientific
Applications." Their key finding: LLM-generated acquisition functions
(Python code) outperform standard Expected Improvement and Upper Confidence
Bound on complex scientific optimization (Inertial Confinement Fusion). Even
open-source WizardCoder-34B matched proprietary models.

Why Level 2 fits Asya naturally:
- The orchestrator already writes code to git state proxy
- x-deploy already deploys new actors from git
- The generated strategy code is just another handler (compilable, deployable)
- The evaluation flow remains immutable (safety preserved)
- The LLM optimizes the *search algorithm*, not just the hyperparameters

Level 2 requires no additional infrastructure beyond Level 1 — just a different
orchestrator prompt strategy. Implement Level 1 first, upgrade to Level 2 when
the loop is proven.

### 4.5 Code Delivery

Actors receive code via **git state proxy** (default) or **ConfigMap** (simple
handlers). The git state proxy mounts a branch, actor reads code from it. If
performance becomes an issue (many file writes = many commits), fall back to
git-sync init container.

For actors that modify code (orchestrator generating new PyTorch modules):
write to git state proxy → commit + push → x-deploy reads from same branch
and applies updated manifests.

**x-deploy** is a crew actor (deployed per namespace by admin). Receives
envelope with `{"branch": "...", "manifest_path": "..."}`, mounts git state
proxy (read-only), reads manifest, runs `asya compile` + `kubectl apply`.

Modes:
- **apply-and-wait** (default): apply, poll until Ready, return status
- **fire-and-forget**: apply, return immediately

Failure handling: standard Asya retry policy. If deployment fails after
retries, envelope goes to x-sump (DLQ).

Security (v0, single-tenant): x-deploy ServiceAccount has namespace-scoped
Role (create/update AsyncActor + ConfigMap in its own namespace only). Image
allowlist enforced by the actor. Multi-tenant hardening deferred.

### 4.6 Safety: Route Enforcement

To prevent reward hacking (LLM-orchestrator bypassing evaluation):

1. **Compiled flows** generate route allowlists automatically from the graph
2. **Runtime enforcement**: `yield "SET", ".route.next", [blocked]` raises
   `RoutingError` in Python — immediate feedback to the handler
3. **Sidecar enforcement**: belt + suspenders — rejects envelope if route.next
   contains blocked targets

See aint `krses` for implementation details.

### 4.7 Metrics and Observability

**Training metrics**: TFEvents written to S3 state proxy via standard
TensorBoard writer (`tf.summary` or `torch.utils.tensorboard`). Writer opens
file once (`"wb"`), appends events in memory, PUTs on close. Works transparently
on state proxy. TensorBoard reads S3 directly:
`tensorboard --logdir s3://bucket/metrics/`.

**Experiment tracking**: git-aint. Each experiment is an aint with status
progression (open -> working -> pushed -> merged/rejected). Orchestrator updates
aint via git state proxy.

**FLY events**: training actors emit live streaming events (loss per step,
progress) via `yield "FLY", {...}`. Gateway streams these via SSE. Future
dashboard subscribes for real-time experiment monitoring.

**Cron observability**: scheduled flows (memory dreaming, metrics GC) dispatch
via gateway POST. OTel tracing for when/what/duration. See aint `34yhs`.

### 4.8 Memory System

Two components:

**Memory state proxy** (S3-backed, mounted at `/memory/`):
- MEMORY.md index + topic files with YAML frontmatter
- Types: project, feedback, reference (from Claude Code taxonomy)
- Write triggers deterministic index rebuild (scan + list, no LLM)
- Actor reads MEMORY.md, decides which files to load (simple handler logic)

**Dreaming cron flow** (scheduled, mounts memory as raw S3):
- Reads all topic files + raw observations
- LLM summarizes, deduplicates, prunes stale entries
- Writes back curated files
- Depends on cron flow pattern (aint `34yhs`)

Dual mount pattern: same S3 prefix mounted as memory proxy (high-level
interface with index rebuild) for agents, and as plain S3 proxy (raw access)
for the dreaming flow.

### 4.9 Dataset Versioning

Rust content-hash library (`asya-dataset`) embedded in a dataset state proxy
sidecar. See `design-dataset-state-proxy.md` for full spec.

Key features:
- Transparent version mounting (actor doesn't know about versions)
- blake3 content hashing + optional perceptual hashing (images)
- Sharded JSONL metadata (scales to 100k+ files)
- Snapshot/diff (workbench-facing, via Python bindings)

## 5. Workbench

Minimal devcontainer (VS Code dev container image + PVC + post-install deps).
Provides: Claude Code, git, git-aint, kubectl, asya CLI, TensorBoard.

PVC layout: `/home/dev/` with git repo, worktrees, `.claude/` (memory,
settings, sessions), `.aint/`.

S3 access for dataset exploration via EKS Mountpoint for S3 CSI.

Not Asya-specific infrastructure — just a persistent dev environment that can
`kubectl apply` to the cluster.

## 6. Data Storage Strategy

**Design Principle 002**: state proxy is for **state** (infrequent, small-to-medium
I/O) — not for **bulk data** (frequent, latency-critical I/O). Every state proxy
`open()` call goes through Unix socket → HTTP → S3, adding ~50ms per operation.

| Data type | Access pattern | Storage | Why |
|---|---|---|---|
| Training dataset (images) | 1000s reads/epoch, tight loop | PVC / emptyDir + `aws s3 sync` | Latency-critical |
| Model checkpoints | Write once, read once | S3 state proxy | Infrequent, large blob |
| TFEvents metrics | Write once ("wb"), single file | S3 state proxy | One PUT on close |
| Metadata/labels (CSV/JSON) | Read once at start | Either | Latency irrelevant |
| Experiment tracking (aint) | Infrequent read/write | Git state proxy | Small files |
| Memory files | Infrequent read/write | S3 (memory proxy) | Small files |

**Training actor pattern**: init container or startup script does
`aws s3 sync s3://bucket/dataset/ /data/` to local volume (PVC or emptyDir).
Training reads local files at native filesystem speed. Metrics and checkpoints
go to S3 state proxy (infrequent writes).

## 7. Dataset Visualization

FiftyOne (Voxel51) for image pair browsing and labeling on the workbench [bh1rg].
Runs locally as a web app. Supports: grid view with images, filtering, one-click
tagging, comparison views.

Workflow for over-upscaling classifier dataset:
1. Load ~5K original images + N upscaled variants into FiftyOne dataset
2. Optional: VLM pre-labeling (Claude/GPT-4V scores each pair)
3. Human reviews in FiftyOne grid, one-click labels: good / over-upscaled / skip
4. Export cleaned labels as CSV for training pipeline

VLM pre-labeling can run as a simple Asya flow (parallelize VLM calls).

## 8. Implementation Tiers

Work is organized into four tiers. Each tier builds on the previous.

### Tier 1 [rjkl2] — "Train a model" (immediate)

Human + Claude Code on EKS workbench, manually deploy training flows, train ViT
over-upscaling classifier, get results. No automation loop.

| Aint | Title | Notes |
|---|---|---|
| ugr4f | Workbench devcontainer | EKS pod, PVC, Claude Code, kubectl, TensorBoard |
| bh1rg | Dataset visualization (FiftyOne) | Image pair browsing, one-click labeling |
| cy0p1 | Git state proxy (read-only stretch) | Optional: mount repo in training actor |

Everything else is existing Asya: S3 state proxy for metrics/checkpoints,
gateway for triggering, ConfigMap for code delivery. Dataset on PVC/emptyDir.

### Tier 2 [qclcl] — "Better infrastructure"

Proper code delivery, crash-resilient writes, scheduled flows.

| Aint | Title |
|---|---|
| jbtnm | Append mode state proxy |
| pr3ib | Periodic flush for buffered writes |
| cynl0 | XRD init/sidecar containers (git-sync) |
| cy0p1 | Git state proxy (full read-write) |
| 34yhs | Cron flow pattern + observability |

### Tier 3 [coeie] — "Autonomous experimentation"

Deploy-once generic autoresearch flow that iterates autonomously.

| Aint | Title |
|---|---|
| gsz18 | Memory state proxy + dreaming cron flow |
| zgdsp | x-deploy crew actor |
| krses | Route allowlist/blocklist enforcement |
| 5i52w | Generic autoresearch flow template |

### Tier 4 [9kega] — "Scale and polish"

Production-grade dataset management, meta-optimization, dashboards.

| Aint | Title |
|---|---|
| lb740 | Dataset state proxy (Rust content-hash library) |
| — | LLAMBO Level 2 orchestration |
| — | Experiment dashboard (real-time UI) |
| — | Multi-tenant security hardening |
| — | In-cloud image building |

## 9. What's New vs What Exists

| Component | Status | Tier |
|---|---|---|
| S3 state proxy | Exists | — |
| Gateway (MCP/A2A/SSE) | Exists | — |
| x-pause / x-resume | Exists | — |
| Self-routing (`yield "SET"`) | Exists | — |
| FLY events for streaming | Exists | — |
| Flow compiler (fan-out/fan-in, loops) | Exists | — |
| Workbench devcontainer | **New** [ugr4f] | 1 |
| Dataset visualization (FiftyOne) | **New** [bh1rg] | 1 |
| Git state proxy | **New** [cy0p1] | 1-2 |
| Append mode state proxy | **New** [jbtnm] | 2 |
| Periodic flush for buffered writes | **New** [pr3ib] | 2 |
| AsyncActor XRD init/sidecar containers | **New** [cynl0] | 2 |
| Cron flow pattern + observability | **New** [34yhs] | 2 |
| Memory state proxy + dreaming cron | **New** [gsz18] | 3 |
| x-deploy crew actor | **New** [zgdsp] | 3 |
| Route allowlist/blocklist enforcement | **New** [krses] | 3 |
| Generic autoresearch flow template | **New** [5i52w] | 3 |
| Dataset state proxy (Rust library) | **New** [lb740] | 4 |
| Gateway rework | **Separate** [63keu] | — |

## 10. Dependency Graph

```
Tier 1 (immediate):
  [ugr4f] workbench              (no deps)
  [bh1rg] dataset viz            (no deps)
  [cy0p1] git state proxy RO     (no deps, stretch)

Tier 2 (after tier 1):
  [jbtnm] append mode            (no deps, unblocks pr3ib)
  [pr3ib] periodic flush         (depends: jbtnm)
  [cynl0] XRD init/sidecars      (no deps)
  [cy0p1] git state proxy RW     (extends tier 1 work)
  [34yhs] cron flow pattern      (no deps, unblocks gsz18)

Tier 3 (after tier 2):
  [gsz18] memory + dreaming      (depends: cy0p1, 34yhs)
  [zgdsp] x-deploy crew actor    (depends: cy0p1)
  [krses] route enforcement      (no deps)
  [5i52w] autoresearch flow      (depends: cy0p1, krses, zgdsp)

Tier 4 (after tier 3):
  [lb740] dataset state proxy    (no deps, separate repo)

Separate:
  [63keu] gateway rework         (pre-existing, independent)
```

Critical path through tiers: ugr4f (workbench) → cy0p1 (git proxy RW) →
zgdsp (x-deploy) → 5i52w (autoresearch flow).

## 11. Open Questions

1. **x-deploy permissions long-term**: multi-tenant clusters need admission
   policies, image signing, resource quotas per tenant. Deferred.

2. **In-cloud image building**: when orchestrator generates new code and needs
   a fresh Docker image (not just ConfigMap update). Kaniko? BuildKit? Deferred.

3. **Experiment dashboard**: real-time UI subscribing to gateway SSE, showing
   parallel runs, loss curves, orchestrator decisions. Separate design.

4. **Named Claude Code sessions**: `claude --resume experiment-42` for ergonomic
   session management on the workbench. Claude Code feature request.

5. **Orchestrator-generated code validation**: when the LLM writes new PyTorch
   modules, how to validate them before deploying (syntax check, import check,
   shape check)? Sandboxed execution in the orchestrator pod?

6. **Memory relevance at scale**: keyword match on frontmatter works for <100
   memories. At 1000+, need embedding-based retrieval. Future optimization.

## 12. Non-Goals

- **Full RL training of the orchestrator policy**: the LLM is zero-shot.
  Memory provides few-shot context but no gradient updates.
- **Replacing Claude Code**: the workbench is for interactive work. Autoresearch
  flows handle the autonomous loop.
- **General-purpose CI/CD**: x-deploy is for Asya actors only, not arbitrary
  Kubernetes resources.
- **MLflow/W&B replacement**: metrics go to TensorBoard (existing tool).
  Experiment tracking is git-aint (markdown files). No new UI for v0.
