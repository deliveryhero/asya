---
title: Add Redis Streams transport support (code + Crossplane)
status: open
priority: 3 # low
type: task
tags:
  - type:feature
---



Implement Redis Streams as a new message transport for the Asya framework. This requires: 1) Sidecar transport plugin for Redis Streams (Go, in src/asya-sidecar/internal/transports/), 2) Operator transport configuration and stream/consumer-group management for Redis Streams, 3) Crossplane composition for Redis, 4) Consumer group support for scaling and XACK-based acknowledgement. Must include unit tests, integration tests, and basic E2E coverage.


---
_Migrated from beads `asya-3109`_
