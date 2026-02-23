---
title: "Sidecar: HTTP streaming events to gateway"
priority: 2 # medium
type: task
tags:
  - type:feature
---





Forward streaming events from runtime to the gateway via HTTP for real-time user delivery.

## Changes

### src/asya-sidecar/ (Go)
- When receiving a 'stream' frame from runtime, POST it to the gateway HTTP endpoint
- Endpoint: POST /api/v1/envelopes/{envelope_id}/events
- Include envelope_id for SSE/WebSocket correlation
- Fire-and-forget (don't block on gateway response, but log errors)

### src/asya-gateway/ (Go)
- New endpoint: POST /api/v1/envelopes/{envelope_id}/events
- Accept streaming events from sidecars
- Forward to connected SSE/WebSocket clients watching this envelope_id
- Store in envelope event history for late-joining clients

## Design
- Sidecar already knows gateway URL (ASYA_GATEWAY_URL env var)
- Events are fire-and-forget from sidecar's perspective
- Gateway correlates events by envelope_id to active SSE connections
- If no client is listening, events are stored for later retrieval

## Test Plan
- Integration test: sidecar sends streaming event, gateway receives it
- Integration test: SSE client receives streaming events in real-time
- Unit test: sidecar handles gateway unavailability gracefully

## References
- RFC: docs/rfc/agentic-compiler/agentic-compiler-rfc.md Section 11.2
- Related: asya-bi8 dual-channel architecture


---
_Migrated from beads `asya-n5mc`_
