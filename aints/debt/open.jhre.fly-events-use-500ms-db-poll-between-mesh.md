---
title: FLY events use 500ms DB poll between mesh and api gateways — route directly to SSE clients
priority: 1 # high
---

In dual-gateway mode (api + mesh), FLY events from actors go: sidecar -> mesh gateway -> PostgreSQL (UpdateProgress) -> api gateway polls DB every 500ms -> SSE client. This adds up to 500ms latency per FLY event, making per-token LLM streaming choppy. FLY events are ephemeral by design (not persisted). They should be relayed directly to SSE clients without touching PostgreSQL. Options: Redis pub/sub, NATS, or shared in-memory channel.
