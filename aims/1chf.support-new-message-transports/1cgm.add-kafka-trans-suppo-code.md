---
title: Add Kafka transport support (code + Crossplane)
status: open
priority: 3 # low
type: task
tags:
  - type:feature
---


Implement Apache Kafka as a new message transport for the Asya framework. This requires: 1) Sidecar transport plugin for Kafka (Go, in src/asya-sidecar/internal/transports/), 2) Operator transport configuration and topic management for Kafka, 3) Crossplane composition for Kafka, 4) Consumer group support for scaling. Must include unit tests, integration tests, and basic E2E coverage.


---
_Migrated from beads `asya-fg1v`_
