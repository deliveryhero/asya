---
title: KEDA external scaler for GCP Pub/Sub — eliminate 5min Cloud Monitoring lag
priority: 1 # high
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/debt/wpla.keda-external-scaler-gcp-pub-sub-eliminate-5min
  - branch:debt/wpla.keda-external-scaler-gcp-pub-sub-eliminate-5min
  - pr:383
---




## Problem

KEDA's built-in `gcp-pubsub` scaler uses Cloud Monitoring (Stackdriver) API for
both `SubscriptionSize` and `OldestUnackedMessageAge` modes. Cloud Monitoring has
a ~5 minute ingestion lag for metric data points. This means:

- Scale 0->1: 5 min delay (messages sit unprocessed)
- Scale 1->N: 5 min delay (backlog grows before KEDA reacts)
- Scale N->0: 5 min delay (idle pods waste resources)

Observed in GKE demo: full cold-start cascade for a 3-actor pipeline took ~4-5
minutes, with 99% of the time being Cloud Monitoring lag, not pod startup.

## Solution

Build a KEDA external scaler (gRPC service) that queries the Pub/Sub Admin API
directly. `projects.subscriptions.get` returns `numUndeliveredMessages` instantly
with no Monitoring lag. Expected scaling latency: 1-2 seconds.

### Implementation

- Small Go service (~100 lines) implementing KEDA external scaler gRPC interface
- Deploys as a Deployment in the platform namespace (e.g. asya-system)
- Uses Workload Identity for GCP auth (same SA as actors)
- Crossplane composition generates `type: external` ScaledObjects instead of
  `type: gcp-pubsub`

### ScaledObject change

From:
```yaml
triggers:
- type: gcp-pubsub
  metadata:
    mode: SubscriptionSize
    subscriptionName: projects/PROJECT/subscriptions/SUB
```

To:
```yaml
triggers:
- type: external
  metadata:
    scalerAddress: "asya-pubsub-scaler.asya-system:6000"
    subscriptionName: "SUB"
    projectId: "PROJECT"
```

### Scope

- [ ] Go gRPC service implementing `externalscaler.ExternalScaler`
- [ ] Dockerfile + Helm chart (or add to asya-crossplane chart)
- [ ] Update Crossplane composition to generate external ScaledObjects
- [ ] Update asya-crossplane values.yaml: `keda.scalerType: external`
- [ ] E2E test: verify scale 0->1 latency < 5s
- [ ] Update GKE install docs
