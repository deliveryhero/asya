# Autoresearch Tiers

## Tier 1 — "Train a model" (immediate)

**Goal**: Human + Claude Code on EKS workbench, manually deploy training flows,
train ViT over-upscaling classifier, get results.

**Concrete task**: Build a ViT-based classifier detecting over-upscaling. Dataset
is ~5K image pairs (original + properly enhanced, original + overly enhanced),
some synthetic. Collect/clean dataset, train model, evaluate, iterate manually.

### What's needed

| Component | How | Aint |
|---|---|---|
| Workbench devcontainer | VS Code devcontainer on EKS, PVC, Claude Code, kubectl | ugr4f |
| Dataset on S3 | Upload images + metadata to S3 bucket | (manual) |
| S3 access from workbench | S3 Mountpoint CSI or aws CLI | part of ugr4f |
| Training AsyncActor | Reads S3 (existing state proxy), trains ViT, writes TFEvents + checkpoint to S3 | (manual, actor manifest) |
| Code delivery | ConfigMap for small handler scripts | (existing) |
| Trigger flow | POST to gateway | (existing) |
| TensorBoard | Runs on workbench, reads S3 directly | part of ugr4f |
| Dataset visualization | FiftyOne on workbench for image pair browsing + quick labeling | new |
| Git state proxy (read-only) | Optional: mount repo in training actor for larger codebases | cy0p1 (stretch) |

### What's NOT needed
- x-deploy, memory proxy, dataset versioning, autoresearch loop
- Route enforcement, cron, append mode
- Custom Docker image building

### Aints: ugr4f (workbench), new (dataset viz), cy0p1 (stretch)

---

## Tier 2 — "Better infrastructure" (state proxies, code delivery)

**Goal**: Proper code delivery to actors, crash-resilient writes, scheduled flows.
Enables more complex training pipelines without manual kubectl.

| Aint | Title |
|---|---|
| jbtnm | Append mode state proxy |
| pr3ib | Periodic flush for buffered writes |
| cynl0 | XRD init/sidecar containers |
| cy0p1 | Git state proxy (full read-write, if not done in tier 1) |
| 34yhs | Cron flow pattern + observability |

---

## Tier 3 — "Autonomous experimentation" (the loop)

**Goal**: Deploy-once generic autoresearch flow that iterates autonomously.
Human starts experiment, walks away (or gets paused for input).

| Aint | Title |
|---|---|
| gsz18 | Memory state proxy + dreaming cron flow |
| zgdsp | x-deploy crew actor |
| krses | Route allowlist/blocklist enforcement |
| 5i52w | Generic autoresearch flow template |

---

## Tier 4 — "Scale and polish"

**Goal**: Production-grade dataset management, meta-optimization, dashboards.

| Component | Aint |
|---|---|
| Dataset state proxy (Rust content-hash library) | lb740 |
| LLAMBO-inspired Level 2 orchestration | (future) |
| Experiment dashboard (real-time UI) | (future) |
| Multi-tenant security hardening | (future) |
| In-cloud image building | (future) |
