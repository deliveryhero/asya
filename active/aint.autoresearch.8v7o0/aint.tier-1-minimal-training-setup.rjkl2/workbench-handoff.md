# Workbench Setup — Handoff Context

## Goal

Deploy a minimal persistent dev workbench on EKS for training a ViT
over-upscaling classifier. Plain Deployment + 2 PVCs (not Coder).

## EKS Cluster

- **Cluster**: `aimc-test-eu-1-blue`, region `eu-central-1`, account `380754419530`
- **Kubeconfig**: `aws eks update-kubeconfig --name aimc-test-eu-1-blue --region eu-central-1 --alias aimc-test-eu-1-blue`
- **API endpoint is VPC-private** (not reachable from GCP VMs)
- **Actor namespace**: `atem`
- **System namespace**: `asya-system` (Crossplane + asya-crossplane chart)
- **AWS profile**: `aimc-test` (aliases: `aws-test`, `ktest`, `helm-test`)
- **IAM user with EKS access**: `gcp-test-user` (cluster-admin via EKS access entry)

## Auth Chain (AWS to GCP)

EKS pods get AWS creds via **Pod Identity** (not IRSA). GCP access is via
**Workload Identity Federation** configured in Terraform
(`cimt-aimc-infra-terraform/terraform/apps/aimenu-sdxl-aws/iam.tf`).

Existing Pod Identity associations in `atem` namespace:
- `default` SA → `asya-actor` role (SQS send/receive, S3, SecretsManager)
- `asya-actors` SA → `asya-actor` role (created for future use)

The workbench pod needs:
1. **AWS access**: S3 (dataset sync), SQS (optional, for triggering flows)
2. **GCP access**: BigQuery (load data), Vertex AI (Claude Code via Vertex)

Options:
- Use existing `default` SA in `atem` (already has `asya-actor` Pod Identity)
- Create dedicated `workbench` SA with both AWS Pod Identity + GCP WIF

## Two-PVC Layout

```yaml
# PVC 1: working directory — git repos, code, Claude Code state
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: workbench-work
  namespace: atem
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: gp3  # check: kubectl get sc
  resources:
    requests:
      storage: 50Gi

---
# PVC 2: storage — datasets, checkpoints, model artifacts
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: workbench-storage
  namespace: atem
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: gp3
  resources:
    requests:
      storage: 200Gi
```

## Deployment Skeleton

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: workbench
  namespace: atem
spec:
  replicas: 1
  strategy:
    type: Recreate  # PVC is RWO, can't do rolling
  selector:
    matchLabels:
      app: workbench
  template:
    metadata:
      labels:
        app: workbench
    spec:
      serviceAccountName: default  # has asya-actor Pod Identity
      terminationGracePeriodSeconds: 300
      containers:
      - name: workbench
        image: mcr.microsoft.com/devcontainers/base:ubuntu
        command: ["sleep", "infinity"]
        volumeMounts:
        - name: work
          mountPath: /home/dev
        - name: storage
          mountPath: /storage
        resources:
          requests:
            cpu: "2"
            memory: 8Gi
          limits:
            cpu: "4"
            memory: 16Gi
      volumes:
      - name: work
        persistentVolumeClaim:
          claimName: workbench-work
      - name: storage
        persistentVolumeClaim:
          claimName: workbench-storage
```

## Post-Deploy Setup Script

Run inside the pod (`kubectl exec -it workbench-xxx -- bash`):

```bash
#!/bin/bash
set -euo pipefail

# System packages
apt-get update && apt-get install -y git curl tmux jq openssh-server

# uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# Python tools
uv tool install tensorboard
uv tool install fiftyone

# Claude Code CLI (via Vertex AI)
npm install -g @anthropic-ai/claude-code
# Configure for Vertex: CLAUDE_CODE_USE_VERTEX=1, CLOUD_ML_REGION, ANTHROPIC_VERTEX_PROJECT_ID

# kubectl + helm (for deploying actors from workbench)
curl -LO "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
install kubectl /usr/local/bin/
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# asya CLI
cd /home/dev && git clone https://github.com/asyacore/asya.git
cd asya && uv sync

# git-aint
# (install from https://github.com/atemate/git-aint)

# GCP CLI (for BQ data loading)
curl https://sdk.cloud.google.com | bash
# gcloud auth: should pick up WIF via Pod Identity → GCP token exchange
```

## Access the Workbench

```bash
# Option A: kubectl exec (simplest)
kubectl --context aimc-test-eu-1-blue exec -it -n atem deploy/workbench -- bash

# Option B: VS Code Remote via port-forward
kubectl --context aimc-test-eu-1-blue port-forward -n atem deploy/workbench 2222:22
# Then: ssh -p 2222 dev@localhost (needs sshd in container)

# Option C: VS Code + Kubernetes extension
# Attach to running container directly
```

## What Exists on the Cluster Already

- Crossplane + asya-crossplane chart in `asya-system` (v1.0.9)
- asya-crew (x-sink, x-sump) in `atem` (v1.0.9)
- SQS queues: `asya-atem-smoke-test`, `asya-atem-x-sink`, `asya-atem-x-sump`
- Sidecar image: `ghcr.io/deliveryhero/asya-sidecar:1.0.9`
- KEDA in `keda` namespace (v2.14.2, DO NOT upgrade)

## Training Workflow (after workbench is up)

1. SSH into workbench, run `claude`
2. Load dataset from BigQuery: `bq extract` or Python `google.cloud.bigquery`
3. Sync to storage PVC: data lives at `/storage/dataset/`
4. Write training handler + AsyncActor manifest
5. Deploy: `kubectl apply -f train-actor.yaml`
6. Trigger: `curl -X POST http://asya-gateway/a2a/v1/tasks -d '...'`
7. Monitor: `tensorboard --logdir s3://bucket/metrics/`
8. Browse images: `fiftyone` on port-forward or matplotlib in scripts

## Known Gotchas

- **Pod Identity timing**: new associations need ~10s. Delete and recreate pod
  if `eks-pod-identity-token` volume is missing.
- **AWS SCP requires tags**: all AWS resources need `dh_app`, `dh_squad`, `dh_tribe`
- **StorageClass**: verify `gp3` exists (`kubectl get sc`), may be `gp2` or custom
- **Gateway in-cluster URL**: check `kubectl get svc -n atem` for gateway service
- **awsAccountId must be string** in Helm: `--set-string awsAccountId="380754419530"`

## Aint Reference

Epic: `8v7o0` (autoresearch)
Tier 1 dir: `.aint/active/aint.autoresearch.8v7o0/aint.tier-1-minimal-training-setup.rjkl2/`
Workbench aint: `ugr4f`
RFC: `.aint/active/aint.autoresearch.8v7o0/rfc.md`

## Open Decisions (for next session)

1. **ServiceAccount**: use existing `default` or create dedicated `workbench` SA?
2. **GCP WIF details**: need to verify the exact federation config from Terraform
   (`cimt-aimc-infra-terraform/terraform/apps/aimenu-sdxl-aws/iam.tf`)
3. **SSH access**: sshd in container, or just `kubectl exec`?
4. **GPU**: workbench itself doesn't need GPU (training runs on actors), but
   if you want local training too, need a GPU node group
5. **Idle management**: for now none (pod runs 24/7). Coder can be added later
   for autostop.
