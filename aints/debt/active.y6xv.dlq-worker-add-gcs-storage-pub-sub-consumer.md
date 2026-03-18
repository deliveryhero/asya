---
title: "dlq-worker: add GCS storage + Pub/Sub consumer for native GKE"
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/debt/y6xv.dlq-worker-add-gcs-storage-pub-sub-consumer
  - branch:debt/y6xv.dlq-worker-add-gcs-storage-pub-sub-consumer
---


The dlq-worker currently only supports SQS consumer + S3 storage. For native GKE deployments (Pub/Sub transport), it is disabled. Add:
1. consumer_pubsub.go — Pub/Sub pull subscriber implementing the Consumer interface
2. storage_gcs.go — GCS native storage using Workload Identity (no HMAC keys)
3. config.go — add pubsub transport + GCS_BUCKET config, remove sqs-only validation
4. gcp-gke.md — enable dlq-worker, document dead letter topic setup
