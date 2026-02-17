---
title: Add Google Pub/Sub transport support (code + Crossplane)
status: open
priority: 3 # low
type: task
---

Implement Google Cloud Pub/Sub as a new message transport for the Asya framework. This requires: 1) Sidecar transport plugin for Pub/Sub (Go, in src/asya-sidecar/internal/transports/), 2) Operator transport configuration and subscription management for Pub/Sub, 3) Crossplane composition for Pub/Sub, 4) GCP IAM and credential management. Must include unit tests, integration tests, and basic E2E coverage.


---
_Migrated from beads `asya-d8l9`_
