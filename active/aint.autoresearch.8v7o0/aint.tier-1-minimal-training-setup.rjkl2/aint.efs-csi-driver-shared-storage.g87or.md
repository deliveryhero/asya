---
title: EFS CSI driver for shared ReadWriteMany storage
status: open
priority: 1 # high
tags: [tier-1, autoresearch, storage, efs, eks]
---

## Context

The workbench and training actors both need access to datasets and code. Current
EBS-backed PVCs (gp2/gp3) are ReadWriteOnce — they can only be mounted to a
single pod at a time. This means:

1. Workbench pod and training actor pod cannot share a PVC simultaneously
2. Dataset PVCs cannot be browsed from workbench while training is running
3. Code changes on the workbench PVC are not visible to actors

We created a duplicate `flow-storage` PVC as a workaround, but this doesn't
solve the fundamental issue — the two copies diverge immediately.

## Problem

EBS volumes are block storage, bound to a single AZ and single pod. For the
workbench + actor collaboration pattern, we need a shared filesystem.

## Solution: Amazon EFS CSI Driver

EFS provides a POSIX-compliant shared filesystem that supports ReadWriteMany
(RWX) access mode — multiple pods can mount the same volume simultaneously.

### Installation

EFS CSI driver is being installed separately (outside this aint). This aint
tracks the PVC/StorageClass configuration and migration of workloads to use it.

### StorageClass

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: efs-sc
provisioner: efs.csi.aws.com
parameters:
  provisioningMode: efs-ap
  fileSystemId: ${EFS_FS_ID}
  directoryPerms: "700"
  basePath: "/asya"
```

### PVC Migration

Replace relevant EBS PVCs with EFS-backed ones:

| Current PVC | Access | Replace with | Purpose |
|---|---|---|---|
| workbench-storage (200Gi) | RWO | shared-storage (EFS) | Datasets, checkpoints — shared between workbench and actors |
| flow-storage (200Gi) | RWO | (remove) | Was a workaround for RWO limitation |
| workbench-work (50Gi) | RWO | keep as EBS | Workbench-only: git repos, .claude/, fast I/O |
| workbench-tracking (20Gi) | RWO | shared-tracking (EFS) | TensorBoard logs — readable from workbench during training |

**Keep workbench-work on EBS**: git operations and editor I/O benefit from
block storage latency. Only shared volumes move to EFS.

### Performance Considerations

- EFS General Purpose mode is sufficient for dataset reads and checkpoint writes
- EFS throughput scales with size (Bursting mode) or can use Provisioned mode
- For training data loading: EFS is ~10x slower than local NVMe but acceptable
  for the image classification workload (~5K images, <10GB)
- If I/O becomes a bottleneck: bulk-copy from EFS to emptyDir at pod startup
  (same pattern as S3 bulk copy in tier 1 spec)

## Deliverables

1. StorageClass manifest for EFS
2. Updated PVC manifests (shared-storage, shared-tracking)
3. Updated workbench deployment to mount EFS PVCs
4. Remove flow-storage PVC workaround
5. Update workbench-handoff.md with new storage layout

## Testing

- Verify workbench pod and training actor pod can mount shared-storage simultaneously
- Verify writes from training actor are visible from workbench in real-time
- Verify TensorBoard on workbench can read training logs while training is running
- Basic I/O performance sanity check (sequential read/write throughput)
