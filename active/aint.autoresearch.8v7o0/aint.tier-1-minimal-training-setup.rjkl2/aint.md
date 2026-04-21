---
title: "Tier 1: Minimal training setup"
status: open
priority: 1 # high
tags: [tier-1, autoresearch]
---

## Goal

Human + Claude Code on EKS workbench, manually deploy training flows, train
ViT over-upscaling classifier, get results. No automation loop.

## Concrete Task

Build a ViT-based classifier detecting over-upscaling on food images. Dataset:
~5K image pairs (original + properly enhanced, original + overly enhanced), some
synthetic. Collect/clean dataset, train model, evaluate, iterate manually.

## Architecture (Minimal)

- **Workbench**: devcontainer on EKS, PVC for code + `.claude/`, TensorBoard
- **Dataset**: on PVC or emptyDir (NOT state proxy — too slow for training I/O,
  see Design Principle 002). Bulk copy from S3 at pod startup.
- **Training actor**: ConfigMap handler, dataset on PVC/emptyDir (bulk copy),
  writes TFEvents to S3 state proxy, writes checkpoint to S3 state proxy
- **Code delivery**: ConfigMap for small scripts. Git state proxy (read-only)
  as stretch goal for larger codebases.
- **Metrics**: TFEvents on S3, TensorBoard on workbench reads S3 directly
- **Visualization**: FiftyOne on workbench for image pair browsing + labeling
- **Triggering**: POST to gateway (existing)

## What's NOT Needed

x-deploy, memory proxy, dataset versioning, autoresearch loop, route
enforcement, cron, append mode

## Aints

| Aint | Title | Status |
|---|---|---|
| ugr4f | Workbench devcontainer setup | running (pod deployed, surviving restarts) |
| bh1rg | Dataset visualization (FiftyOne) | open |
| cynl0 | XRD init/sidecar containers | open (moved from tier 2 — blocks code delivery) |
| jf7uo | Init container code delivery for training actors | open (depends on cynl0) |
| g87or | EFS CSI driver for shared ReadWriteMany storage | open |
| cy0p1 | Git state proxy (stretch) | open |
