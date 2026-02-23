---
title: Add NATS transport support (code + Crossplane)
priority: 2 # medium
type: task
tags:
  - type:feature
---




Implement NATS as a new message transport for the Asya framework. This requires: 1) Sidecar transport plugin for NATS (Go, in src/asya-sidecar/internal/transports/), 2) Operator transport configuration and queue management for NATS, 3) Crossplane composition for NATS, 4) At least one delivery mode (e.g., JetStream for persistence). Must include unit tests, integration tests, and basic E2E coverage.


---
_Migrated from beads `asya-wo31`_
