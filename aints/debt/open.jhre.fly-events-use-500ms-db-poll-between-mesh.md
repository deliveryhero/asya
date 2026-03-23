---
title: FLY events use 500ms DB poll between mesh and api gateways — route directly to SSE clients
priority: 1 # high
---

In dual-gateway mode (api + mesh), FLY events from actors go: sidecar -> mesh gateway -> PostgreSQL (UpdateProgress) -> api gateway polls DB every 500ms -> SSE client. This adds up to 500ms latency per FLY event, making per-token LLM streaming choppy. FLY events are ephemeral by design (not persisted). They should be relayed directly to SSE clients without touching PostgreSQL. Options: Redis pub/sub, NATS, or shared in-memory channel.



The gateway mesh does NOT send SSE to the gateway API. They share PostgreSQL.

Here's the actual architecture:

Client ──SSE──→ Gateway API (blocks in waitAndRelayEvents)
                    │
                    ├─ DB poll every 500ms (cross-process detection)
                    └─ In-process subscription channel (same-pod only)

Sidecar ──POST /mesh/{id}/fly──→ Gateway Mesh
                                    │
                                    └─ Writes to PostgreSQL (envelope_updates table)

For FLY events specifically:
1. Sidecar POSTs FLY payload → gateway mesh → UpdateProgress() writes to PostgreSQL
2. Gateway API polls DB every 500ms → detects the update → relays to SSE client

For terminal status (succeeded/failed):
1. x-sink sidecar POSTs final status → gateway mesh → writes succeeded to PostgreSQL
2. Gateway API detects via DB poll (500ms) → writes TaskStatusUpdateEvent → SSE stream ends

Latency:
- FLY event latency = 500ms worst case (DB poll interval) + DB write time
- This means per-token LLM streaming at ~30 tokens/sec would actually be batched — you'd get ~15 tokens every 500ms poll tick, not
individual token events
- For the "fast path" (in-process subscription channel), latency is near-zero, but only works when api + mesh run in the same pod
(single-gateway mode)

Implication for token streaming: The 500ms DB poll is fine for progress updates but adds noticeable latency for real-time token
streaming. To make per-token streaming smooth, the dual-gateway setup would need either:
- A shared pub/sub channel (Redis, NATS) between mesh and api pods
- Or running in single-gateway mode (both api+mesh in one pod)