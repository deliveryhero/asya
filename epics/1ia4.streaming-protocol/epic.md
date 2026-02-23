---
title: "Streaming Protocol: Upstream Partial Events to Gateway"
priority: 2 # medium
type: epic
---

Implement upstream partial event streaming from generator handlers to the gateway for real-time UI updates (LLM token streaming, progress indicators). Upstream events are transport-level — they flow directly from sidecar to gateway via HTTP, never entering message queues.

Depends on epic 1fbe (HTTP-over-Unix-socket protocol between sidecar and runtime). See `rfc.md` for design rationale and the explicit rejection of queue-based partial event routing.
