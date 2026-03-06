---
title: Add Google Pub/Sub transport support (code + Crossplane)
priority: 3 # low
tags:
  - type:feature
  - pr:251
  - user-approved
---







Implement Google Cloud Pub/Sub as a new message transport for the Asya framework. This requires: 1) Sidecar transport plugin for Pub/Sub (Go, in src/asya-sidecar/internal/transports/), 2) Operator transport configuration and subscription management for Pub/Sub, 3) Crossplane composition for Pub/Sub, 4) GCP IAM and credential management. Must include unit tests, integration tests, and basic E2E coverage.

## Design Decisions

- **Provisioning**: Crossplane-managed (like SQS). Crossplane creates Topic + Subscription via provider-gcp-pubsub.
- **Testing**: Use official GCP Pub/Sub emulator (`google/cloud-sdk` image) for component/integration/E2E tests.
- **SendWithDelay**: Return `ErrDelayNotSupported` (like RabbitMQ). No Cloud Tasks workaround.
- **Queue naming**: Same convention as SQS/RabbitMQ: `asya-{namespace}-{actorName}` for both topic and subscription names.
- **Receipt handle**: Store `*pubsub.Message` pointer (native ack/nack via client library).
- **Auth**: Support both Workload Identity (GKE) and service account JSON key (generic K8s).

## Implementation Plan

### Step 1: Sidecar transport implementation
Files:
- `src/asya-sidecar/internal/transport/pubsub.go` — PubSubTransport struct implementing Transport interface
- `src/asya-sidecar/internal/transport/pubsub_test.go` — Unit tests with mock client
- `src/asya-sidecar/internal/config/config.go` — Add PubSubProjectID, PubSubEndpoint fields
- `src/asya-sidecar/cmd/sidecar/main.go` — Add `case "pubsub"` to transport switch

PubSubTransport methods:
- `NewPubSubTransport(ctx, cfg)` — Create client with optional emulator endpoint
- `Receive(ctx, queueName)` — Pull from subscription via subscription.Receive(), single-message channel pattern
- `Send(ctx, queueName, body)` — Publish to topic synchronously
- `SendWithDelay(ctx, queueName, body, delay)` — Return ErrDelayNotSupported
- `Ack(ctx, msg)` — msg.ReceiptHandle.(*pubsub.Message).Ack()
- `Requeue(ctx, msg)` — msg.ReceiptHandle.(*pubsub.Message).Nack()
- `Close()` — client.Close()

### Step 2: Gateway queue client
Files:
- `src/asya-gateway/internal/queue/pubsub.go` — PubSubClient implementing Client interface
- `src/asya-gateway/internal/queue/pubsub_test.go` — Unit tests
- `src/asya-gateway/cmd/gateway/main.go` — Add pubsub client creation path

### Step 3: Injector updates
Files:
- `src/asya-injector/internal/config/config.go` — Add PubSubEndpoint, GCPCredsSecret
- `src/asya-injector/internal/injection/inject.go` — Add pubsub env var injection
- `deploy/helm-charts/asya-injector/values.yaml` — Add pubsub config fields
- `deploy/helm-charts/asya-injector/templates/deployment.yaml` — Wire new env vars

### Step 4: Crossplane XRD + composition
Files:
- `deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml` — Add `pubsub` to enum, add `gcpProject` field
- `deploy/helm-charts/asya-crossplane/templates/composition-pubsub.yaml` — New composition pipeline:
  1. Resolve overlays (reuse)
  2. Render Topic (pubsub.gcp.upbound.io/v1beta2/Topic)
  3. Render Subscription (pubsub.gcp.upbound.io/v1beta2/Subscription, ackDeadlineSeconds=300)
  4. Render TriggerAuthentication (KEDA gcp-pubsub auth)
  5. Render ScaledObject (trigger type: gcp-pubsub, metric: subscriptionSize)
  6. Render Deployment (reuse pattern)
  7. Patch status (queueIdentifier = subscription name)
  8. Auto-ready (reuse)
- `deploy/helm-charts/asya-crossplane/values.yaml` — Add gcpProviderConfig, pubsub sections

### Step 5: Helm chart updates
Files:
- `deploy/helm-charts/asya-gateway/values.yaml` — Add pubsub transport config
- `deploy/helm-charts/asya-crew/values.yaml` — Add pubsub as valid transport option

### Step 6: Test infrastructure
Files:
- `testing/shared/compose/pubsub.yml` — Pub/Sub emulator service + topic/subscription setup
- `testing/shared/compose/envs/.env.pubsub` — Pub/Sub env vars
- `testing/shared/compose/configs/pubsub-setup.sh` — Script to create topics/subscriptions via gcloud
- Component test profiles: `testing/component/sidecar/profiles/pubsub.yml` + `.env.pubsub`
- Integration test profiles: `testing/integration/sidecar-runtime/profiles/pubsub.yml` + `.env.pubsub`
- E2E chart: `testing/e2e/charts/pubsub/` (emulator deployment)
- E2E profile: `testing/e2e/profiles/pubsub-s3.yaml` + `.env.pubsub-s3`
- Makefile updates across all test levels

### Step 7: Go module dependencies
- `src/asya-sidecar/go.mod` — Add `cloud.google.com/go/pubsub`
- `src/asya-gateway/go.mod` — Add `cloud.google.com/go/pubsub`
