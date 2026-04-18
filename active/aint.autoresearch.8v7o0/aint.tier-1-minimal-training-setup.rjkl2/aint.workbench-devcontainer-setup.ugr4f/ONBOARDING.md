# Workbench Onboarding — AI Agent Guide

You are running inside an EKS workbench pod. This document explains your
environment and how to use Asya to offload heavy workloads.

## Your Environment

You are `dev` user with sudo on an Ubuntu pod in EKS cluster `aimc-test-eu-1-blue`,
namespace `atem`. Your session persists across reconnects (PVCs survive pod restarts).

### Mounts

| Path | PVC | Purpose |
|---|---|---|
| `/home/dev` | workbench-work (50Gi) | Git repos, worktrees, `~/.claude/`, config, tools |
| `/storage` | workbench-storage (200Gi) | Datasets, model checkpoints, large artifacts |
| `/tracking` | workbench-tracking (20Gi) | TensorBoard logs, experiment metrics |
| `/secrets/gcp/key.json` | K8s secret | GCP service account for Vertex AI + BigQuery |

### Available Tools

- `claude` — Claude Code CLI (via GCP Vertex AI)
- `kubectl` — K8s access to `atem` namespace (in-cluster auth, no kubeconfig needed)
- `helm` — Helm chart management
- `uv` — Python package manager
- `gcloud` / `bq` — GCP CLI (authenticated as `asya-workbench` SA)
- `git` / `git-aint` — Version control + experiment tracking
- `tmux` — Terminal multiplexer for parallel sessions

### Auth

- **AWS**: Pod Identity via `default` ServiceAccount → `asya-actor` IAM role
  (S3 read/write, SQS send/receive, SecretsManager)
- **GCP**: Service account key at `/secrets/gcp/key.json`. Env vars set:
  `GOOGLE_APPLICATION_CREDENTIALS`, `CLAUDE_CODE_USE_VERTEX=1`
- **kubectl**: RBAC role allows create/update/delete AsyncActors and ConfigMaps
  in `atem` namespace

## What is Asya?

Asya is an Actor Mesh framework for running workloads on Kubernetes. Actors are
stateless Python handlers that communicate by passing envelopes through message
queues (SQS). The key components:

- **AsyncActor**: K8s custom resource defining an actor (handler code, queue, scaling)
- **Sidecar**: injected into each actor pod, handles queue I/O and routing
- **Runtime**: loads your Python handler, executes it, returns results
- **State Proxy**: gives actors virtual filesystem backed by S3/Redis/etc

## How to Use Asya from This Workbench

### Pattern: Offload Heavy Work to Asya Flows

You (the agent) handle planning, code writing, and analysis. Asya actors handle
compute-heavy execution (training, evaluation, data processing).

### Step-by-Step: Deploy a Training Actor

1. **Write the handler** — a Python function `dict -> dict`:

```python
# /home/dev/repo/experiments/train.py
def handler(payload):
    import torch
    # ... training code ...
    # Read dataset from /storage/ (PVC mounted in actor too)
    # Write metrics to /tracking/ (PVC mounted in actor too)
    # Write checkpoint to /storage/checkpoints/
    return {"status": "done", "accuracy": 0.95}
```

2. **Write the AsyncActor manifest**:

```yaml
# /home/dev/repo/experiments/train-actor.yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: train-vit
  namespace: atem
spec:
  compositionSelector:
    matchLabels:
      transport: sqs
  transport: sqs
  actor:
    handler: handler
  # Handler code delivered via ConfigMap (for small scripts)
  # For larger codebases, use volumes with git-sync
```

3. **Create ConfigMap with handler code**:

```bash
kubectl create configmap train-vit-handler -n atem \
  --from-file=handler.py=experiments/train.py
```

4. **Deploy the actor**:

```bash
kubectl apply -f experiments/train-actor.yaml
```

5. **Trigger via SQS** (no gateway in tier 1):

```bash
QUEUE_URL=$(aws sqs get-queue-url --queue-name asya-atem-train-vit --region eu-central-1 --query QueueUrl --output text)
aws sqs send-message --queue-url "$QUEUE_URL" --region eu-central-1 \
  --message-body '{"id":"exp-001","parent_id":"exp-001","route":{"prev":[],"curr":"train-vit","next":[]},"headers":{},"payload":{"lr":0.001,"epochs":10}}'
```

6. **Monitor**:

```bash
# Actor logs
kubectl logs -n atem -l asya.sh/actor=train-vit -c asya-runtime --tail=50

# TensorBoard (if metrics written to /tracking/)
tensorboard --logdir /tracking/ --bind_all --port 6006
# Then port-forward from local: kubectl port-forward deploy/workbench 6006:6006
```

## Data Locations

| Data | Where | Why |
|---|---|---|
| Training datasets (images) | `/storage/dataset/` | Fast local I/O for training loops |
| Model checkpoints | `/storage/checkpoints/` | Large blobs, persist across experiments |
| TensorBoard logs | `/tracking/` | Separate PVC, will become state proxy later |
| Code | `/home/dev/repo/` | Git repo on workspace PVC |
| Experiment tracking | `.aint/` in the repo | Git-based, shared across agents |

**Design Principle 002**: Do NOT use Asya state proxy for training datasets.
State proxy adds ~50ms per file read (Unix socket -> HTTP -> S3). Use PVC or
bulk copy (`aws s3 sync`) for data accessed in tight training loops. State proxy
is for infrequent state (metrics, checkpoints, experiment tracking).

## Existing Cluster Resources

- Crossplane + asya-crossplane chart in `asya-system` (v1.0.9)
- asya-crew (x-sink, x-sump) in `atem` (v1.0.9)
- SQS queues: `asya-atem-smoke-test`, `asya-atem-x-sink`, `asya-atem-x-sump`
- Sidecar image: `ghcr.io/deliveryhero/asya-sidecar:1.0.9`
- **No gateway deployed yet** — trigger flows via SQS directly for tier 1

## Important Constraints

- Do NOT upgrade KEDA (v2.14.2 in `keda` ns, managed by infra team)
- AWS resources require tags: `dh_app=asya`, `dh_squad=aimc`, `dh_tribe=foodscience`
- `awsAccountId` must be string in Helm: `--set-string awsAccountId="380754419530"`
- Pod Identity associations need ~10s to propagate after creation

## Context: Autoresearch Epic

This workbench is part of the Autoresearch initiative (aint `8v7o0`). The
long-term goal is autonomous ML experimentation: an orchestrator flow that
iterates training/evaluation loops, tracks experiments via git-aint, and
accumulates knowledge in a memory state proxy.

For now (tier 1), you work interactively with the human user: explore data,
write training code, deploy actors, analyze results, iterate manually.

Full design: `.aint/active/aint.autoresearch.8v7o0/rfc.md`
